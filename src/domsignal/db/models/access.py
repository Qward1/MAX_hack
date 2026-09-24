from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "platform_role IS NULL OR platform_role = 'superadmin'", name="platform_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(200))
    demo_alias: Mapped[str | None] = mapped_column(String(50), unique=True)
    max_user_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    max_identity_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_role: Mapped[str | None] = mapped_column(String(30))
    # Диалог с ботом по подписанному вебхуку MAX (D1): когда человек начал
    # диалог или написал боту и когда остановил бота. Бот не может написать
    # первым тому, кто диалог не начинал.
    max_dialog_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_dialog_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Последний ответ бота в домовом чате на `/report` этого автора (не чаще
    # раза в 10 минут).
    group_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def dialog_open(self) -> bool:
        """Начат ли диалог с ботом и не остановлен ли он после этого."""
        return self.max_dialog_at is not None and (
            self.max_dialog_stopped_at is None or self.max_dialog_stopped_at < self.max_dialog_at
        )


class House(Base):
    __tablename__ = "houses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Открытый доступ (OPEN-HOUSE-ACCESS-2026-09-25): любой вошедший через MAX
    # может выбрать дом и действовать как житель, пока переключатель включён.
    # Только серверное значение по умолчанию: вставки прежних ревизий (проверки
    # миграций) не должны знать о столбце.
    open_resident_access: Mapped[bool] = mapped_column(Boolean, server_default="false")
    open_access_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    open_access_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


#: Основание членства: участник домового чата (RESIDENT-BY-CHAT-2026-09-25).
CHAT_MEMBER_SOURCE = "chat_member"
#: Основание членства: открытый доступ к дому (OPEN-HOUSE-ACCESS-2026-09-25).
OPEN_ACCESS_SOURCE = "open_access"
#: Источники, у которых действующая запись одна, а завершённые — история.
EVENT_SOURCES = (CHAT_MEMBER_SOURCE, OPEN_ACCESS_SOURCE)
END_REASONS = ("user_removed", "not_member", "open_access_closed")


class ResidentMembership(Base):
    """Product access basis, never evidence of ownership or verified residence.

    Legacy role/evidence are retained losslessly for migration rollback only.
    They are not consulted by access policy.

    `chat_member` — текущее участие в домовом чате с действующей привязкой:
    основание — привязка и её версия, срок — проверка + 24 ч. `open_access` —
    выбор открытого дома; живёт, пока переключатель дома включён. У этих
    источников действующая запись одна, завершённые остаются историей.
    """

    __tablename__ = "resident_memberships"
    __table_args__ = (
        Index(
            "uq_resident_user_house",
            "user_id",
            "house_id",
            unique=True,
            postgresql_where=text("source NOT IN ('chat_member', 'open_access')"),
        ),
        Index(
            "uq_resident_chat_member_active",
            "user_id",
            "chat_binding_id",
            unique=True,
            postgresql_where=text("source = 'chat_member' AND status = 'active'"),
        ),
        Index(
            "uq_resident_open_access_active",
            "user_id",
            "house_id",
            unique=True,
            postgresql_where=text("source = 'open_access' AND status = 'active'"),
        ),
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="status"),
        CheckConstraint(
            "(source = 'chat_member') = (chat_binding_id IS NOT NULL) AND "
            "(source <> 'chat_member' OR (binding_version IS NOT NULL "
            "AND checked_at IS NOT NULL AND expires_at IS NOT NULL))",
            name="chat_basis",
        ),
        CheckConstraint(
            "end_reason IS NULL OR end_reason IN "
            "('user_removed','not_member','open_access_closed')",
            name="end_reason",
        ),
        CheckConstraint(
            "source NOT IN ('chat_member', 'open_access') "
            "OR (status = 'active') = (ended_at IS NULL)",
            name="ended",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), index=True
    )
    legacy_role: Mapped[str] = mapped_column(
        String(30), default="resident", server_default="resident"
    )
    evidence_source: Mapped[str] = mapped_column(
        String(100), default="manual", server_default="manual"
    )
    source: Mapped[str] = mapped_column(String(100), default="manual", server_default="manual")
    verification_level: Mapped[str] = mapped_column(
        String(50), default="unverified", server_default="unverified"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    chat_binding_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_bindings.id", ondelete="RESTRICT"), index=True
    )
    binding_version: Mapped[int | None] = mapped_column(Integer)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMemberCheck(Base):
    """Последний вызов MAX API «участник ли человек этого чата».

    Не чаще одного вызова на пару «пользователь, чат» за 15 минут. `error` —
    вызов не удался: прежний результат действует до своего срока, нового
    доступа не выдаётся.
    """

    __tablename__ = "chat_member_checks"
    __table_args__ = (
        CheckConstraint("outcome IN ('member','not_member','error')", name="outcome"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    max_chat_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(20))


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ManagementCompany(Timestamps, Base):
    __tablename__ = "management_companies"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'archived')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    legal_name: Mapped[str | None] = mapped_column(String(300))
    inn: Mapped[str | None] = mapped_column(String(12), unique=True)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    # Открытая регистрация сотрудников по публичной ссылке `/join/<код>` (D2).
    # Включает и закрывает суперадмин; в базе только хэш кода ссылки.
    open_registration_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    open_registration_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    open_registration_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    open_registration_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class HouseManagement(Timestamps, Base):
    __tablename__ = "house_managements"
    __table_args__ = (
        UniqueConstraint("id", "house_id", name="uq_management_id_house"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="period"),
        CheckConstraint("status IN ('active', 'suspended', 'ended')", name="status"),
        ExcludeConstraint(
            ("house_id", "="),
            (text("tstzrange(valid_from, valid_to, '[)')"), "&&"),
            where=text("status = 'active'"),
            name="ex_management_active_period",
        ),
        Index(
            "ix_management_current",
            "house_id",
            "valid_from",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="RESTRICT"), index=True
    )
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="RESTRICT"), index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
    basis_type: Mapped[str | None] = mapped_column(String(100))
    basis_reference: Mapped[str | None] = mapped_column(String(500))
    ticket_intake_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class OrganizationMembership(Timestamps, Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_organization_user_tenant"),
        CheckConstraint("role IN ('company_admin', 'operator')", name="role"),
        CheckConstraint("status IN ('active', 'revoked')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")


class HouseAssignment(Timestamps, Base):
    __tablename__ = "house_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "management_id", name="uq_assignment_user_management"),
        CheckConstraint("role IN ('responsible', 'operator')", name="role"),
        CheckConstraint("status IN ('active', 'revoked')", name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    management_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("house_managements.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default="active", server_default="active")
