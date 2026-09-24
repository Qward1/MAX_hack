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


class OpenHouse(ContractModel):
    """Дом с открытым доступом: его может выбрать любой вошедший через MAX."""

    id: UUID
    name: str
    address: str
    joined: bool


class OpenHouseList(ContractModel):
    items: list[OpenHouse]


class MeResponse(ContractModel):
    id: UUID
    display_name: str
    houses: list[HouseAccess]
    capabilities: CapabilityFlags


class TestSessionRequest(ContractModel):
    actor: Literal[
        "demo",
        "demo-neighbour",
        "demo-third",
        "outsider",
        "a16-admin",
        "a16-responsible",
        "a16-operator",
        "a16-revoked",
        "a16-resident",
        "a16-neighbor",
        "a16-outsider",
        "a16-beta-admin",
        # Синтетический оператор и админ очереди сигналов браузерного стенда P5.
        "p5-operator",
        "p5-admin",
        # Житель без дома браузерного стенда D1 (создаёт `tests/browser/d1_fixture.py`).
        "d1-guest",
    ] = "demo"


class MaxSessionRequest(ContractModel):
    init_data: str = Field(min_length=1, max_length=8192)


class SessionResponse(ContractModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
