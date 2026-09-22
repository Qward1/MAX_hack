"""Детерминированный текст личного сообщения с карточкой маршрута.

Сообщение собирается из уже готовой `ActionCard` и проверенных данных
справочника: заголовок маршрута, основание, один-два факта канала с
источником, дисклеймер. Модель здесь не участвует и её текст
(`clean_description`) сюда не попадает — он нужен только в черновике
обращения, где его правит человек.

Продукт не подаёт обращение за человека, поэтому формулировки «заявка
отправлена», «обращение зарегистрировано» и «передано в …» невозможны: они
покрыты тем же списком `FORBIDDEN_PHRASES`, что и сама карточка.

При опасности блок безопасности идёт **первым** — раньше заголовка маршрута.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.contracts.common import ContractModel
from domsignal.contracts.routing import (
    ActionCard,
    DangerKind,
    RouteFact,
    SafetyBlock,
)

#: Сколько фактов канала попадает в сообщение.
MAX_FACTS = 2

OPEN_CARD_LABEL = "Открыть карточку"

#: Префикс `launch_ref` карточки маршрута. Заявочные ссылки остаются на `w_`.
ROUTE_CARD_REF_PREFIX = "r_"

#: Вид сообщения в существующем outbox. Второго транспорта не появляется.
ROUTE_CARD_INTENT_KIND = "route.action_card.v1"

_SOURCE_PREFIX = "Источник: "


class RouteCardIntent(ContractModel):
    """Снимок карточки для доставки: всё, что нужно, чтобы собрать текст.

    Намеренно нет ни одного поля под свободный текст модели. Снимок делается
    в момент разбора, поэтому повторная доставка не меняет формулировку и не
    зависит от того, обновился ли справочник.
    """

    route_outcome_id: UUID
    house_id: UUID
    recipient_user_id: UUID
    route_type: str
    title: str
    explanation: str
    basis_text: str | None = None
    basis_source_title: str | None = None
    organization_name: str | None = None
    facts: list[RouteFact] = Field(default_factory=list)
    safety: SafetyBlock | None = None
    disclaimer: str | None = None
    demo_notice: str | None = None
    # Честная формулировка следующего шага, когда ответственный не определён.
    next_step: str | None = None
    dangerous: bool = False


def build_route_card_intent(
    card: ActionCard,
    *,
    route_outcome_id: UUID,
    house_id: UUID,
    recipient_user_id: UUID,
    danger_kinds: tuple[DangerKind, ...] = (),
    next_step: str | None = None,
) -> RouteCardIntent:
    """Снять с карточки ровно то, что попадёт в личное сообщение."""
    basis = card.route.basis
    return RouteCardIntent(
        route_outcome_id=route_outcome_id,
        house_id=house_id,
        recipient_user_id=recipient_user_id,
        route_type=card.route.route_type,
        title=card.title,
        explanation=card.explanation,
        basis_text=basis.text if basis else None,
        basis_source_title=basis.source_title if basis else None,
        organization_name=card.route.organization_name,
        facts=list(card.facts[:MAX_FACTS]),
        safety=card.safety,
        disclaimer=card.disclaimer,
        demo_notice=card.demo_notice,
        next_step=next_step,
        dangerous=bool(danger_kinds) or card.safety is not None,
    )


def safety_lines(safety: SafetyBlock) -> list[str]:
    """Строки проверенной памятки: личное сообщение и памятка в чат общие."""
    lines = [safety.title, *safety.lines]
    if safety.phone:
        lines.append(f"Единый номер экстренных служб: {safety.phone}")
    lines.extend(f"— {step.text} ({step.source_title})" for step in safety.steps)
    if safety.source_title:
        lines.append(f"{_SOURCE_PREFIX}{safety.source_title}")
    return lines


def _fact_lines(facts: list[RouteFact]) -> list[str]:
    return [f"{fact.text}\n{_SOURCE_PREFIX}{fact.source_title}" for fact in facts[:MAX_FACTS]]


def render_route_card(intent: RouteCardIntent, *, ref: str) -> PersonalMessage:
    """Собрать личное сообщение. Один и тот же снимок даёт один и тот же текст."""
    blocks: list[str] = []
    # Памятка безопасности идёт первой при любом маршруте.
    if intent.dangerous and intent.safety is not None:
        blocks.append("\n".join(safety_lines(intent.safety)))
    blocks.append(intent.title)
    blocks.append(intent.explanation)
    if intent.basis_text:
        basis = intent.basis_text
        if intent.basis_source_title:
            basis = f"{basis}\n{_SOURCE_PREFIX}{intent.basis_source_title}"
        blocks.append(basis)
    if intent.next_step:
        blocks.append(intent.next_step)
    blocks.extend(_fact_lines(intent.facts))
    if intent.disclaimer:
        blocks.append(intent.disclaimer)
    if intent.demo_notice:
        blocks.append(intent.demo_notice)
    return PersonalMessage(
        "\n\n".join(blocks),
        ((MessageButton("open_app", OPEN_CARD_LABEL, ref),),),
    )
