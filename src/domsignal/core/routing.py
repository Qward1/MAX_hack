"""Responsibility Router: кто, вероятно, отвечает за проблему.

Чистая детерминированная логика без I/O и без модели. На вход приходят код
подтипа и предварительная территория из контракта AI плюс серверный контекст
дома; справочник передаётся уже загруженным. Ни одного непроверенного органа,
телефона или ссылки маршрут не публикует: непроверенная запись остаётся
счётчиком `hidden_unverified_channels`, а отсутствие правила — честным
`unknown`, а не догадкой.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date

from domsignal.contracts.routing import (
    DangerKind,
    LocationScope,
    ResponsibilityRoute,
    RouteAlternative,
    RouteBasis,
    RouteChannel,
    RouteFact,
    RouteMatch,
    RouteType,
    SafetyBlock,
    SafetyStep,
    TerritoryPolicy,
)
from domsignal.core.responsibility import (
    STALE_AFTER_DAYS,
    Basis,
    Channel,
    EffectiveDirectory,
    Organization,
    ResponsibilityDirectory,
    Rule,
    SafetyBlockData,
    Verification,
)

#: Код подтипа, которым продукт заменяет всё, чего нет в таксономии.
UNSPECIFIED_SUBTYPE = "other.unspecified"

#: Версия справочника, когда он не загрузился: маршрут остаётся unknown.
UNAVAILABLE_DIRECTORY_VERSION = "unavailable"

_UK_ALTERNATIVE_REASON = "Внутридомовые сети обслуживает управляющая компания дома."
_SUPPLIER_ALTERNATIVE_REASON = (
    "Отключение может идти от внешних сетей — тогда отвечает ресурсоснабжающая организация."
)
_MUNICIPAL_ALTERNATIVE_REASON = "Территория может относиться к муниципальной."


@dataclass(frozen=True)
class HouseRoutingContext:
    """Контекст дома с сервера. Из текста сообщения он никогда не берётся."""

    is_demo: bool = False
    has_active_connected_uk: bool = False
    region_code: str | None = None
    municipality_code: str | None = None
    territory_policy: TerritoryPolicy = "unknown"


@dataclass(frozen=True)
class RoutingQuery:
    """Вход роутера: результат разбора плюс контекст дома."""

    subtype: str
    location_scope: LocationScope = "unknown"
    danger_kinds: tuple[DangerKind, ...] = ()
    house: HouseRoutingContext = field(default_factory=HouseRoutingContext)


def unavailable_route() -> ResponsibilityRoute:
    """Справочник недоступен: честный `unknown`, а не догадка об организации."""
    return ResponsibilityRoute(
        route_type="unknown",
        directory_version=UNAVAILABLE_DIRECTORY_VERSION,
        match="none",
    )


def _visible(verification: Verification, *, is_demo: bool) -> bool:
    """Проверенное видно всем, демо — только демо-дому, непроверенное — никому."""
    if verification.status == "verified":
        return True
    return verification.status == "demo" and is_demo


def _channel_dto(channel: Channel, *, today: date) -> RouteChannel:
    return RouteChannel(
        id=channel.id,
        channel_type=channel.channel_type,
        label=channel.label,
        url=channel.url,
        phone=channel.phone,
        entry_hint=channel.entry_hint,
        routes_to_competent_authority=channel.routes_to_competent_authority,
        facts=[
            RouteFact(text=fact.text, source_title=fact.source_title, source_url=fact.source_url)
            for fact in channel.facts
        ],
        verification_status=channel.verification.status,
        verified_at=channel.verification.verified_at,
        source_title=channel.verification.source_title,
        source_url=channel.verification.source_url,
        stale=channel.verification.stale_on(today),
    )


def visible_to_house(verification: Verification, *, is_demo: bool) -> bool:
    """Видна ли запись справочника этому дому."""
    return _visible(verification, is_demo=is_demo)


def channel_dto(channel: Channel, *, today: date) -> RouteChannel:
    """DTO канала справочника без пересчёта маршрута."""
    return _channel_dto(channel, today=today)


def _channels(
    channel_ids: Sequence[str],
    directory: EffectiveDirectory,
    house: HouseRoutingContext,
    today: date,
) -> tuple[list[RouteChannel], int]:
    visible: list[RouteChannel] = []
    hidden = 0
    for channel_id in channel_ids:
        channel = directory.channels.get(channel_id)
        if channel is None:
            hidden += 1
            continue
        if not channel.available_in(house.region_code):
            continue
        if not _visible(channel.verification, is_demo=house.is_demo):
            hidden += 1
            continue
        visible.append(_channel_dto(channel, today=today))
    return visible, hidden


def _organization(
    organization_id: str | None,
    directory: EffectiveDirectory,
    house: HouseRoutingContext,
) -> Organization | None:
    """Непроверенная организация не называется даже внутри маршрута."""
    if organization_id is None:
        return None
    organization = directory.organizations.get(organization_id)
    if organization is None or not _visible(organization.verification, is_demo=house.is_demo):
        return None
    return organization


def _basis_dto(basis: Basis, verification: Verification, *, rule_id: str | None) -> RouteBasis:
    return RouteBasis(
        rule_id=rule_id,
        text=basis.text,
        source_title=basis.source_title,
        source_url=basis.source_url,
        verified_at=verification.verified_at,
        verification_status=verification.status,
    )


def _route(
    *,
    route_type: RouteType,
    directory: EffectiveDirectory,
    match: RouteMatch,
    basis: RouteBasis | None = None,
    channels: list[RouteChannel] | None = None,
    hidden: int = 0,
    organization: Organization | None = None,
    can_create_ticket: bool = False,
    can_prepare_appeal: bool = False,
    requires_operator_choice: bool = False,
    alternatives: Sequence[RouteAlternative] = (),
    today: date,
) -> ResponsibilityRoute:
    visible = channels or []
    stale = bool(
        basis and basis.verified_at and (today - basis.verified_at).days > STALE_AFTER_DAYS
    )
    stale = stale or any(channel.stale for channel in visible)
    return ResponsibilityRoute(
        route_type=route_type,
        organization_id=organization.id if organization else None,
        organization_name=organization.name if organization else None,
        channels=visible,
        basis=basis,
        directory_version=directory.version,
        directory_verified_at=directory.updated_at,
        automatic_integration=route_type == "uk_internal",
        can_create_ticket=can_create_ticket,
        can_prepare_appeal=can_prepare_appeal,
        requires_operator_choice=requires_operator_choice,
        alternatives=list(alternatives),
        match=match,
        hidden_unverified_channels=hidden,
        stale=stale,
    )


def _unknown_route(directory: EffectiveDirectory, today: date) -> ResponsibilityRoute:
    return _route(route_type="unknown", directory=directory, match="none", today=today)


def _uk_route(
    subtype: str,
    directory: EffectiveDirectory,
    house: HouseRoutingContext,
    today: date,
) -> ResponsibilityRoute:
    default = directory.uk_default
    basis = (
        _basis_dto(default.basis, default.verification, rule_id=None)
        if default is not None
        else None
    )
    alternatives: list[RouteAlternative] = []
    if default is not None and subtype in default.resource_supplier_alternatives:
        alternatives.append(
            RouteAlternative(route_type="resource_supplier", reason=_SUPPLIER_ALTERNATIVE_REASON)
        )
    # Официальный канал заявки в УК (D4: «Госуслуги Дом») — только проверенный.
    channels, hidden = _channels(
        default.channel_ids if default is not None else (), directory, house, today
    )
    return _route(
        route_type="uk_internal",
        directory=directory,
        match="default",
        basis=basis,
        channels=channels,
        hidden=hidden,
        can_create_ticket=house.has_active_connected_uk,
        alternatives=alternatives,
        today=today,
    )


def _rule_route(
    rule: Rule,
    directory: EffectiveDirectory,
    house: HouseRoutingContext,
    today: date,
) -> ResponsibilityRoute:
    channels, hidden = _channels(rule.channel_ids, directory, house, today)
    return _route(
        route_type=rule.route_type,
        directory=directory,
        match="rule",
        basis=_basis_dto(rule.basis, rule.verification, rule_id=rule.id),
        channels=channels,
        hidden=hidden,
        organization=_organization(rule.organization_id, directory, house),
        can_prepare_appeal=rule.can_prepare_appeal and bool(channels),
        today=today,
    )


def _operator_choice(
    directory: EffectiveDirectory,
    alternatives: Sequence[RouteAlternative],
    today: date,
    *,
    match: RouteMatch,
) -> ResponsibilityRoute:
    return _route(
        route_type="unknown",
        directory=directory,
        match=match,
        requires_operator_choice=True,
        alternatives=alternatives,
        today=today,
    )


def _from_rules(
    matched: Sequence[Rule],
    directory: EffectiveDirectory,
    house: HouseRoutingContext,
    today: date,
) -> ResponsibilityRoute:
    """Первое совпавшее правило; равноправные и расходящиеся — выбор оператора."""
    best = matched[0]
    peers = [
        rule
        for rule in matched
        if rule.priority == best.priority and rule.layer_depth == best.layer_depth
    ]
    distinct = {(rule.route_type, rule.organization_id) for rule in peers}
    if len(distinct) > 1:
        return _operator_choice(
            directory,
            [
                RouteAlternative(route_type=rule.route_type, reason=rule.basis.text)
                for rule in peers
            ],
            today,
            match="rule",
        )
    return _rule_route(best, directory, house, today)


def resolve_route(
    query: RoutingQuery,
    directory: ResponsibilityDirectory,
    *,
    known_subtypes: Collection[str],
    today: date,
) -> ResponsibilityRoute:
    """Определить маршрут ответственности. Никогда не выдумывает организацию."""
    house = query.house
    effective = directory.effective(house.region_code, house.municipality_code)
    subtype = query.subtype if query.subtype in known_subtypes else UNSPECIFIED_SUBTYPE
    scope = query.location_scope
    matched = [
        rule for rule in effective.rules if rule.matches(subtype, scope, query.danger_kinds)
    ]

    # Экстренный маршрут не уступает внутренней заявке: запах газа остаётся
    # вызовом службы, даже когда он на территории общего имущества дома. Какие
    # виды опасности ведут в экстренную службу ещё до подтипа, решают данные
    # справочника (`match.danger_kinds`), а не код: другие правила видов
    # опасности не знают, поэтому «затопило» маршрут не меняет.
    emergency = [rule for rule in matched if rule.route_type == "emergency_service"]
    if emergency:
        return _from_rules(emergency, effective, house, today)

    # Правило справочника, названное по подтипу, точнее типового распределения:
    # «газ не подаётся» остаётся газоснабжающей организации и в подъезде,
    # вывоз ТКО — региональному оператору и во дворе (P6, эталон маршрутов).
    # Приоритет — только перед ветками общего имущества и двора; муниципальные
    # правила зависят от территории, их по-прежнему решает профиль дома.
    if scope in {"house_common", "house_territory"}:
        specific = [rule for rule in matched if subtype in rule.subtypes]
        if specific and all(rule.route_type != "municipality" for rule in specific):
            return _from_rules(specific, effective, house, today)

    default = effective.uk_default
    uk_subtype = default is not None and subtype in default.subtypes

    # Общее имущество с подключённой УК — её зона, и для неопределённого
    # подтипа тоже: форма с категорией создаёт заявку УК без подтипа, и её
    # карточка не может говорить «ответственный не определён».
    if scope == "house_common" and house.has_active_connected_uk:
        return _uk_route(subtype, effective, house, today)

    if scope == "house_territory":
        return _territory_route(subtype, effective, house, today)

    if matched:
        return _from_rules(matched, effective, house, today)

    if uk_subtype and scope in {"house_common", "unknown"}:
        if house.has_active_connected_uk:
            return _uk_route(subtype, effective, house, today)
        return _unknown_route(effective, today)

    # Проблема видна в квартире, но система общедомовая (холодные батареи).
    if (
        scope == "apartment"
        and default is not None
        and subtype in default.apartment_subtypes
        and house.has_active_connected_uk
    ):
        return _uk_route(subtype, effective, house, today)

    return _unknown_route(effective, today)


def route_of_type(
    route_type: RouteType,
    query: RoutingQuery,
    directory: ResponsibilityDirectory,
    *,
    known_subtypes: Collection[str],
    today: date,
) -> ResponsibilityRoute:
    """Маршрут типа, который выбрал человек, когда роутер не смог решить сам.

    Тип задаёт оператор; организацию и канал подставляет справочник — первое
    по приоритету правило этого типа для подтипа или вида опасности. Нет
    такого правила — организация и канал остаются пустыми: продукт ничего не
    дописывает за справочник и не принимает свободный текст организации.
    """
    house = query.house
    effective = directory.effective(house.region_code, house.municipality_code)
    subtype = query.subtype if query.subtype in known_subtypes else UNSPECIFIED_SUBTYPE
    if route_type == "uk_internal":
        return _uk_route(subtype, effective, house, today)
    if route_type == "unknown":
        return _unknown_route(effective, today)
    candidates = [
        rule
        for rule in effective.rules
        if rule.route_type == route_type
        and (
            subtype in rule.subtypes
            or any(kind in rule.danger_kinds for kind in query.danger_kinds)
        )
    ]
    if candidates:
        return _rule_route(candidates[0], effective, house, today)
    return _route(route_type=route_type, directory=effective, match="none", today=today)


def _territory_route(
    subtype: str,
    directory: EffectiveDirectory,
    house: HouseRoutingContext,
    today: date,
) -> ResponsibilityRoute:
    """Придомовая территория решается профилем дома, а не текстом сообщения."""
    if house.territory_policy == "uk":
        if house.has_active_connected_uk:
            return _uk_route(subtype, directory, house, today)
        return _unknown_route(directory, today)
    if house.territory_policy == "municipal":
        municipal = [
            rule for rule in directory.rules if rule.matches(subtype, "municipal_territory")
        ]
        if municipal:
            return _from_rules(municipal, directory, house, today)
        return _unknown_route(directory, today)
    alternatives: list[RouteAlternative] = []
    if house.has_active_connected_uk:
        alternatives.append(
            RouteAlternative(route_type="uk_internal", reason=_UK_ALTERNATIVE_REASON)
        )
    alternatives.append(
        RouteAlternative(route_type="municipality", reason=_MUNICIPAL_ALTERNATIVE_REASON)
    )
    return _operator_choice(directory, alternatives, today, match="default")


def safety_block(
    directory: ResponsibilityDirectory,
    danger_kinds: Sequence[DangerKind],
    house: HouseRoutingContext,
) -> SafetyBlock | None:
    """Проверенная памятка безопасности из продуктовых данных."""
    effective = directory.effective(house.region_code, house.municipality_code)
    block = effective.safety_for(danger_kinds)
    return _safety_dto(block) if block is not None else None


def _safety_dto(block: SafetyBlockData) -> SafetyBlock:
    return SafetyBlock(
        title=block.title,
        lines=list(block.lines),
        phone=block.phone,
        steps=[
            SafetyStep(text=step.text, source_title=step.source_title, source_url=step.source_url)
            for step in block.steps
        ],
        source_title=block.verification.source_title,
        source_url=block.verification.source_url,
        verified_at=block.verification.verified_at,
    )
