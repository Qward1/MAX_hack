"""A16 ticket work and resident verification

Revision ID: 20260918_0004
Revises: 20260918_0003
Create Date: 2026-09-18 13:51:31.268056
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_0004"
down_revision: str | None = "20260918_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_incident_scope", "incidents", ["id", "management_id", "house_id"]
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("management_id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("latest_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("resume_status", sa.String(length=30), nullable=False),
        sa.Column("routing_reason", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "resume_status IN ('new','accepted','in_progress')",
            name=op.f("ck_tickets_resume_status"),
        ),
        sa.CheckConstraint(
            "status IN ('new','accepted','in_progress','verification_pending',"
            "'needs_clarification','waiting_external','closed','cancelled')",
            name=op.f("ck_tickets_status"),
        ),
        sa.CheckConstraint(
            "(accepted_by IS NULL AND accepted_at IS NULL) OR "
            "(accepted_by IS NOT NULL AND assignee_id IS NOT NULL AND "
            "accepted_by = assignee_id AND accepted_at IS NOT NULL)",
            name=op.f("ck_tickets_acceptance_owner"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_tickets_version")),
        sa.ForeignKeyConstraint(
            ["accepted_by"], ["users.id"], name=op.f("fk_tickets_accepted_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("fk_tickets_assignee_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_tickets_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["incident_id", "management_id", "house_id"],
            ["incidents.id", "incidents.management_id", "incidents.house_id"],
            name="fk_ticket_incident_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
        sa.UniqueConstraint("number", name=op.f("uq_tickets_number")),
    )
    op.create_index(
        "ix_ticket_queue", "tickets", ["management_id", "status", "assignee_id"], unique=False
    )
    op.create_index(op.f("ix_tickets_incident_id"), "tickets", ["incident_id"], unique=False)
    op.create_index(
        "uq_ticket_active_incident",
        "tickets",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('closed','cancelled')"),
    )
    op.create_table(
        "work_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("reported_by", sa.Uuid(), nullable=False),
        sa.Column("performed_by", sa.Uuid(), nullable=False),
        sa.Column("public_description", sa.Text(), nullable=False),
        sa.Column("rework_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number > 0", name=op.f("ck_work_attempts_number")),
        sa.ForeignKeyConstraint(
            ["performed_by"], ["users.id"], name=op.f("fk_work_attempts_performed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["reported_by"], ["users.id"], name=op.f("fk_work_attempts_reported_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_work_attempts_ticket_id_tickets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_attempts")),
        sa.UniqueConstraint("ticket_id", "id", name="uq_attempt_ticket_id"),
        sa.UniqueConstraint("ticket_id", "number", name="uq_attempt_number"),
    )
    op.create_index(
        op.f("ix_work_attempts_ticket_id"), "work_attempts", ["ticket_id"], unique=False
    )
    op.create_table(
        "result_observations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("corrects_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "outcome IN ('resolved','unresolved')", name=op.f("ck_result_observations_outcome")
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_result_observations_revision")),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_result_observations_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "actor_id", "corrects_id"],
            [
                "result_observations.attempt_id",
                "result_observations.actor_id",
                "result_observations.id",
            ],
            name="fk_observation_correction",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["work_attempts.id"],
            name=op.f("fk_result_observations_attempt_id_work_attempts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_result_observations")),
        sa.UniqueConstraint("attempt_id", "actor_id", "id", name="uq_observation_actor_id"),
        sa.UniqueConstraint("attempt_id", "revision", name="uq_observation_revision"),
    )
    op.create_index(
        op.f("ix_result_observations_attempt_id"),
        "result_observations",
        ["attempt_id"],
        unique=False,
    )
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("observation_id", sa.Uuid(), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "visibility IN ('internal','resident')", name=op.f("ck_ticket_events_visibility")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_ticket_events_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name=op.f("fk_ticket_events_assignee_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["result_observations.id"],
            name=op.f("fk_ticket_events_observation_id_result_observations"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id", "attempt_id"],
            ["work_attempts.ticket_id", "work_attempts.id"],
            name="fk_event_attempt",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_events_ticket_id_tickets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
        sa.UniqueConstraint("ticket_id", "id", name="uq_ticket_event_id"),
        sa.UniqueConstraint("ticket_id", "version", name="uq_ticket_event_version"),
    )
    op.create_index(
        op.f("ix_ticket_events_ticket_id"), "ticket_events", ["ticket_id"], unique=False
    )
    op.create_table(
        "ticket_deadlines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("basis", sa.String(length=20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("start_event_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rule_source", sa.String(length=500), nullable=True),
        sa.Column("rule_version", sa.String(length=100), nullable=True),
        sa.Column("agreement_reference", sa.String(length=500), nullable=True),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "basis <> 'agreed' OR (agreement_reference IS NOT NULL AND agreed_at IS NOT NULL)",
            name=op.f("ck_ticket_deadlines_agreement_source"),
        ),
        sa.CheckConstraint(
            "basis <> 'normative' OR (rule_source IS NOT NULL AND rule_version IS NOT NULL)",
            name=op.f("ck_ticket_deadlines_normative_source"),
        ),
        sa.CheckConstraint(
            "basis IN ('internal','agreed','normative')", name=op.f("ck_ticket_deadlines_basis")
        ),
        sa.CheckConstraint(
            "kind IN ('response','completion','next_update')", name=op.f("ck_ticket_deadlines_kind")
        ),
        sa.CheckConstraint(
            "due_at IS NULL OR due_at >= started_at",
            name=op.f("ck_ticket_deadlines_due_after_start"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name=op.f("fk_ticket_deadlines_recorded_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id", "event_id"],
            ["ticket_events.ticket_id", "ticket_events.id"],
            name="fk_deadline_event",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id", "start_event_id"],
            ["ticket_events.ticket_id", "ticket_events.id"],
            name="fk_deadline_start_event",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_deadlines_ticket_id_tickets")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_deadlines")),
        sa.UniqueConstraint("ticket_id", "kind", "basis", "revision", name="uq_deadline_revision"),
    )
    op.create_index(
        op.f("ix_ticket_deadlines_ticket_id"), "ticket_deadlines", ["ticket_id"], unique=False
    )
    op.add_column(
        "house_managements",
        sa.Column("ticket_intake_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("outbox_messages", sa.Column("dedupe_key", sa.String(length=100), nullable=True))
    op.create_unique_constraint(
        op.f("uq_outbox_messages_dedupe_key"), "outbox_messages", ["dedupe_key"]
    )
    op.create_foreign_key(
        "fk_ticket_latest_attempt",
        "tickets",
        "work_attempts",
        ["id", "latest_attempt_id"],
        ["ticket_id", "id"],
    )
    op.execute("""
        CREATE FUNCTION protect_ticket_history() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Ticket history cannot be deleted' USING ERRCODE='23514';
            END IF;
            IF TG_TABLE_NAME = 'tickets' THEN
                IF (NEW.id, NEW.number, NEW.incident_id, NEW.management_id, NEW.house_id,
                    NEW.created_by, NEW.created_at, NEW.source) IS DISTINCT FROM
                   (OLD.id, OLD.number, OLD.incident_id, OLD.management_id, OLD.house_id,
                    OLD.created_by, OLD.created_at, OLD.source) THEN
                    RAISE EXCEPTION 'Ticket identity is immutable' USING ERRCODE='23514';
                END IF;
            ELSIF TG_TABLE_NAME = 'work_attempts' THEN
                IF (to_jsonb(NEW) - 'rework_required') IS DISTINCT FROM
                   (to_jsonb(OLD) - 'rework_required') OR
                   (OLD.rework_required AND NOT NEW.rework_required) THEN
                    RAISE EXCEPTION 'Attempt history is immutable' USING ERRCODE='23514';
                END IF;
            ELSE
                RAISE EXCEPTION 'Ticket history is append-only' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END; $$ LANGUAGE plpgsql;
    """)
    for table in (
        "tickets",
        "work_attempts",
        "result_observations",
        "ticket_events",
        "ticket_deadlines",
    ):
        op.execute(
            f"CREATE TRIGGER ticket_history BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_ticket_history()"
        )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM tickets) OR
               EXISTS (SELECT 1 FROM outbox_messages WHERE kind='ticket.notification_intent.v1') OR
               EXISTS (SELECT 1 FROM house_managements WHERE ticket_intake_enabled) THEN
                RAISE EXCEPTION 'A-16 contains history/config; restore a pre-A16 backup';
            END IF;
        END $$;
    """)
    for table in (
        "tickets",
        "work_attempts",
        "result_observations",
        "ticket_events",
        "ticket_deadlines",
    ):
        op.execute(f"DROP TRIGGER ticket_history ON {table}")
    op.execute("DROP FUNCTION protect_ticket_history()")
    op.drop_constraint("fk_ticket_latest_attempt", "tickets", type_="foreignkey")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(op.f("uq_outbox_messages_dedupe_key"), "outbox_messages", type_="unique")
    op.drop_column("outbox_messages", "dedupe_key")
    op.drop_column("house_managements", "ticket_intake_enabled")
    op.drop_index(op.f("ix_ticket_deadlines_ticket_id"), table_name="ticket_deadlines")
    op.drop_table("ticket_deadlines")
    op.drop_index(op.f("ix_ticket_events_ticket_id"), table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index(op.f("ix_result_observations_attempt_id"), table_name="result_observations")
    op.drop_table("result_observations")
    op.drop_index(op.f("ix_work_attempts_ticket_id"), table_name="work_attempts")
    op.drop_table("work_attempts")
    op.drop_index(
        "uq_ticket_active_incident",
        table_name="tickets",
        postgresql_where=sa.text("status NOT IN ('closed','cancelled')"),
    )
    op.drop_index(op.f("ix_tickets_incident_id"), table_name="tickets")
    op.drop_index("ix_ticket_queue", table_name="tickets")
    op.drop_table("tickets")
    op.drop_constraint("uq_incident_scope", "incidents", type_="unique")
    # ### end Alembic commands ###
