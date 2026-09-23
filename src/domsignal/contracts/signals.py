"""DTO очереди сигналов оператора (P5): список, деталь и решения.

Сигнал — наблюдение из домового чата, а не заявка. Заявку из него создаёт
только оператор. Все тексты, которые здесь видит оператор, — шаблоны
продукта, дословные цитаты жителей или записи справочника; свободного текста
модели в DTO нет.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from domsignal.contracts.common import ContractModel, PageMeta
from domsignal.contracts.incidents import DuplicateCandidate
from domsignal.contracts.routing import (
    ActionCard,
    DangerKind,
    LocationScope,
    RouteType,
    VerificationStatus,
)
from domsignal.core.incidents import ReportCategory

SignalStrength = Literal["critical", "strong", "medium", "weak"]
SignalStatus = Literal["new", "in_review", "converted", "routed_external", "dismissed"]
DismissReason = Literal["not_a_problem", "duplicate", "resolved", "out_of_scope", "spam"]
SignalActionCode = Literal["create-ticket", "join", "route-external", "choose-route", "dismiss"]
DangerSource = Literal["rules", "semantic"]
#: Кто определил текущий маршрут сигнала: роутер по справочнику или оператор.
RouteSource = Literal["router", "operator"]

SIGNAL_STRENGTHS: tuple[SignalStrength, ...] = ("critical", "strong", "medium", "weak")
SIGNAL_STATUSES: tuple[SignalStatus, ...] = (
    "new",
    "in_review",
    "converted",
    "routed_external",
    "dismissed",
)
DISMISS_REASONS: tuple[DismissReason, ...] = (
    "not_a_problem",
    "duplicate",
    "resolved",
    "out_of_scope",
    "spam",
)


class SignalQuoteView(ContractModel):
    """Дословная цитата жителя с псевдонимом автора и временем."""

    author: str
    sent_at: datetime
    text: str


class SignalEvidenceValue(ContractModel):
    """Значение места или времени — только вместе с дословной цитатой."""

    value: str
    quote: str


class SignalPlace(ContractModel):
    entrance: SignalEvidenceValue | None = None
    floor: SignalEvidenceValue | None = None
    since: SignalEvidenceValue | None = None


class SignalTerritory(ContractModel):
    scope: LocationScope
    label: str
    quote: str | None = None


class DangerEvidenceView(ContractModel):
    """Основание опасности: срабатывание правил или цитата разбора.

    При `evidence_unverified` цитаты разбора не показываются: вместо них идут
    сами реплики жителей из сохранённых цитат сигнала.
    """

    kind: DangerKind
    label: str
    source: DangerSource
    text: str
    author: str | None = None
    sent_at: datetime | None = None


class SignalDanger(ContractModel):
    kinds: list[DangerKind]
    labels: list[str]
    sources: list[DangerSource]
    evidence: list[DangerEvidenceView] = Field(default_factory=list)
    evidence_unverified: bool = False
    preliminary: bool = False
    #: Опасность отмечена «не у нас / не сейчас»: памятки в чат не было.
    displaced: bool = False
    downgraded: bool = False


class SignalActionDescriptor(ContractModel):
    """Команда оператора. `enabled=false` всегда сопровождается причиной."""

    code: SignalActionCode
    enabled: bool
    reason: str | None = None


class SignalLinked(ContractModel):
    """Заявка или проблема, связанная с сигналом решением оператора."""

    incident_id: UUID
    report_id: UUID | None = None
    title: str
    ticket_id: UUID | None = None
    ticket_number: str | None = None


class SignalRouteSnapshot(ContractModel):
    """Маршрут, как он был показан в момент решения оператора."""

    route_type: RouteType
    organization_name: str | None = None
    channel_label: str | None = None
    basis_text: str | None = None
    basis_source_title: str | None = None
    basis_verified_at: date | None = None
    basis_verification_status: VerificationStatus | None = None
    directory_version: str | None = None


class SignalDecisionView(ContractModel):
    status: SignalStatus
    decided_by: str | None = None
    decided_at: datetime | None = None
    reason: DismissReason | None = None
    reason_label: str | None = None
    note: str | None = None
    route: SignalRouteSnapshot | None = None


class SignalEventView(ContractModel):
    """Безопасное подмножество событий: вид, подпись и время. Без деталей модели."""

    kind: str
    label: str
    at: datetime
    actor: str | None = None


class SignalTicketDraft(ContractModel):
    """Что уйдёт в заявку по умолчанию: категория и описание из цитат."""

    category: ReportCategory
    description: str


class SignalSummary(ContractModel):
    id: UUID
    house_id: UUID
    house_address: str
    subtype: str
    subtype_label: str
    object_label: str
    category: ReportCategory
    strength: SignalStrength
    strength_reason: str
    status: SignalStatus
    report_count: int = Field(ge=0)
    author_count: int = Field(ge=0)
    first_seen_at: datetime
    last_seen_at: datetime
    first_quote: SignalQuoteView | None = None
    place: SignalPlace
    route_type: RouteType
    route_source: RouteSource
    requires_operator_choice: bool = False
    danger_kinds: list[DangerKind] = Field(default_factory=list)
    is_demo: bool = False
    version: int = Field(ge=1)


class SignalView(SignalSummary):
    territory: SignalTerritory
    quotes: list[SignalQuoteView] = Field(default_factory=list)
    danger: SignalDanger | None = None
    action_card: ActionCard
    #: Типы маршрута, которые оператор может выбрать сейчас. Пусто — выбор не нужен.
    route_choices: list[RouteType] = Field(default_factory=list)
    route_chosen_by: str | None = None
    route_chosen_at: datetime | None = None
    join_candidates: list[DuplicateCandidate] = Field(default_factory=list)
    ticket_draft: SignalTicketDraft
    linked: SignalLinked | None = None
    decision: SignalDecisionView | None = None
    allowed_actions: list[SignalActionDescriptor] = Field(default_factory=list)
    events: list[SignalEventView] = Field(default_factory=list)


class SignalAttention(ContractModel):
    """Открытые критические сигналы в выбранной области: для баннера."""

    count: int = Field(ge=0)
    latest_signal_id: UUID | None = None
    latest_at: datetime | None = None


class SignalStrengthCounts(ContractModel):
    critical: int = Field(default=0, ge=0)
    strong: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    weak: int = Field(default=0, ge=0)


class SignalList(ContractModel):
    items: list[SignalSummary]
    page: PageMeta
    #: Счётчики по силе при тех же доме и статусе, без фильтра силы.
    counts: SignalStrengthCounts
    attention: SignalAttention


# ------------------------------------------------------------------ команды


class SignalCommand(ContractModel):
    expected_version: int = Field(ge=1)


def _plain(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if any(ord(char) < 32 and char not in "\n\r\t" for char in cleaned):
        raise ValueError("Plain text required")
    return cleaned or None


class SignalCreateTicket(SignalCommand):
    """Заявка из сигнала. Без полей — категория и описание по умолчанию."""

    category: ReportCategory | None = None
    description: str | None = Field(default=None, min_length=5, max_length=2000)

    @field_validator("description")
    @classmethod
    def plain_description(cls, value: str | None) -> str | None:
        return _plain(value)


class SignalJoin(SignalCommand):
    incident_id: UUID


class SignalRouteExternal(SignalCommand):
    pass


class SignalChooseRoute(SignalCommand):
    route_type: RouteType


class SignalDismiss(SignalCommand):
    reason: DismissReason
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def plain_note(cls, value: str | None) -> str | None:
        return _plain(value)


class SignalMutation(ContractModel):
    signal: SignalView
    replayed: bool = False
    effect_version: int = Field(ge=1)
