from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

SCOPE_CHECK = (
    "(scope_type = 'house' AND scope_value IS NULL) OR "
    "(scope_type = 'entrance' AND scope_value IS NOT NULL AND length(trim(scope_value)) > 0)"
)


class MAXChat(Timestamps, Base):
    __tablename__ = "max_chats"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    max_chat_id: Mapped[str] = mapped_column(String(200), unique=True)
    type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str | None] = mapped_column(String(500))
    is_channel: Mapped[bool | None] = mapped_column(Boolean)
    owner_max_user_id: Mapped[str | None] = mapped_column(String(200))
    bot_present: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lifecycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Monotonic across *all* bindings of the same external chat.
    binding_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ConnectionRequest(Base):
    __tablename__ = "chat_connection_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["management_id", "house_id"],
            ["house_managements.id", "house_managements.house_id"],
            name="fk_connection_management_house",
            ondelete="RESTRICT",
        ),
        CheckConstraint(SCOPE_CHECK, name="scope"),
        CheckConstraint(
            "status IN ('created','connector_claimed','chat_detected','max_verified',"
            "'awaiting_approval','completed','expired','cancelled','rejected')",
            name="status",
        ),
        Index("ix_connection_connector_status", "connector_max_user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    management_id: Mapped[uuid.UUID] = mapped_column(index=True)
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="RESTRICT"))
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    connector_max_user_id: Mapped[str | None] = mapped_column(String(200))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="created", server_default="created")
    candidate_max_chat_id: Mapped[str | None] = mapped_column(ForeignKey("max_chats.max_chat_id"))
    scope_type: Mapped[str] = mapped_column(String(30))
    scope_value: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))


class ChatBinding(Timestamps, Base):
    __tablename__ = "chat_bindings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["management_id", "house_id"],
            ["house_managements.id", "house_managements.house_id"],
            name="fk_binding_management_house",
            ondelete="RESTRICT",
        ),
        CheckConstraint(SCOPE_CHECK, name="scope"),
        CheckConstraint("status IN ('pending','active','suspended','revoked')", name="status"),
        CheckConstraint("binding_version > 0", name="version"),
        UniqueConstraint("max_chat_id", "binding_version", name="uq_chat_binding_version"),
        Index(
            "uq_chat_binding_active",
            "max_chat_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    max_chat_id: Mapped[str] = mapped_column(ForeignKey("max_chats.max_chat_id"), index=True)
    connection_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_connection_requests.id"),
        unique=True,
    )
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="RESTRICT"))
    management_id: Mapped[uuid.UUID] = mapped_column(index=True)
    scope_type: Mapped[str] = mapped_column(String(30))
    scope_value: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), default="pending", server_default="pending")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    binding_version: Mapped[int] = mapped_column(Integer)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(100))
