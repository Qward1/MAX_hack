from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.contracts.common import ContractModel


class HouseAccess(ContractModel):
    id: UUID
    name: str
    address: str
    role: Literal["resident", "admin", "operator", "responsible"]
    is_demo: bool


class MeResponse(ContractModel):
    id: UUID
    display_name: str
    houses: list[HouseAccess]
    capabilities: CapabilityFlags


class TestSessionRequest(ContractModel):
    actor: Literal[
        "demo",
        "outsider",
        "a16-admin",
        "a16-responsible",
        "a16-operator",
        "a16-revoked",
        "a16-resident",
        "a16-neighbor",
        "a16-outsider",
        "a16-beta-admin",
    ] = "demo"


class MaxSessionRequest(ContractModel):
    init_data: str = Field(min_length=1, max_length=8192)


class SessionResponse(ContractModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
