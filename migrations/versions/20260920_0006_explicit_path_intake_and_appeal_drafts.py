"""explicit path intake, route outcomes, appeal drafts and the AI call budget

Аддитивная миграция явного пути. Существующие данные и путь B-02 не меняются:
все новые столбцы допускают NULL, `notification_deliveries.ticket_id` только
ослабляется до NULL, а новое назначение доставки добавляется в существующий
CHECK, не заменяя старые значения.

Revision ID: 20260920_0006
Revises: 20260920_0005
Create Date: 2026-09-20 21:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_0006"
down_revision: str | None = "20260920_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PURPOSE = "purpose IN ('ticket_accepted','work_verification')"
_NEW_PURPOSE = "purpose IN ('ticket_accepted','work_verification','route_action_card')"


def upgrade() -> None:
    op.create_table(
        "ai_call_budget",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("scope_key", sa.String(length=200), nullable=False),
        sa.Column("calls", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("day", "scope_key", name=op.f("pk_ai_call_budget")),
    )
    op.create_table(
        "explicit_intakes",
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("chat_id", sa.String(length=200), nullable=False),
        sa.Column("chat_binding_id", sa.Uuid(), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("external_user_id", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clean_description", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=100), nullable=True),
        sa.Column("result_kind", sa.String(length=30), nullable=True),
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
            "(state = 'pending') = (claimed_at IS NULL)",
            name=op.f("ck_explicit_intakes_claimed_at"),
        ),
        sa.CheckConstraint(
            "result_kind IS NULL OR result_kind IN "
            "('ticket', 'external_route', 'needs_clarification', 'ignored')",
            name=op.f("ck_explicit_intakes_result_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'claimed', 'done', 'failed')",
            name=op.f("ck_explicit_intakes_state"),
        ),
        sa.ForeignKeyConstraint(
            ["chat_binding_id"],
            ["chat_bindings.id"],
            name=op.f("fk_explicit_intakes_chat_binding_id_chat_bindings"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_explicit_intakes")),
    )
    op.create_index(
        op.f("ix_explicit_intakes_chat_id"), "explicit_intakes", ["chat_id"], unique=False
    )
    op.create_index("ix_explicit_intakes_state", "explicit_intakes", ["state"], unique=False)
    op.create_table(
        "route_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("subtype", sa.String(length=100), nullable=False),
        sa.Column("location_scope", sa.String(length=30), nullable=False),
        sa.Column("route_type", sa.String(length=30), nullable=False),
        sa.Column("organization_id", sa.String(length=100), nullable=True),
        sa.Column("channel_id", sa.String(length=100), nullable=True),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("intake_event_id", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('ticket', 'external', 'needs_clarification')",
            name=op.f("ck_route_outcomes_decision"),
        ),
        sa.CheckConstraint(
            "source IN ('group_report', 'form')", name=op.f("ck_route_outcomes_source")
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_route_outcomes_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["intake_event_id"],
            ["explicit_intakes.event_id"],
            name=op.f("fk_route_outcomes_intake_event_id_explicit_intakes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_route_outcomes_report_id_reports"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_outcomes")),
    )
    op.create_index(
        "ix_route_outcomes_house_created",
        "route_outcomes",
        ["house_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_route_outcomes_house_id"), "route_outcomes", ["house_id"], unique=False
    )
    op.create_table(
        "appeal_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("route_outcome_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("ai_assisted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filed_reference", sa.String(length=200), nullable=True),
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
            "filed_at IS NOT NULL OR filed_reference IS NULL",
            name=op.f("ck_appeal_drafts_filed_reference"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_appeal_drafts_version")),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_appeal_drafts_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_appeal_drafts_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["route_outcome_id"],
            ["route_outcomes.id"],
            name=op.f("fk_appeal_drafts_route_outcome_id_route_outcomes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appeal_drafts")),
        sa.UniqueConstraint("route_outcome_id", "author_id", name="uq_appeal_draft_outcome_author"),
    )
    op.create_index(op.f("ix_appeal_drafts_house_id"), "appeal_drafts", ["house_id"], unique=False)
    op.create_index(
        op.f("ix_appeal_drafts_route_outcome_id"),
        "appeal_drafts",
        ["route_outcome_id"],
        unique=False,
    )
    # Место и «с какого времени» заполняются только значениями с цитатой.
    op.add_column("incidents", sa.Column("location_entrance", sa.String(length=50), nullable=True))
    op.add_column("incidents", sa.Column("location_floor", sa.String(length=50), nullable=True))
    op.add_column("incidents", sa.Column("location_label", sa.String(length=200), nullable=True))
    op.add_column("incidents", sa.Column("observed_since", sa.String(length=200), nullable=True))
    # Происхождение разбора без текста реплики.
    op.add_column(
        "reports",
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Доставка карточки маршрута относится к исходу маршрутизации, а не к заявке.
    op.add_column(
        "notification_deliveries", sa.Column("route_outcome_id", sa.Uuid(), nullable=True)
    )
    op.alter_column("notification_deliveries", "ticket_id", existing_type=sa.Uuid(), nullable=True)
    op.create_index(
        op.f("ix_notification_deliveries_route_outcome_id"),
        "notification_deliveries",
        ["route_outcome_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_notification_deliveries_route_outcome_id_route_outcomes"),
        "notification_deliveries",
        "route_outcomes",
        ["route_outcome_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # CHECK-ограничения Alembic не сравнивает: назначение доставки и предмет
    # доставки переописываются здесь явно. Существующие строки проходят оба.
    op.drop_constraint("ck_notification_deliveries_purpose", "notification_deliveries")
    op.create_check_constraint("purpose", "notification_deliveries", sa.text(_NEW_PURPOSE))
    op.create_check_constraint(
        "subject",
        "notification_deliveries",
        sa.text("(ticket_id IS NOT NULL) <> (route_outcome_id IS NOT NULL)"),
    )
    op.create_check_constraint(
        "route_card_subject",
        "notification_deliveries",
        sa.text("purpose <> 'route_action_card' OR route_outcome_id IS NOT NULL"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    retained = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM explicit_intakes)"
            " OR EXISTS (SELECT 1 FROM route_outcomes)"
            " OR EXISTS (SELECT 1 FROM appeal_drafts)"
            " OR EXISTS (SELECT 1 FROM notification_deliveries WHERE ticket_id IS NULL)"
        )
    ).scalar()
    if retained:
        raise RuntimeError(
            "Explicit path intake, route outcomes, appeal drafts or route-card deliveries "
            "are retained; restore a pre-P3b backup before downgrade"
        )
    op.drop_constraint("ck_notification_deliveries_route_card_subject", "notification_deliveries")
    op.drop_constraint("ck_notification_deliveries_subject", "notification_deliveries")
    op.drop_constraint("ck_notification_deliveries_purpose", "notification_deliveries")
    op.create_check_constraint("purpose", "notification_deliveries", sa.text(_OLD_PURPOSE))
    op.drop_constraint(
        op.f("fk_notification_deliveries_route_outcome_id_route_outcomes"),
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_notification_deliveries_route_outcome_id"), table_name="notification_deliveries"
    )
    op.alter_column("notification_deliveries", "ticket_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("notification_deliveries", "route_outcome_id")
    op.drop_column("reports", "analysis")
    op.drop_column("incidents", "observed_since")
    op.drop_column("incidents", "location_label")
    op.drop_column("incidents", "location_floor")
    op.drop_column("incidents", "location_entrance")
    op.drop_index(op.f("ix_appeal_drafts_route_outcome_id"), table_name="appeal_drafts")
    op.drop_index(op.f("ix_appeal_drafts_house_id"), table_name="appeal_drafts")
    op.drop_table("appeal_drafts")
    op.drop_index(op.f("ix_route_outcomes_house_id"), table_name="route_outcomes")
    op.drop_index("ix_route_outcomes_house_created", table_name="route_outcomes")
    op.drop_table("route_outcomes")
    op.drop_index("ix_explicit_intakes_state", table_name="explicit_intakes")
    op.drop_index(op.f("ix_explicit_intakes_chat_id"), table_name="explicit_intakes")
    op.drop_table("explicit_intakes")
    op.drop_table("ai_call_budget")
