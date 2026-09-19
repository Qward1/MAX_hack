from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class House(Base):
    __tablename__ = "houses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(500), unique=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ResidentMembership(Base):
    """Product access basis, never evidence of ownership or verified residence.

    Legacy role/evidence are retained losslessly for migration rollback only.
    They are not consulted by access policy.
    """

    __tablename__ = "resident_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "house_id", name="uq_resident_user_house"),
        CheckConstraint("status IN ('active', 'revoked', 'expired')", name="status"),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
