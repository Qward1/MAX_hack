from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Problem(ContractModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str
    errors: list[dict[str, Any]] | None = None


class MessageResponse(ContractModel):
    message: str


class PageMeta(ContractModel):
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)
