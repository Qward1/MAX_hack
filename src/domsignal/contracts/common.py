from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class FieldError(ContractModel):
    field: str
    code: str
    message: str


class Problem(ContractModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    retryable: bool
    trace_id: str
    field_errors: list[FieldError] | None = None


class MessageResponse(ContractModel):
    message: str


class PageMeta(ContractModel):
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
