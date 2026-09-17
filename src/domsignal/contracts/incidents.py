from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel, PageMeta
from domsignal.core.incidents import ClassificationMode, IncidentStatus, ReportCategory


class ReportCreate(ContractModel):
    house_id: UUID
    category: ReportCategory
    description: str = Field(min_length=5, max_length=2000)
    classification_mode: ClassificationMode = ClassificationMode.MANUAL


class ReportSummary(ContractModel):
    id: UUID
    description: str
    created_at: datetime


class IncidentSummary(ContractModel):
    id: UUID
    house_id: UUID
    category: ReportCategory
    title: str
    description: str
    status: IncidentStatus
    created_at: datetime
    report_count: int = 1
    allowed_actions: list[Literal["view"]] = ["view"]


class RuleProvenance(ContractModel):
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


class IncidentList(ContractModel):
    items: list[IncidentSummary]
    page: PageMeta
