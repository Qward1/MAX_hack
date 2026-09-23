"""signal decisions: operator inbox, window fallback and route snapshots

Аддитивная миграция очереди сигналов оператора (P5). К `signals` добавлены
версия и поля решения оператора; существующие сигналы получают `version = 1`,
остальные столбцы пусты. CHECK «решённый статус ⇔ есть время решения»
проходят все прежние строки: до P5 сигнал не мог быть решён.

`signal_events.actor_id` — автор решения; события ядра остаются без автора.
`conversation_windows.analyzed_by` — кто разобрал окно: AI-пул или сторож
правил. `route_outcomes.basis` и `directory_version` — снимок маршрута в
момент решения оператора; прежние исходы остаются без снимка.

Revision ID: 20260923_0009
Revises: 20260922_0008
Create Date: 2026-09-23 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0009"
down_revision: str | None = "20260922_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DECIDED = "(status IN ('converted', 'routed_external', 'dismissed')) = (decided_at IS NOT NULL)"
_REASON = (
    "decision_reason IS NULL OR decision_reason IN "
    "('not_a_problem', 'duplicate', 'resolved', 'out_of_scope', 'spam')"
)


def upgrade() -> None:
    op.add_column("signals", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("signals", sa.Column("decided_by", sa.Uuid(), nullable=True))
    op.add_column("signals", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("signals", sa.Column("decision_reason", sa.String(length=30), nullable=True))
    op.add_column("signals", sa.Column("decision_note", sa.String(length=500), nullable=True))
    op.add_column("signals", sa.Column("report_id", sa.Uuid(), nullable=True))
    op.add_column("signals", sa.Column("incident_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_signals_decided_by_users"),
        "signals",
        "users",
        ["decided_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_signals_report_id_reports"),
        "signals",
        "reports",
        ["report_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_signals_incident_id_incidents"),
        "signals",
        "incidents",
        ["incident_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint("version", "signals", sa.text("version >= 1"))
    op.create_check_constraint("decided", "signals", sa.text(_DECIDED))
    op.create_check_constraint("decision_reason", "signals", sa.text(_REASON))
    op.create_index("ix_signals_incident", "signals", ["incident_id"], unique=False)

    op.add_column("signal_events", sa.Column("actor_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_signal_events_actor_id_users"),
        "signal_events",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.add_column(
        "conversation_windows", sa.Column("analyzed_by", sa.String(length=20), nullable=True)
    )
    op.create_check_constraint(
        "analyzed_by",
        "conversation_windows",
        sa.text("analyzed_by IS NULL OR analyzed_by IN ('ai', 'fallback')"),
    )

    op.add_column(
        "route_outcomes",
        sa.Column("basis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "route_outcomes", sa.Column("directory_version", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    connection = op.get_bind()
    retained = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM signals WHERE decided_at IS NOT NULL"
            "   OR status = 'in_review')"
            " OR EXISTS (SELECT 1 FROM signal_events WHERE actor_id IS NOT NULL)"
            " OR EXISTS (SELECT 1 FROM route_outcomes WHERE basis IS NOT NULL"
            "   OR directory_version IS NOT NULL)"
        )
    ).scalar()
    if retained:
        raise RuntimeError(
            "Operator signal decisions or route snapshots are retained; "
            "restore a pre-P5 backup before downgrade"
        )
    op.drop_column("route_outcomes", "directory_version")
    op.drop_column("route_outcomes", "basis")
    op.drop_constraint("ck_conversation_windows_analyzed_by", "conversation_windows")
    op.drop_column("conversation_windows", "analyzed_by")
    op.drop_constraint(op.f("fk_signal_events_actor_id_users"), "signal_events", type_="foreignkey")
    op.drop_column("signal_events", "actor_id")
    op.drop_index("ix_signals_incident", table_name="signals")
    op.drop_constraint("ck_signals_decision_reason", "signals")
    op.drop_constraint("ck_signals_decided", "signals")
    op.drop_constraint("ck_signals_version", "signals")
    op.drop_constraint(op.f("fk_signals_incident_id_incidents"), "signals", type_="foreignkey")
    op.drop_constraint(op.f("fk_signals_report_id_reports"), "signals", type_="foreignkey")
    op.drop_constraint(op.f("fk_signals_decided_by_users"), "signals", type_="foreignkey")
    for column in (
        "incident_id",
        "report_id",
        "decision_note",
        "decision_reason",
        "decided_at",
        "decided_by",
        "version",
    ):
        op.drop_column("signals", column)
