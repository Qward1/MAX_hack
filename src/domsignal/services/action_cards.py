"""Детерминированная сборка ActionCard из маршрута. LLM здесь не участвует.

Карточка отвечает на вопрос «что делать дальше» и не утверждает, что обращение
куда-то отправлено или где-то зарегистрировано: официальный канал открывает сам
человек. Тексты — шаблоны продукта, факты и ссылки — только из проверенных
записей справочника.
"""

from __future__ import annotations

from collections.abc import Sequence

from domsignal.contracts.routing import (
    ActionCard,
    ActionCardAction,
    ActionType,
    Audience,
    CardSource,
    DangerKind,
    ResponsibilityRoute,
    RouteChannel,
    RouteFact,
    SafetyBlock,
)
from domsignal.core.routing import HouseRoutingContext
from domsignal.services.routing import RoutingService

#: Формулировки, которых в карточке быть не может: продукт не подаёт обращение
#: за человека, не регистрирует его и не назначает нормативных сроков.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "заявка отправлена",
    "обращение отправлено",
    "обращение зарегистрировано",
    "передано в",
    "срок исполнения",
    "обязан",
)

EXTERNAL_ROUTES = frozenset(
    {"municipality", "resource_supplier", "regional_operator", "other_authority"}
)

DEMO_NOTICE = "Тестовые данные"
CHAT_DISCLAIMER = "Сообщение в домовом чате не является официальным обращением."
EXTERNAL_DISCLAIMER = (
    "ДомСигнал не отправляет обращения за вас — вы отправляете его сами в официальном сервисе."
)

_NO_UK_REASON = "К дому не подключена управляющая компания."
_UNVERIFIED_CHANNEL_REASON = "Канал ещё не проверен в справочнике."
_NO_URL_REASON = "Точная ссылка входа ещё не заполнена в справочнике."

_TITLE_UK = "Это зона ответственности вашей управляющей компании"
_TITLE_EXTERNAL = "Проблема, вероятно, относится не к вашей УК"
_TITLE_EMERGENCY = "Похоже на ситуацию для экстренных служб"
_TITLE_CHOICE = "Нужна проверка диспетчером"
_TITLE_UNKNOWN = "Не удалось надёжно определить ответственную организацию"

_EXPLANATION_UK = "Общее имущество дома обслуживает управляющая компания — это её первая линия."
_EXPLANATION_ROUTED = "Ответственное ведомство определит официальный сервис."
_EXPLANATION_NO_CHANNEL = (
    "Проверенного канала пока нет — маршрут уточняет диспетчер управляющей компании."
)
_EXPLANATION_CHOICE = (
    "Подходит и управляющая компания, и внешний маршрут: выбор остаётся за диспетчером."
)
_EXPLANATION_UNKNOWN = "Правила для этой проблемы в справочнике нет, а догадку продукт не выдаёт."
_EXPLANATION_EMERGENCY = "Такие сообщения адресуются экстренным службам, а не обычной заявке."
#: Общие пояснения, которые основание маршрута пересказывает своими словами:
#: в личном сообщении при основании они не повторяются (P6b, владелец).
EXPLANATIONS_COVERED_BY_BASIS = frozenset(
    {_EXPLANATION_UK, _EXPLANATION_ROUTED, _EXPLANATION_EMERGENCY}
)


def _action(
    action_type: ActionType,
    label: str,
    *,
    enabled: bool = True,
    reason: str | None = None,
    url: str | None = None,
    phone: str | None = None,
) -> ActionCardAction:
    return ActionCardAction(
        type=action_type,
        label=label,
        enabled=enabled,
        reason=reason,
        url=url,
        phone=phone,
    )


def _official_channel(channels: Sequence[RouteChannel]) -> RouteChannel | None:
    for channel in channels:
        if channel.channel_type in {"official_web", "max_bot", "email"}:
            return channel
    return None


def _phone_channel(channels: Sequence[RouteChannel]) -> RouteChannel | None:
    for channel in channels:
        if channel.phone:
            return channel
    return None


def _open_channel_action(channel: RouteChannel) -> ActionCardAction:
    if channel.url:
        return _action("open_official_channel", f"Перейти: {channel.label}", url=channel.url)
    reason = _NO_URL_REASON
    if channel.entry_hint:
        reason = f"{_NO_URL_REASON} Вход: {channel.entry_hint}"
    return _action(
        "open_official_channel", f"Перейти: {channel.label}", enabled=False, reason=reason
    )


def _report_to_uk(can_report_to_uk: bool) -> ActionCardAction:
    return _action(
        "report_to_uk_anyway",
        "Всё равно сообщить в УК",
        enabled=can_report_to_uk,
        reason=None if can_report_to_uk else _NO_UK_REASON,
    )


def _create_ticket(route: ResponsibilityRoute) -> ActionCardAction:
    return _action(
        "create_ticket",
        "Сообщить в УК",
        enabled=route.can_create_ticket,
        reason=None if route.can_create_ticket else _NO_UK_REASON,
    )


def _uk_actions(
    route: ResponsibilityRoute,
    audience: Audience,
    existing_ticket_ref: str | None,
) -> list[ActionCardAction]:
    actions = [_create_ticket(route)]
    if existing_ticket_ref:
        actions.append(_action("join_existing", "Присоединиться к уже созданной заявке"))
    if audience == "resident":
        channel = _official_channel(route.channels)
        if channel is not None:
            actions.append(_open_channel_action(channel))
        else:
            actions.append(
                _action(
                    "open_official_channel",
                    "Официальное обращение через «Госуслуги Дом»",
                    enabled=False,
                    reason=_UNVERIFIED_CHANNEL_REASON,
                )
            )
    else:
        actions.append(_action("not_a_problem", "Отметить, что проблемы нет"))
    return actions


