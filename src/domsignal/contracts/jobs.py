from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel
from domsignal.core.incidents import ReportCategory


class NormalizedInboundEvent(ContractModel):
    event_id: str = Field(min_length=1, max_length=200)
    event_type: Literal["diagnostic.report"]
    external_user_id: str = Field(min_length=1, max_length=200)
    house_id: UUID
    category: ReportCategory
    description: str = Field(min_length=5, max_length=2000)
    occurred_at: datetime


class InboundAccepted(ContractModel):
    event_id: str
    accepted: bool
    duplicate: bool
    job_id: UUID | None


class DiagnosticJobRequest(ContractModel):
    destination: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=1000)


class JobAccepted(ContractModel):
    job_id: UUID
    status: Literal["pending"] = "pending"
