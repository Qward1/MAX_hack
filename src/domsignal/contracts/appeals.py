"""DTO черновика обращения (минимальный A-04).

Черновик — это текст, который житель проверяет, правит и отправляет **сам** в
официальном сервисе. Продукт не подаёт обращение и не подтверждает внешнюю
регистрацию: `filed` остаётся отметкой жителя (`user_reported`), а не фактом
приёма официальной системой.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from domsignal.contracts.common import ContractModel
from domsignal.contracts.incidents import ActionDescriptor, Provenance
from domsignal.contracts.routing import RouteChannel


class AppealDraftCreate(ContractModel):
    """Откуда собирать черновик: исход маршрутизации либо созданная заявка."""

    house_id: UUID
    route_outcome_id: UUID | None = None
    report_id: UUID | None = None


class AppealDraftUpdate(ContractModel):
    """Правка текста с версией. Устаревшая версия не затирает чужой ввод."""

    text: str = Field(min_length=1, max_length=20000)
    version: int = Field(ge=1)


class AppealFiledMark(ContractModel):
    """Отметка «я отправил сам». Номер необязателен и не проверяется."""

    reference: str | None = Field(default=None, max_length=200)


class AppealDraftView(ContractModel):
    """Сохранённый черновик вместе с каналом и происхождением текста."""

    id: UUID
    house_id: UUID
    route_outcome_id: UUID
    text: str
    version: int
    created_at: datetime
    updated_at: datetime
    #: Абзац описания пришёл от модели и прошёл guard `no_new_facts`.
    ai_assisted: bool
    organization_name: str | None = None
    channel: RouteChannel | None = None
    filed_at: datetime | None = None
    filed_reference: str | None = None
    provenance: Provenance
    allowed_actions: list[ActionDescriptor] = Field(default_factory=list)