def _external_actions(
    route: ResponsibilityRoute,
    audience: Audience,
    can_report_to_uk: bool,
) -> list[ActionCardAction]:
    actions: list[ActionCardAction] = []
    channel = _official_channel(route.channels)
    if channel is not None:
        actions.append(_open_channel_action(channel))
    phone = _phone_channel(route.channels)
    if phone is not None and phone.phone:
        actions.append(_action("call_phone", f"Позвонить: {phone.label}", phone=phone.phone))
    if route.can_prepare_appeal:
        actions.append(_action("prepare_appeal", "Подготовить текст обращения"))
    if not route.channels:
        if audience == "resident":
            actions.append(_report_to_uk(can_report_to_uk))
        else:
            actions.append(_action("operator_review", "Определить маршрут вручную"))
        return actions
    if audience == "resident":
        actions.append(_report_to_uk(can_report_to_uk))
    else:
        actions.append(_action("route_external", "Отметить внешний маршрут"))
        actions.append(_action("not_a_problem", "Отметить, что проблемы нет"))
        actions.append(_create_ticket(route))
    return actions


def _title_and_explanation(route: ResponsibilityRoute) -> tuple[str, str]:
    if route.requires_operator_choice:
        return _TITLE_CHOICE, _EXPLANATION_CHOICE
    if route.route_type == "uk_internal":
        return _TITLE_UK, _EXPLANATION_UK
    if route.route_type == "emergency_service":
        return _TITLE_EMERGENCY, _EXPLANATION_EMERGENCY
    if route.route_type in EXTERNAL_ROUTES:
        if route.organization_name:
            return _TITLE_EXTERNAL, f"Вероятно, отвечает: {route.organization_name}."
        if any(channel.routes_to_competent_authority for channel in route.channels):
            return _TITLE_EXTERNAL, _EXPLANATION_ROUTED
        if not route.channels:
            return _TITLE_EXTERNAL, _EXPLANATION_NO_CHANNEL
        return _TITLE_EXTERNAL, _EXPLANATION_ROUTED
    return _TITLE_UNKNOWN, _EXPLANATION_UNKNOWN


def _disclaimer(route: ResponsibilityRoute, source: CardSource) -> str | None:
    parts: list[str] = []
    if source == "chat":
        parts.append(CHAT_DISCLAIMER)
    if route.route_type in EXTERNAL_ROUTES or route.route_type == "emergency_service":
        parts.append(EXTERNAL_DISCLAIMER)
    return " ".join(parts) or None


def _facts(route: ResponsibilityRoute) -> list[RouteFact]:
    facts: list[RouteFact] = []
    for channel in route.channels:
        facts.extend(channel.facts)
    return facts


def build_action_card(
    route: ResponsibilityRoute,
    *,
    audience: Audience,
    source: CardSource,
    danger_kinds: Sequence[DangerKind] = (),
    existing_ticket_ref: str | None = None,
    is_demo: bool = False,
    can_report_to_uk: bool = False,
    safety: SafetyBlock | None = None,
) -> ActionCard:
    """Собрать карточку следующего шага для жителя или оператора."""
    title, explanation = _title_and_explanation(route)
    if route.requires_operator_choice:
        actions = (
            [_report_to_uk(can_report_to_uk)]
            if audience == "resident"
            else [_action("operator_review", "Выбрать маршрут")]
        )
    elif route.route_type == "uk_internal":
        actions = _uk_actions(route, audience, existing_ticket_ref)
    elif route.route_type == "emergency_service" or route.route_type in EXTERNAL_ROUTES:
        actions = _external_actions(route, audience, can_report_to_uk)
    else:
        actions = (
            [_report_to_uk(can_report_to_uk)]
            if audience == "resident"
            else [_action("operator_review", "Определить маршрут вручную")]
        )

    dangerous = bool(danger_kinds) or route.route_type == "emergency_service"
    block = safety if dangerous else None
    if block is not None and block.phone:
        emergency_call = _action("call_phone", f"Позвонить {block.phone}", phone=block.phone)
        actions = [emergency_call] + [
            action
            for action in actions
            if not (action.type == "call_phone" and action.phone == block.phone)
        ]

    return ActionCard(
        route=route,
        audience=audience,
        source=source,
        title=title,
        explanation=explanation,
        safety=block,
        facts=_facts(route),
        actions=actions,
        disclaimer=_disclaimer(route, source),
        demo_notice=DEMO_NOTICE if is_demo else None,
        existing_ticket_ref=existing_ticket_ref,
    )


class ActionCardBuilder:
    """Сборщик карточек, связанный с загруженным справочником.

    Берёт памятку безопасности из продуктовых данных и подставляет признаки
    дома, чтобы карточка не предлагала действие, которого у дома нет.
    """

    def __init__(self, routing: RoutingService) -> None:
        self.routing = routing

    def build(
        self,
        route: ResponsibilityRoute,
        house: HouseRoutingContext,
        *,
        audience: Audience,
        source: CardSource,
        danger_kinds: Sequence[DangerKind] = (),
        existing_ticket_ref: str | None = None,
    ) -> ActionCard:
        return build_action_card(
            route,
            audience=audience,
            source=source,
            danger_kinds=danger_kinds,
            existing_ticket_ref=existing_ticket_ref,
            is_demo=house.is_demo,
            can_report_to_uk=house.has_active_connected_uk,
            safety=self.routing.safety(house, danger_kinds),
        )
