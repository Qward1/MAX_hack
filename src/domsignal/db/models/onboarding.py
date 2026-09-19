"""Administrative requests are proposals, never access grants."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

REVIEW_STATUSES = "'submitted','under_review','needs_info','approved','rejected','cancelled'"


class ReviewFields(Timestamps):
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))


class CompanyOnboardingRequest(ReviewFields, Base):
    __tablename__ = "company_onboarding_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({REVIEW_STATUSES})", name="status"),
        Index(
            "uq_company_application_open_inn",
            "inn",
            unique=True,
            postgresql_where=text("status IN ('submitted','under_review','needs_info')"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    legal_name: Mapped[str] = mapped_column(String(300))
    short_name: Mapped[str] = mapped_column(String(200))
    inn: Mapped[str] = mapped_column(String(12))
    contact_name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(String(2000))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("management_companies.id"), unique=True
    )


class EmployeeInvitation(Timestamps, Base):
    __tablename__ = "employee_invitations"
    __table_args__ = (
        CheckConstraint("organization_role IN ('operator','company_admin')", name="role"),
        CheckConstraint(
            "status IN ('pending','claimed','accepted','expired','revoked')", name="status"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("management_companies.id"), index=True)
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    organization_role: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HouseManagementRequest(ReviewFields, Base):
    __tablename__ = "house_management_requests"
    __table_args__ = (CheckConstraint(f"status IN ({REVIEW_STATUSES})", name="status"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("management_companies.id"), index=True)
    requested_address: Mapped[str] = mapped_column(String(500))
    normalized_address: Mapped[str] = mapped_column(String(500), index=True)
    requested_valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    basis_text: Mapped[str] = mapped_column(String(2000))
    candidate_house_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("houses.id"))
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    management_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("house_managements.id"), unique=True
    )
