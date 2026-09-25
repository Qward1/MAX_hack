"""Детерминированный текст личного сообщения с карточкой маршрута.

Сообщение собирается из уже готовой `ActionCard` и проверенных данных
справочника: заголовок маршрута, основание, один-два факта канала,
дисклеймер и в конце одна строка «Информация взята с: …» со ссылкой
источника (P6b, владелец: без «Источник: …» у каждого факта, без «Проверено
без входа …» и без повторов). Источники фактов целиком — в карточке mini app.
Модель здесь не участвует и её текст (`clean_description`) сюда не попадает —
он нужен только в черновике обращения, где его правит человек.

Продукт не подаёт обращение за человека, поэтому формулировки «заявка
отправлена», «обращение зарегистрировано» и «передано в …» невозможны: они
покрыты тем же списком `FORBIDDEN_PHRASES`, что и сама карточка.

При опасности блок безопасности идёт **первым** — раньше заголовка маршрута.
"""

from __future__ import annotations

import re
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
from domsignal.services.action_cards import EXPLANATIONS_COVERED_BY_BASIS

#: Сколько фактов канала попадает в сообщение.
MAX_FACTS = 2

OPEN_CARD_LABEL = "Открыть карточку"

#: Префикс `launch_ref` карточки маршрута. Заявочные ссылки остаются на `w_`.
ROUTE_CARD_REF_PREFIX = "r_"

#: Вид сообщения в существующем outbox. Второго транспорта не появляется.
ROUTE_CARD_INTENT_KIND = "route.action_card.v1"

_SOURCE_PREFIX = "Источник: "
SOURCES_PREFIX = "Информация взята с: "
STEPS_HEADING = "Что делать:"
#: Подписи кнопок — как на экранах mini app (`features/incidents/presentation.ts`,
#: `features/appeals/AppealDraftScreen.tsx`): инструкция ведёт по ним (P6b, владелец).
_APPEAL_STEPS = (
    f"Нажмите «{OPEN_CARD_LABEL}» под этим сообщением.",
    "В карточке нажмите «{prepare}».",
    "Проверьте текст обращения: верно ли указаны место и суть проблемы. "
    "При необходимости поправьте его и нажмите «Сохранить правку».",
    "Нажмите «Скопировать текст», затем «Открыть официальный сервис».",
    "В официальном сервисе войдите, вставьте текст в форму и отправьте обращение.",
    "Вернитесь в карточку и нажмите «Я отправил(а) обращение», чтобы отметить подачу.",
)
#: Цитата «…» факта, уже показанная в основании, — повтор.
_QUOTE = re.compile(r"«([^«»]{20,})»")


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
    basis_source_url: str | None = None
    organization_name: str | None = None
    facts: list[RouteFact] = Field(default_factory=list)
    safety: SafetyBlock | None = None
    disclaimer: str | None = None
    demo_notice: str | None = None
    # Честная формулировка следующего шага, когда ответственный не определён.
    next_step: str | None = None
    dangerous: bool = False
    # Пошаговая инструкция по кнопкам mini app (P6b); пусто — без инструкции.
    steps: list[str] = Field(default_factory=list)


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
    prepare = next(
        (action for action in card.actions if action.type == "prepare_appeal" and action.enabled),
        None,
    )
    steps = (
        [step.format(prepare=prepare.label) for step in _APPEAL_STEPS]
        if prepare is not None
        else []
    )
    return RouteCardIntent(
        route_outcome_id=route_outcome_id,
        house_id=house_id,
        recipient_user_id=recipient_user_id,
        route_type=card.route.route_type,
        title=card.title,
        explanation=card.explanation,
        basis_text=basis.text if basis else None,
        basis_source_title=basis.source_title if basis else None,
        basis_source_url=basis.source_url if basis else None,
        organization_name=card.route.organization_name,
        facts=list(card.facts[:MAX_FACTS]),
        safety=card.safety,
        disclaimer=card.disclaimer,
        demo_notice=card.demo_notice,
        next_step=next_step,
        dangerous=bool(danger_kinds) or card.safety is not None,
        steps=steps,
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


def _display_url(url: str) -> str:
    """Ссылка для текста сообщения: без схемы и завершающего «/»."""
    return re.sub(r"^https?://", "", url.strip()).rstrip("/")


def _repeats(text: str, shown: str) -> bool:
    return any(quote in shown for quote in _QUOTE.findall(text))


def render_route_card(intent: RouteCardIntent, *, ref: str) -> PersonalMessage:
    """Собрать личное сообщение. Один и тот же снимок даёт один и тот же текст."""
    blocks: list[str] = []
    sources: list[str] = []
    # Памятка безопасности идёт первой при любом маршруте.
    if intent.dangerous and intent.safety is not None:
        blocks.append(
            "\n".join(
                line for line in safety_lines(intent.safety) if not line.startswith(_SOURCE_PREFIX)
            )
        )
        if intent.safety.source_url:
            sources.append(intent.safety.source_url)
    blocks.append(intent.title)
    if not (intent.basis_text and intent.explanation in EXPLANATIONS_COVERED_BY_BASIS):
        blocks.append(intent.explanation)
    if intent.basis_text:
        blocks.append(intent.basis_text)
        if intent.basis_source_url:
            sources.append(intent.basis_source_url)
    if intent.next_step:
        blocks.append(intent.next_step)
    for fact in intent.facts[:MAX_FACTS]:
        if not _repeats(fact.text, "\n".join(blocks)):
            blocks.append(fact.text)
    if intent.steps:
        numbered = [f"{number}. {step}" for number, step in enumerate(intent.steps, start=1)]
        blocks.append("\n".join([STEPS_HEADING, *numbered]))
    if intent.disclaimer:
        blocks.append(intent.disclaimer)
    if intent.demo_notice:
        blocks.append(intent.demo_notice)
    shown = list(dict.fromkeys(_display_url(url) for url in sources))
    if shown:
        blocks.append(SOURCES_PREFIX + ", ".join(shown))
    return PersonalMessage(
        "\n\n".join(blocks),
        ((MessageButton("open_app", OPEN_CARD_LABEL, ref),),),
    )
