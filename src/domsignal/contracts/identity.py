from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel


class HouseAccess(ContractModel):
    id: UUID
    name: str
    address: str
    role: Literal["resident", "admin"]
    is_demo: bool


class MeResponse(ContractModel):
    id: UUID
    display_name: str
    houses: list[HouseAccess]


class TestSessionRequest(ContractModel):
    actor: Literal["demo", "outsider"] = "demo"


class MaxSessionRequest(ContractModel):
    init_data: str = Field(min_length=1, max_length=8192)


class SessionResponse(ContractModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
