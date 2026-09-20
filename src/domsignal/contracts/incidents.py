from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel, PageMeta
from domsignal.contracts.routing import ActionCard, DangerKind, LocationScope
from domsignal.core.incidents import ClassificationMode, IncidentStatus, ReportCategory

#: Чем получен разбор: моделью, правилами или ничем (человек уточняет сам).
AnalysisMode = Literal["model", "rules", "manual"]


class ReportCreate(ContractModel):
    house_id: UUID
    category: ReportCategory
    description: str = Field(min_length=5, max_length=2000)
    classification_mode: ClassificationMode = ClassificationMode.MANUAL


class ReportPreviewRequest(ContractModel):
    """Предпросмотр маршрута для формы mini app. Ничего не создаёт."""

    description: str = Field(min_length=5, max_length=2000)


class ReportAnalysisView(ContractModel):
    """Что удалось понять из описания. Только правила, без обращения к модели.

    Место и «с какого времени» отдаются лишь тогда, когда у значения есть
    дословная цитата из текста жителя: угадывать продукт не станет.
    """

    subtype: str | None
    category: ReportCategory
    location_scope: LocationScope
    entrance: str | None
    floor: str | None
    since: str | None
    danger_kinds: list[DangerKind]
    mode: AnalysisMode
    confident: bool
    reason: str


class ReportPreview(ContractModel):
    """Разбор и карточка следующего шага без побочных эффектов."""

    analysis: ReportAnalysisView
    action_card: ActionCard


class ReportSummary(ContractModel):
    id: UUID
    description: str
    created_at: datetime


class ActionDescriptor(ContractModel):
    code: Literal[
        "prepare_appeal",
        "edit_draft",
        "join",
        "copy_draft",
        "open_official_channel",
        "mark_filed",
        "mark_resolved",
        "mark_unresolved",
        "escalate",
        "report_not_problem",
        "retry",
    ]
    enabled: bool
    reason: str | None


class Provenance(ContractModel):
    origin: Literal["official", "product_derived", "user_reported", "demo"] | None
    source_title: str | None = None
    source_url: str | None = None
    verified_at: datetime | None = None
    recorded_at: datetime | None = None
    note: str | None = None


class IncidentLocation(ContractModel):
    """Место и время наблюдения. Заполняется только значениями с цитатой."""

    entrance: str | None = None
    floor: str | None = None
    label: str | None = None
    observed_since: str | None = None


class IncidentSummary(ContractModel):
    id: UUID
    house_id: UUID
    category: ReportCategory
    title: str
    description: str
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime | None
    due_at: datetime | None
    location: IncidentLocation | None
    report_count: int = Field(ge=0)
    participant_count: int | None = Field(ge=0)
    is_demo: bool
    provenance: Provenance | None
    allowed_actions: list[ActionDescriptor] = Field(default_factory=list)


class RuleProvenance(ContractModel):
    origin: Literal["official", "product_derived", "user_reported", "demo"] | None
    verified_at: datetime | None = None
    verification_status: Literal["verified", "needs_verification", "demo"]
    source_url: str
    source_title: str
    due_at: datetime | None = None
    note: str


class IncidentDetail(IncidentSummary):
    reports: list[ReportSummary]
    rule: RuleProvenance


class ReportCreated(ContractModel):
    report_id: UUID
    incident: IncidentDetail
    #: Та же детерминированная карточка следующего шага, что и в предпросмотре.
    action_card: ActionCard | None = None


class IncidentList(ContractModel):
    items: list[IncidentSummary]
    page: PageMeta
