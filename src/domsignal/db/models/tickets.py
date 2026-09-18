from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["incident_id", "management_id", "house_id"],
            ["incidents.id", "incidents.management_id", "incidents.house_id"],
            name="fk_ticket_incident_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "latest_attempt_id"],
            ["work_attempts.ticket_id", "work_attempts.id"],
            name="fk_ticket_latest_attempt",
            use_alter=True,
        ),
        CheckConstraint(
            "status IN ('new','accepted','in_progress','verification_pending',"
            "'needs_clarification','waiting_external','closed','cancelled')",
            name="status",
        ),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("resume_status IN ('new','accepted','in_progress')", name="resume_status"),
        CheckConstraint(
            "(accepted_by IS NULL AND accepted_at IS NULL) OR "
            "(accepted_by IS NOT NULL AND assignee_id IS NOT NULL AND "
            "accepted_by = assignee_id AND accepted_at IS NOT NULL)",
            name="acceptance_owner",
        ),
        Index("ix_ticket_queue", "management_id", "status", "assignee_id"),
        Index(
            "uq_ticket_active_incident",
            "incident_id",
            unique=True,
            postgresql_where=text("status NOT IN ('closed','cancelled')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    number: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(index=True)
    management_id: Mapped[uuid.UUID]
    house_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(30), default="new")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    latest_attempt_id: Mapped[uuid.UUID | None]
    resume_status: Mapped[str] = mapped_column(String(30), default="new")
    routing_reason: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(30))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkAttempt(Base):
    __tablename__ = "work_attempts"
    __table_args__ = (
        UniqueConstraint("ticket_id", "id", name="uq_attempt_ticket_id"),
        UniqueConstraint("ticket_id", "number", name="uq_attempt_number"),
        CheckConstraint("number > 0", name="number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    number: Mapped[int]
    reported_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    performed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    public_description: Mapped[str] = mapped_column(Text)
    rework_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResultObservation(Base):
    __tablename__ = "result_observations"
    __table_args__ = (
        UniqueConstraint("attempt_id", "revision", name="uq_observation_revision"),
        UniqueConstraint("attempt_id", "actor_id", "id", name="uq_observation_actor_id"),
        ForeignKeyConstraint(
            ["attempt_id", "actor_id", "corrects_id"],
            [
                "result_observations.attempt_id",
                "result_observations.actor_id",
                "result_observations.id",
            ],
            name="fk_observation_correction",
        ),
        CheckConstraint("outcome IN ('resolved','unresolved')", name="outcome"),
        CheckConstraint("revision > 0", name="revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_attempts.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    outcome: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int]
    corrects_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketEvent(Base):
    __tablename__ = "ticket_events"
    __table_args__ = (
        UniqueConstraint("ticket_id", "version", name="uq_ticket_event_version"),
        UniqueConstraint("ticket_id", "id", name="uq_ticket_event_id"),
        ForeignKeyConstraint(
            ["ticket_id", "attempt_id"],
            ["work_attempts.ticket_id", "work_attempts.id"],
            name="fk_event_attempt",
        ),
        CheckConstraint("visibility IN ('internal','resident')", name="visibility"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    version: Mapped[int]
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str | None] = mapped_column(Text)
    attempt_id: Mapped[uuid.UUID | None]
    observation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("result_observations.id"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    visibility: Mapped[str] = mapped_column(String(20), default="internal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TicketDeadline(Base):
    """Append-only facts. Different kind/basis clocks never overwrite each other."""

    __tablename__ = "ticket_deadlines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ticket_id", "start_event_id"],
            ["ticket_events.ticket_id", "ticket_events.id"],
            name="fk_deadline_start_event",
        ),
        ForeignKeyConstraint(
            ["ticket_id", "event_id"],
            ["ticket_events.ticket_id", "ticket_events.id"],
            name="fk_deadline_event",
        ),
        UniqueConstraint("ticket_id", "kind", "basis", "revision", name="uq_deadline_revision"),
        CheckConstraint("kind IN ('response','completion','next_update')", name="kind"),
        CheckConstraint("basis IN ('internal','agreed','normative')", name="basis"),
        CheckConstraint(
            "basis <> 'agreed' OR (agreement_reference IS NOT NULL AND agreed_at IS NOT NULL)",
            name="agreement_source",
        ),
        CheckConstraint(
            "basis <> 'normative' OR (rule_source IS NOT NULL AND rule_version IS NOT NULL)",
            name="normative_source",
        ),
        CheckConstraint("due_at IS NULL OR due_at >= started_at", name="due_after_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tickets.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    basis: Mapped[str] = mapped_column(String(20))
    revision: Mapped[int]
    start_event_id: Mapped[uuid.UUID]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rule_source: Mapped[str | None] = mapped_column(String(500))
    rule_version: Mapped[str | None] = mapped_column(String(100))
    agreement_reference: Mapped[str | None] = mapped_column(String(500))
    agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    event_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
