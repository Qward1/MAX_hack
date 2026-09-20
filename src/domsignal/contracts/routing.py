"""DTO детерминированного Responsibility Router и ActionCard.

Модель здесь не участвует: маршрут и карточка собираются правилами по
проверенному справочнику. Эти DTO пока не публикуются ни одним endpoint —
HTTP-граница появится отдельным срезом, поэтому OpenAPI не меняется.

`LocationScope` и `DangerKind` объявлены продуктом заново, а не импортированы
из внутреннего контракта AI: продукт проверяет вход, а не доверяет ему.
Совпадение значений закреплено тестом.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from domsignal.contracts.common import ContractModel

RouteType = Literal[
    "uk_internal",
    "municipality",
    "resource_supplier",
    "emergency_service",
    "regional_operator",
    "other_authority",
    "unknown",
]
OrganizationKind = Literal[
    "municipality",
    "resource_supplier",
    "emergency_service",
    "regional_operator",
    "other_authority",
]
ChannelType = Literal["official_web", "phone", "max_bot", "email", "in_person"]
VerificationStatus = Literal["verified", "needs_verification", "demo"]
TerritoryPolicy = Literal["uk", "municipal", "mixed", "unknown"]
RouteMatch = Literal["rule", "default", "none"]
Audience = Literal["resident", "operator"]
CardSource = Literal["chat", "explicit"]
ActionType = Literal[
    "create_ticket",
    "join_existing",
    "open_official_channel",
    "call_phone",
    "prepare_appeal",
    "mark_filed_self_reported",
    "report_to_uk_anyway",
    "operator_review",
    "route_external",
    "not_a_problem",
]
LocationScope = Literal[
    "apartment",
    "house_common",
    "house_territory",
    "municipal_territory",
    "external_network",
    "other_building",
    "unknown",
]
DangerKind = Literal[
    "gas",
    "smoke_fire",
    "electric",
    "person_trapped",
    "flooding",
    "structural",
    "other_hazard",
]

ROUTE_TYPES: tuple[RouteType, ...] = (
    "uk_internal",
    "municipality",
    "resource_supplier",
    "emergency_service",
    "regional_operator",
    "other_authority",
    "unknown",
)
TERRITORY_POLICIES: tuple[TerritoryPolicy, ...] = ("uk", "municipal", "mixed", "unknown")
LOCATION_SCOPES: tuple[LocationScope, ...] = (
    "apartment",
    "house_common",
    "house_territory",
    "municipal_territory",
    "external_network",
    "other_building",
    "unknown",
)
DANGER_KINDS: tuple[DangerKind, ...] = (
    "gas",
    "smoke_fire",
    "electric",
    "person_trapped",
    "flooding",
    "structural",
    "other_hazard",
)


class RouteFact(ContractModel):
    """Проверяемое утверждение о канале вместе с его источником."""

    text: str
    source_title: str
    source_url: str | None = None


class RouteBasis(ContractModel):
    """Почему выбран этот маршрут. Основание не является нормой и не задаёт срок."""

    rule_id: str | None = None
    text: str
    source_title: str
    source_url: str | None = None
    verified_at: date | None = None
    verification_status: VerificationStatus


class RouteChannel(ContractModel):
    """Видимый жителю канал. Непроверенные каналы сюда не попадают."""

    id: str
    channel_type: ChannelType
    label: str
    url: str | None = None
    phone: str | None = None
    entry_hint: str | None = None
    routes_to_competent_authority: bool = False
    facts: list[RouteFact] = Field(default_factory=list)
    verification_status: VerificationStatus
    verified_at: date | None = None
    source_title: str | None = None
    source_url: str | None = None
    stale: bool = False


class RouteAlternative(ContractModel):
    """Другой допустимый маршрут; решение остаётся за человеком."""

    route_type: RouteType
    reason: str


class ResponsibilityRoute(ContractModel):
    """Кто, вероятно, отвечает за проблему, и что об этом известно проверенного."""

    route_type: RouteType
    organization_id: str | None = None
    organization_name: str | None = None
    channels: list[RouteChannel] = Field(default_factory=list)
    basis: RouteBasis | None = None
    directory_version: str
    directory_verified_at: date | None = None
    automatic_integration: bool = False
    can_create_ticket: bool = False
    can_prepare_appeal: bool = False
    requires_operator_choice: bool = False
    alternatives: list[RouteAlternative] = Field(default_factory=list)
    match: RouteMatch
    hidden_unverified_channels: int = 0
    stale: bool = False


class SafetyStep(ContractModel):
    """Шаг памятки. Допустим только вместе с официальным источником."""

    text: str
    source_title: str
    source_url: str | None = None


class SafetyBlock(ContractModel):
    """Проверенная памятка безопасности из продуктовых данных, не из модели."""

    title: str
    lines: list[str] = Field(default_factory=list)
    phone: str | None = None
    steps: list[SafetyStep] = Field(default_factory=list)
    source_title: str | None = None
    source_url: str | None = None
    verified_at: date | None = None


class ActionCardAction(ContractModel):
    """Следующий шаг. `enabled=false` всегда сопровождается причиной."""

    type: ActionType
    label: str
    enabled: bool
    reason: str | None = None
    url: str | None = None
    phone: str | None = None


class ActionCard(ContractModel):
    """Детерминированная карточка следующего шага. LLM её не генерирует."""

    route: ResponsibilityRoute
    audience: Audience
    source: CardSource
    title: str
    explanation: str
    safety: SafetyBlock | None = None
    facts: list[RouteFact] = Field(default_factory=list)
    actions: list[ActionCardAction] = Field(default_factory=list)
    disclaimer: str | None = None
    demo_notice: str | None = None
    existing_ticket_ref: str | None = None
    generated_by: Literal["rules"] = "rules"
