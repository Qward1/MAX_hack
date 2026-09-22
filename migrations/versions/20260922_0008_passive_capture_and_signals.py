"""passive chat capture: message buffer, conversation windows and signals

Аддитивная миграция пассивного чтения подключённого чата (A-17/Product, P4).
Новые таблицы пусты; к существующим добавлены только столбцы, допускающие NULL
или имеющие значение по умолчанию. `notification_deliveries.recipient_user_id`
лишь ослабляется до NULL (сообщение в групповой чат адресовано чату, а не
человеку), CHECK назначения доставки дополняется, не теряя прежних значений,
а CHECK предмета доставки переписывается так, что каждая существующая строка
его проходит: у неё ровно один из `ticket_id` / `route_outcome_id`.

Revision ID: 20260922_0008
Revises: 20260920_0007
Create Date: 2026-09-22 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260922_0008"
down_revision: str | None = "20260920_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PURPOSE = "purpose IN ('ticket_accepted','work_verification','route_action_card')"
_NEW_PURPOSE = (
    "purpose IN ('ticket_accepted','work_verification','route_action_card',"
    "'signal_alert','chat_reading_notice','chat_safety_memo')"
)
_OLD_SUBJECT = "(ticket_id IS NOT NULL) <> (route_outcome_id IS NOT NULL)"
_NEW_SUBJECT = "num_nonnulls(ticket_id, route_outcome_id, signal_id, chat_binding_id) = 1"
_OLD_SOURCE = "source IN ('group_report', 'form')"
_NEW_SOURCE = "source IN ('group_report', 'form', 'passive')"


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.add_column(
        "chat_bindings",
        sa.Column(
            "passive_capture_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.create_table(
        "chat_author_aliases",
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("external_user_id", sa.String(length=200), nullable=False),
        sa.Column("alias_index", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint("alias_index >= 0", name=op.f("ck_chat_author_aliases_alias_index")),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_chat_author_aliases_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "house_id", "external_user_id", name=op.f("pk_chat_author_aliases")
        ),
        sa.UniqueConstraint("house_id", "alias_index", name="uq_chat_author_alias_index"),
    )
    op.create_table(
        "conversation_windows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("chat_binding_id", sa.Uuid(), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("max_chat_id", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("close_reason", sa.String(length=20), nullable=True),
        sa.Column("has_danger", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("line_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_line_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_line_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tick_job_id", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=100), nullable=True),
        sa.Column("analysis_mode", sa.String(length=20), nullable=True),
        sa.Column("execution_state", sa.String(length=40), nullable=True),
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "state IN ('open', 'closed', 'analyzing', 'done')",
            name=op.f("ck_conversation_windows_state"),
        ),
        sa.CheckConstraint(
            "close_reason IS NULL OR close_reason IN "
            "('silence', 'max_lines', 'max_age', 'danger')",
            name=op.f("ck_conversation_windows_close_reason"),
        ),
        sa.CheckConstraint(
            "(state = 'open') = (closed_at IS NULL)",
            name=op.f("ck_conversation_windows_closed_at"),
        ),
        sa.CheckConstraint("line_count >= 0", name=op.f("ck_conversation_windows_line_count")),
        sa.ForeignKeyConstraint(
            ["chat_binding_id"],
            ["chat_bindings.id"],
            name=op.f("fk_conversation_windows_chat_binding_id_chat_bindings"),
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_conversation_windows_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_windows")),
    )
    op.create_index(
        "uq_conversation_window_open",
        "conversation_windows",
        ["chat_binding_id"],
        unique=True,
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index(
        "ix_conversation_windows_house_created",
        "conversation_windows",
        ["house_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("max_chat_id", sa.String(length=200), nullable=False),
        sa.Column("mid", sa.String(length=200), nullable=False),
        sa.Column("chat_binding_id", sa.Uuid(), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("external_user_id", sa.String(length=200), nullable=False),
        sa.Column("author_ref", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reply_to_mid", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("window_id", sa.Uuid(), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["chat_binding_id"],
            ["chat_bindings.id"],
            name=op.f("fk_chat_messages_chat_binding_id_chat_bindings"),
        ),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["conversation_windows.id"],
            name=op.f("fk_chat_messages_window_id_conversation_windows"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint("max_chat_id", "mid", name="uq_chat_messages_chat_mid"),
    )
    op.create_index(
        "ix_chat_messages_window_sent", "chat_messages", ["window_id", "sent_at"], unique=False
    )
    op.create_index(
        "ix_chat_messages_binding_sent",
        "chat_messages",
        ["chat_binding_id", "sent_at"],
        unique=False,
    )
    op.create_index("ix_chat_messages_received", "chat_messages", ["received_at"], unique=False)
    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("chat_binding_id", sa.Uuid(), nullable=False),
        sa.Column("window_id", sa.Uuid(), nullable=True),
        sa.Column("subtype", sa.String(length=100), nullable=False),
        sa.Column("product_category", sa.String(length=50), nullable=False),
        sa.Column("object_label", sa.String(length=200), nullable=False),
        sa.Column("entrance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("floor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("since", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("location_scope", sa.String(length=30), nullable=False),
        sa.Column("location", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("facets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("strength", sa.String(length=20), nullable=False),
        sa.Column("strength_reason", sa.String(length=60), nullable=False),
        sa.Column("disposition", sa.String(length=20), nullable=False),
        sa.Column("audit_reason", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("emergency", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="new", nullable=False),
        sa.Column("report_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("author_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_outcome_id", sa.Uuid(), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('new', 'in_review', 'converted', 'routed_external', 'dismissed')",
            name=op.f("ck_signals_status"),
        ),
        sa.CheckConstraint(
            "strength IN ('critical', 'strong', 'medium', 'weak', 'filtered')",
            name=op.f("ck_signals_strength"),
        ),
        sa.CheckConstraint(
            "disposition IN ('inbox', 'audit_pool')", name=op.f("ck_signals_disposition")
        ),
        sa.CheckConstraint(
            "source IN ('rules', 'model', 'rules+model')", name=op.f("ck_signals_source")
        ),
        sa.CheckConstraint(
            "report_count >= 0 AND author_count >= 0 AND author_count <= report_count",
            name=op.f("ck_signals_counters"),
        ),
        sa.ForeignKeyConstraint(
            ["chat_binding_id"],
            ["chat_bindings.id"],
            name=op.f("fk_signals_chat_binding_id_chat_bindings"),
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_signals_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["conversation_windows.id"],
            name=op.f("fk_signals_window_id_conversation_windows"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(
        "ix_signals_house_status_seen",
        "signals",
        ["house_id", "status", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_signals_house_dedupe", "signals", ["house_id", "dedupe_key", "status"], unique=False
    )
    # Исход маршрутизации пассивного сигнала.
    op.add_column("route_outcomes", sa.Column("signal_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_route_outcomes_signal_id"), "route_outcomes", ["signal_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_route_outcomes_signal_id_signals"),
        "route_outcomes",
        "signals",
        ["signal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint("ck_route_outcomes_source", "route_outcomes")
    op.create_check_constraint("source", "route_outcomes", sa.text(_NEW_SOURCE))
    op.create_foreign_key(
        "fk_signals_route_outcome_id_route_outcomes",
        "signals",
        "route_outcomes",
        ["route_outcome_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "signal_quotes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("line_mid", sa.String(length=200), nullable=False),
        sa.Column("author_ref", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_signal_quotes_signal_id_signals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_quotes")),
        sa.UniqueConstraint("signal_id", "line_mid", name="uq_signal_quote_line"),
    )
    op.create_index(
        op.f("ix_signal_quotes_signal_id"), "signal_quotes", ["signal_id"], unique=False
    )
    op.create_table(
        "signal_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("window_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("line_mid", sa.String(length=200), nullable=False),
        sa.Column("author_ref", sa.String(length=16), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=True),
        sa.Column("link_certainty", sa.String(length=10), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_signal_lines_signal_id_signals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["conversation_windows.id"],
            name=op.f("fk_signal_lines_window_id_conversation_windows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_lines")),
        sa.UniqueConstraint("window_id", "line_mid", "signal_id", name="uq_signal_line"),
    )
    op.create_index("ix_signal_lines_signal", "signal_lines", ["signal_id"], unique=False)
    op.create_table(
        "signal_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("window_id", sa.Uuid(), nullable=True),
        sa.Column("line_mid", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("details", sa.Text(), server_default="", nullable=False),
        sa.Column("versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_signal_events_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_signal_events_signal_id_signals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["window_id"],
            ["conversation_windows.id"],
            name=op.f("fk_signal_events_window_id_conversation_windows"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signal_events")),
    )
    op.create_index(
        "ix_signal_events_house_created",
        "signal_events",
        ["house_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_signal_events_signal_id"), "signal_events", ["signal_id"], unique=False
    )
    op.create_index(
        op.f("ix_signal_events_window_id"), "signal_events", ["window_id"], unique=False
    )
    # Доставка: оповещение оператора относится к сигналу, сообщение в чат — к
    # привязке и адресовано чату, а не человеку.
    op.add_column("notification_deliveries", sa.Column("signal_id", sa.Uuid(), nullable=True))
    op.add_column(
        "notification_deliveries", sa.Column("chat_binding_id", sa.Uuid(), nullable=True)
    )
    op.create_index(
        op.f("ix_notification_deliveries_signal_id"),
        "notification_deliveries",
        ["signal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_deliveries_chat_binding_id"),
        "notification_deliveries",
        ["chat_binding_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_notification_deliveries_signal_id_signals"),
        "notification_deliveries",
        "signals",
        ["signal_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_notification_deliveries_chat_binding_id_chat_bindings"),
        "notification_deliveries",
        "chat_bindings",
        ["chat_binding_id"],
        ["id"],
    )
    op.alter_column(
        "notification_deliveries", "recipient_user_id", existing_type=sa.Uuid(), nullable=True
    )
    op.create_index(
        "uq_delivery_outbox_without_recipient",
        "notification_deliveries",
        ["outbox_message_id"],
        unique=True,
        postgresql_where=sa.text("recipient_user_id IS NULL"),
    )
    # CHECK-ограничения Alembic не сравнивает: они переописываются явно.
    op.drop_constraint("ck_notification_deliveries_purpose", "notification_deliveries")
    op.create_check_constraint("purpose", "notification_deliveries", sa.text(_NEW_PURPOSE))
    op.drop_constraint("ck_notification_deliveries_subject", "notification_deliveries")
    op.create_check_constraint("subject", "notification_deliveries", sa.text(_NEW_SUBJECT))
    op.create_check_constraint(
        "signal_alert_subject",
        "notification_deliveries",
        sa.text("purpose <> 'signal_alert' OR signal_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "chat_subject",
        "notification_deliveries",
        sa.text(
            "purpose NOT IN ('chat_reading_notice','chat_safety_memo') "
            "OR (chat_binding_id IS NOT NULL AND recipient_user_id IS NULL)"
        ),
    )
    op.create_check_constraint(
        "recipient",
        "notification_deliveries",
        sa.text(
            "recipient_user_id IS NOT NULL "
            "OR purpose IN ('chat_reading_notice','chat_safety_memo') "
            "OR (purpose = 'signal_alert' AND status = 'skipped')"
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    retained = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM chat_messages)"
            " OR EXISTS (SELECT 1 FROM conversation_windows)"
            " OR EXISTS (SELECT 1 FROM signals)"
            " OR EXISTS (SELECT 1 FROM signal_events)"
            " OR EXISTS (SELECT 1 FROM chat_author_aliases)"
            " OR EXISTS (SELECT 1 FROM route_outcomes WHERE source = 'passive')"
            " OR EXISTS (SELECT 1 FROM notification_deliveries WHERE recipient_user_id IS NULL"
            "   OR signal_id IS NOT NULL OR chat_binding_id IS NOT NULL)"
            " OR EXISTS (SELECT 1 FROM chat_bindings WHERE passive_capture_enabled)"
        )
    ).scalar()
    if retained:
        raise RuntimeError(
            "Passive chat capture data, signals, chat deliveries or enabled passive bindings "
            "are retained; restore a pre-P4 backup before downgrade"
        )
    op.drop_constraint("ck_notification_deliveries_recipient", "notification_deliveries")
    op.drop_constraint("ck_notification_deliveries_chat_subject", "notification_deliveries")
    op.drop_constraint(
        "ck_notification_deliveries_signal_alert_subject", "notification_deliveries"
    )
    op.drop_constraint("ck_notification_deliveries_subject", "notification_deliveries")
    op.create_check_constraint("subject", "notification_deliveries", sa.text(_OLD_SUBJECT))
    op.drop_constraint("ck_notification_deliveries_purpose", "notification_deliveries")
    op.create_check_constraint("purpose", "notification_deliveries", sa.text(_OLD_PURPOSE))
    op.drop_index("uq_delivery_outbox_without_recipient", table_name="notification_deliveries")
    op.alter_column(
        "notification_deliveries", "recipient_user_id", existing_type=sa.Uuid(), nullable=False
    )
    op.drop_constraint(
        op.f("fk_notification_deliveries_chat_binding_id_chat_bindings"),
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_notification_deliveries_signal_id_signals"),
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_notification_deliveries_chat_binding_id"), table_name="notification_deliveries"
    )
    op.drop_index(
        op.f("ix_notification_deliveries_signal_id"), table_name="notification_deliveries"
    )
    op.drop_column("notification_deliveries", "chat_binding_id")
    op.drop_column("notification_deliveries", "signal_id")
    op.drop_index(op.f("ix_signal_events_window_id"), table_name="signal_events")
    op.drop_index(op.f("ix_signal_events_signal_id"), table_name="signal_events")
    op.drop_index("ix_signal_events_house_created", table_name="signal_events")
    op.drop_table("signal_events")
    op.drop_index("ix_signal_lines_signal", table_name="signal_lines")
    op.drop_table("signal_lines")
    op.drop_index(op.f("ix_signal_quotes_signal_id"), table_name="signal_quotes")
    op.drop_table("signal_quotes")
    op.drop_constraint(
        "fk_signals_route_outcome_id_route_outcomes", "signals", type_="foreignkey"
    )
    op.drop_constraint("ck_route_outcomes_source", "route_outcomes")
    op.create_check_constraint("source", "route_outcomes", sa.text(_OLD_SOURCE))
    op.drop_constraint(
        op.f("fk_route_outcomes_signal_id_signals"), "route_outcomes", type_="foreignkey"
    )
    op.drop_index(op.f("ix_route_outcomes_signal_id"), table_name="route_outcomes")
    op.drop_column("route_outcomes", "signal_id")
    op.drop_index("ix_signals_house_dedupe", table_name="signals")
    op.drop_index("ix_signals_house_status_seen", table_name="signals")
    op.drop_table("signals")
    op.drop_index("ix_chat_messages_received", table_name="chat_messages")
    op.drop_index("ix_chat_messages_binding_sent", table_name="chat_messages")
    op.drop_index("ix_chat_messages_window_sent", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversation_windows_house_created", table_name="conversation_windows")
    op.drop_index("uq_conversation_window_open", table_name="conversation_windows")
    op.drop_table("conversation_windows")
    op.drop_table("chat_author_aliases")
    op.drop_column("chat_bindings", "passive_capture_enabled")
