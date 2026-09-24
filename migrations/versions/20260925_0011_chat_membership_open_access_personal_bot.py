"""chat membership, open house access and the personal bot (D1)

Аддитивная миграция среза D1.

* `resident_memberships`: основание членства по чату (`source = 'chat_member'`,
  привязка и её версия, время проверки) и по открытому доступу
  (`open_access`); завершение с причиной. Прежняя уникальность «один житель —
  один дом» остаётся для прежних источников; для новых — одна **действующая**
  запись, завершённые остаются историей.
* `chat_member_checks`: время и исход последнего вызова MAX API на пару
  «пользователь, чат» — не чаще одного вызова за 15 минут.
* `houses.open_resident_access`: переключатель открытого доступа к дому.
* `users`: диалог с ботом (когда начат и остановлен) и время последнего
  ответа в группе на `/report`.
* `explicit_intakes`: канал `dm_report` — сообщение о проблеме в личке бота:
  дом выбирается после приёма, поэтому привязки чата у такой записи нет.
* `route_outcomes.source` — `dm_report`; доставки — ответ бота в личке,
  сообщение о подключении и ответ в группе на `/report`.

Revision ID: 20260925_0011
Revises: 20260924_0010
Create Date: 2026-09-25 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260925_0011"
down_revision: str | None = "20260924_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_PURPOSE = (
    "purpose IN ('ticket_accepted','work_verification','route_action_card',"
    "'signal_alert','chat_reading_notice','chat_safety_memo')"
)
_NEW_PURPOSE = (
    "purpose IN ('ticket_accepted','work_verification','route_action_card',"
    "'signal_alert','chat_reading_notice','chat_safety_memo',"
    "'chat_connection_notice','chat_report_ack','bot_reply')"
)
_CHAT = "('chat_reading_notice','chat_safety_memo','chat_connection_notice','chat_report_ack')"
_OLD_CHAT = "('chat_reading_notice','chat_safety_memo')"


def _check(name: str, table: str, condition: str) -> None:
    op.drop_constraint(f"ck_{table}_{name}", table)
    op.create_check_constraint(name, table, sa.text(condition))


def upgrade() -> None:
    # --- дом: открытый доступ
    op.add_column(
        "houses",
        sa.Column(
            "open_resident_access", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column(
        "houses", sa.Column("open_access_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("houses", sa.Column("open_access_changed_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_houses_open_access_changed_by_users",
        "houses",
        "users",
        ["open_access_changed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- пользователь: диалог с ботом и ответ в группе
    op.add_column("users", sa.Column("max_dialog_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("max_dialog_stopped_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("group_ack_at", sa.DateTime(timezone=True), nullable=True))

    # --- членство: основание по чату и открытому доступу
    op.add_column("resident_memberships", sa.Column("chat_binding_id", sa.Uuid(), nullable=True))
    op.add_column(
        "resident_memberships", sa.Column("binding_version", sa.Integer(), nullable=True)
    )
    op.add_column(
        "resident_memberships", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "resident_memberships", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "resident_memberships", sa.Column("end_reason", sa.String(length=40), nullable=True)
    )
    op.create_foreign_key(
        "fk_resident_memberships_chat_binding_id_chat_bindings",
        "resident_memberships",
        "chat_bindings",
        ["chat_binding_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_resident_memberships_chat_binding_id"),
        "resident_memberships",
        ["chat_binding_id"],
        unique=False,
    )
    op.create_check_constraint(
        "chat_basis",
        "resident_memberships",
        sa.text(
            "(source = 'chat_member') = (chat_binding_id IS NOT NULL) AND "
            "(source <> 'chat_member' OR (binding_version IS NOT NULL "
            "AND checked_at IS NOT NULL AND expires_at IS NOT NULL))"
        ),
    )
    op.create_check_constraint(
        "end_reason",
        "resident_memberships",
        sa.text(
            "end_reason IS NULL OR end_reason IN "
            "('user_removed','not_member','open_access_closed')"
        ),
    )
    op.create_check_constraint(
        "ended",
        "resident_memberships",
        sa.text(
            "source NOT IN ('chat_member', 'open_access') "
            "OR (status = 'active') = (ended_at IS NULL)"
        ),
    )
    op.drop_constraint("uq_resident_user_house", "resident_memberships", type_="unique")
    op.create_index(
        "uq_resident_user_house",
        "resident_memberships",
        ["user_id", "house_id"],
        unique=True,
        postgresql_where=sa.text("source NOT IN ('chat_member', 'open_access')"),
    )
    op.create_index(
        "uq_resident_chat_member_active",
        "resident_memberships",
        ["user_id", "chat_binding_id"],
        unique=True,
        postgresql_where=sa.text("source = 'chat_member' AND status = 'active'"),
    )
    op.create_index(
        "uq_resident_open_access_active",
        "resident_memberships",
        ["user_id", "house_id"],
        unique=True,
        postgresql_where=sa.text("source = 'open_access' AND status = 'active'"),
    )

    # --- проверки участия в чате: не чаще одного вызова на пару за 15 минут
    op.create_table(
        "chat_member_checks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("max_chat_id", sa.String(length=200), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('member','not_member','error')",
            name=op.f("ck_chat_member_checks_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_chat_member_checks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "max_chat_id", name=op.f("pk_chat_member_checks")),
    )

    # --- приём: канал личных сообщений
    op.add_column(
        "explicit_intakes",
        sa.Column(
            "channel", sa.String(length=20), server_default="group_report", nullable=False
        ),
    )
    op.add_column("explicit_intakes", sa.Column("house_id", sa.Uuid(), nullable=True))
    op.add_column("explicit_intakes", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "explicit_intakes", sa.Column("hold_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "explicit_intakes",
        sa.Column(
            "pending_analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.create_foreign_key(
        "fk_explicit_intakes_house_id_houses",
        "explicit_intakes",
        "houses",
        ["house_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_explicit_intakes_user_id_users",
        "explicit_intakes",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_explicit_intakes_user_created", "explicit_intakes", ["user_id", "created_at"]
    )
    op.alter_column("explicit_intakes", "chat_binding_id", nullable=True)
    op.alter_column("explicit_intakes", "binding_version", nullable=True)
    op.create_check_constraint(
        "channel", "explicit_intakes", sa.text("channel IN ('group_report','dm_report')")
    )
    op.create_check_constraint(
        "origin",
        "explicit_intakes",
        sa.text(
            "(channel = 'group_report' AND chat_binding_id IS NOT NULL "
            "AND binding_version IS NOT NULL) OR "
            "(channel = 'dm_report' AND chat_binding_id IS NULL AND user_id IS NOT NULL)"
        ),
    )
    _check(
        "state",
        "explicit_intakes",
        "state IN ('pending', 'claimed', 'done', 'failed', 'awaiting_house', 'awaiting_choice')",
    )
    _check(
        "claimed_at",
        "explicit_intakes",
        "(state IN ('pending', 'awaiting_house')) = (claimed_at IS NULL)",
    )
    _check(
        "result_kind",
        "explicit_intakes",
        "result_kind IS NULL OR result_kind IN "
        "('ticket', 'external_route', 'needs_clarification', 'ignored', "
        "'not_a_problem', 'expired', 'joined')",
    )
    _check(
        "source",
        "route_outcomes",
        "source IN ('group_report', 'form', 'passive', 'dm_report')",
    )

    # --- доставки: ответ бота в личке, сообщение о подключении, ответ в группе
    op.add_column(
        "notification_deliveries",
        sa.Column("reply_event_id", sa.String(length=200), nullable=True),
    )
    _check("purpose", "notification_deliveries", _NEW_PURPOSE)
    _check(
        "subject",
        "notification_deliveries",
        "num_nonnulls(ticket_id, route_outcome_id, signal_id, chat_binding_id, "
        "reply_event_id) = 1",
    )
    _check(
        "chat_subject",
        "notification_deliveries",
        f"purpose NOT IN {_CHAT} OR (chat_binding_id IS NOT NULL AND recipient_user_id IS NULL)",
    )
    _check(
        "recipient",
        "notification_deliveries",
        f"recipient_user_id IS NOT NULL OR purpose IN {_CHAT} "
        "OR (purpose = 'signal_alert' AND status = 'skipped')",
    )
    op.create_check_constraint(
        "bot_reply_subject",
        "notification_deliveries",
        sa.text(
            "purpose <> 'bot_reply' OR (reply_event_id IS NOT NULL "
            "AND recipient_user_id IS NOT NULL)"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    retained = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM resident_memberships "
            "WHERE source IN ('chat_member', 'open_access')) "
            "OR EXISTS (SELECT 1 FROM explicit_intakes WHERE channel = 'dm_report') "
            "OR EXISTS (SELECT 1 FROM route_outcomes WHERE source = 'dm_report') "
            "OR EXISTS (SELECT 1 FROM notification_deliveries WHERE purpose IN "
            "('chat_connection_notice','chat_report_ack','bot_reply'))"
        )
    ).scalar()
    if retained:
        raise RuntimeError(
            "Chat membership, open access or personal bot history is retained; "
            "restore a pre-D1 backup before downgrade"
        )
    op.drop_constraint(
        "ck_notification_deliveries_bot_reply_subject", "notification_deliveries"
    )
    _check(
        "recipient",
        "notification_deliveries",
        f"recipient_user_id IS NOT NULL OR purpose IN {_OLD_CHAT} "
        "OR (purpose = 'signal_alert' AND status = 'skipped')",
    )
    _check(
        "chat_subject",
        "notification_deliveries",
        f"purpose NOT IN {_OLD_CHAT} "
        "OR (chat_binding_id IS NOT NULL AND recipient_user_id IS NULL)",
    )
    _check(
        "subject",
        "notification_deliveries",
        "num_nonnulls(ticket_id, route_outcome_id, signal_id, chat_binding_id) = 1",
    )
    _check("purpose", "notification_deliveries", _OLD_PURPOSE)
    op.drop_column("notification_deliveries", "reply_event_id")

    _check("source", "route_outcomes", "source IN ('group_report', 'form', 'passive')")
    _check(
        "result_kind",
        "explicit_intakes",
        "result_kind IS NULL OR result_kind IN "
        "('ticket', 'external_route', 'needs_clarification', 'ignored')",
    )
    _check("claimed_at", "explicit_intakes", "(state = 'pending') = (claimed_at IS NULL)")
    _check("state", "explicit_intakes", "state IN ('pending', 'claimed', 'done', 'failed')")
    op.drop_constraint("ck_explicit_intakes_origin", "explicit_intakes")
    op.drop_constraint("ck_explicit_intakes_channel", "explicit_intakes")
    op.alter_column("explicit_intakes", "binding_version", nullable=False)
    op.alter_column("explicit_intakes", "chat_binding_id", nullable=False)
    op.drop_index("ix_explicit_intakes_user_created", table_name="explicit_intakes")
    op.drop_constraint("fk_explicit_intakes_user_id_users", "explicit_intakes")
    op.drop_constraint("fk_explicit_intakes_house_id_houses", "explicit_intakes")
    for column in ("pending_analysis", "hold_until", "user_id", "house_id", "channel"):
        op.drop_column("explicit_intakes", column)

    op.drop_table("chat_member_checks")

    op.drop_index("uq_resident_open_access_active", table_name="resident_memberships")
    op.drop_index("uq_resident_chat_member_active", table_name="resident_memberships")
    op.drop_index("uq_resident_user_house", table_name="resident_memberships")
    op.create_unique_constraint(
        "uq_resident_user_house", "resident_memberships", ["user_id", "house_id"]
    )
    op.drop_constraint("ck_resident_memberships_ended", "resident_memberships")
    op.drop_constraint("ck_resident_memberships_end_reason", "resident_memberships")
    op.drop_constraint("ck_resident_memberships_chat_basis", "resident_memberships")
    op.drop_index(
        op.f("ix_resident_memberships_chat_binding_id"), table_name="resident_memberships"
    )
    op.drop_constraint(
        "fk_resident_memberships_chat_binding_id_chat_bindings", "resident_memberships"
    )
    for column in ("end_reason", "ended_at", "checked_at", "binding_version", "chat_binding_id"):
        op.drop_column("resident_memberships", column)

    for column in ("group_ack_at", "max_dialog_stopped_at", "max_dialog_at"):
        op.drop_column("users", column)

    op.drop_constraint("fk_houses_open_access_changed_by_users", "houses")
    for column in ("open_access_changed_by", "open_access_changed_at", "open_resident_access"):
        op.drop_column("houses", column)
