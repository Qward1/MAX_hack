"""Identity only: no tenant, role or house authority belongs in these records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps


class EmployeeCredential(Timestamps, Base):
    __tablename__ = "employee_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    login_name: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    password_change_required: Mapped[bool] = mapped_column(Boolean, default=True)
    temporary_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    temporary_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    encrypted_totp_secret: Mapped[str | None] = mapped_column(String(500))
    last_totp_step: Mapped[int | None] = mapped_column(Integer)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthChallenge(Base):
    __tablename__ = "auth_challenges"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employee_credentials.id"), index=True
    )
    stage: Mapped[str] = mapped_column(String(30))
    encrypted_totp_secret: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryCode(Base):
    __tablename__ = "employee_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employee_credentials.id"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthRateLimit(Base):
    """Fixed hash slots bound storage even for arbitrary nonexistent usernames/IPs."""

    __tablename__ = "auth_rate_limits"

    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    window_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
