"""Квота подключения чатов УК (CHAT-QUOTA-2026-09-26)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel

GrantKind = Literal["initial", "expansion", "adjustment", "migration"]
QuotaRequestStatus = Literal["pending", "approved", "partially_approved", "rejected", "cancelled"]


class ChatQuotaView(ContractModel):
    """Слоты УК: единица — активная привязка бота к домовому чату этой УК."""

    #: Выданная квота; `null` — без ограничения.
    limit: int | None
    #: Активные привязки чатов домов УК.
    used: int
    #: Сколько новых чатов ещё можно подключить; `null` — без ограничения.
    remaining: int | None
    #: Квоту снизили ниже числа подключённых чатов: чаты работают, новые — нет.
    over_limit: bool
    #: Новые подключения заблокированы: слотов нет.
    exhausted: bool


class ChatQuotaGrantView(ContractModel):
    kind: GrantKind
    limit_after: int | None
    delta: int | None
    reason: str
    created_at: datetime


class ChatQuotaRequestView(ContractModel):
    id: UUID
    company_id: UUID
    company_name: str | None = None
    requested_delta: int
    reason: str
    status: QuotaRequestStatus
    granted_delta: int | None
    decision_reason: str | None
    created_at: datetime
    decided_at: datetime | None
    #: Текущая квота УК — контекст решения для платформы.
    quota: ChatQuotaView | None = None


class CompanyQuotaView(ContractModel):
    quota: ChatQuotaView
    grants: list[ChatQuotaGrantView]
    requests: list[ChatQuotaRequestView]


class ChatQuotaRequestCreate(ContractModel):
    requested_delta: int = Field(ge=1, le=1000)
    reason: str = Field(min_length=3, max_length=2000, pattern=r"^[^<>]+$")


class ChatQuotaDecision(ContractModel):
    """Решение по запросу: 0 — отклонить, меньше запрошенного — частично."""

    granted_delta: int = Field(ge=0, le=1000)
    reason: str = Field(min_length=3, max_length=2000, pattern=r"^[^<>]+$")


class ChatQuotaSet(ContractModel):
    """Суперадмин задаёт квоту; `null` — без ограничения."""

    limit: int | None = Field(ge=0, le=10000)
    reason: str = Field(min_length=3, max_length=2000, pattern=r"^[^<>]+$")
