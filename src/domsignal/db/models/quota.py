"""Квота подключения чатов УК (CHAT-QUOTA-2026-09-26).

Единица — активная привязка бота к домовому чату этой УК. История выдач —
отдельная таблица; текущая квота — `limit_after` последней записи (`NULL` —
без ограничения). У УК без единой записи квоты нет ограничения: так ведут
себя организации, созданные до D2, а миграция пишет им явную запись.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

GRANT_KINDS = "'initial','expansion','adjustment','migration'"
REQUEST_STATUSES = "'pending','approved','partially_approved','rejected','cancelled'"


class ChatQuotaRequest(Timestamps, Base):
    """Запрос администратора УК на расширение квоты: +N и обоснование."""

    __tablename__ = "chat_quota_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({REQUEST_STATUSES})", name="status"),
        CheckConstraint("requested_delta BETWEEN 1 AND 1000", name="requested_delta"),
        CheckConstraint(
            "granted_delta IS NULL OR (granted_delta >= 0 AND granted_delta <= requested_delta)",
            name="granted_delta",
        ),
        # Один запрос на рассмотрении на УК.
        Index(
            "uq_chat_quota_request_pending",
            "company_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="RESTRICT"), index=True
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    requested_delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    granted_delta: Mapped[int | None] = mapped_column(Integer)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))


class ChatQuotaGrant(Base):
    """Одна выдача или изменение квоты: кто, почему, когда и что стало."""

    __tablename__ = "chat_quota_grants"
    __table_args__ = (
        CheckConstraint(f"kind IN ({GRANT_KINDS})", name="kind"),
        CheckConstraint("limit_after IS NULL OR limit_after >= 0", name="limit_after"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: Порядок записей внутри УК; время записи может совпадать.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30))
    #: Квота после этой записи; `NULL` — без ограничения.
    limit_after: Mapped[int | None] = mapped_column(Integer)
    #: Изменение относительно прежней квоты, если обе конечны.
    delta: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(2000))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("company_onboarding_requests.id")
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_quota_requests.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
