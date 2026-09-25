"""housing navigator and house community: profile, mailings, polls, chat settings (D3)

Аддитивная миграция среза D3.

* `company_profiles`: контакты УК «по данным УК» с датой обновления.
* `houses`: число подъездов и этажей «по данным УК» (необязательно).
* `chat_bindings`: что бот может публиковать по решению человека и тихие
  часы (BOT-VOICE-HUMAN-2026-09-27). Прежним чатам: статусы заявок,
  сообщения УК и опросы — разрешены, сообщения платформы — выключены,
  тихие часы 22:00–08:00 МСК.
* `users.broadcast_opt_out_at`: «Не получать рассылки».
* `organization_memberships.daily_digest_enabled`: ежедневная сводка.
* `reports.joined`: «Меня тоже касается» / «Это та же проблема».
* `appeal_drafts`: сопровождение обращения A-09.
* `broadcasts`, `broadcast_houses`, `broadcast_companies`, `polls`,
  `poll_options`, `poll_ballots`, `poll_choices`, `reception_slots`,
  `reception_bookings`.
* `notification_deliveries`: `broadcast_id`, новые назначения; сообщение в
  чат — одна доставка на пару «запись outbox, чат»; одно сообщение в чате на
  заявку; повтор рассылки не дублирует.

Revision ID: 20260927_0013
Revises: 20260926_0012
Create Date: 2026-09-27 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260927_0013"
down_revision: str | None = "20260926_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_CHAT = "('chat_reading_notice','chat_safety_memo','chat_connection_notice','chat_report_ack')"
_NEW_CHAT = (
    "('chat_reading_notice','chat_safety_memo','chat_connection_notice','chat_report_ack',"
    "'broadcast_chat','chat_ticket_status')"
)
_OLD_PURPOSE = (
    "purpose IN ('ticket_accepted','work_verification','route_action_card',"
    "'signal_alert','chat_reading_notice','chat_safety_memo',"
    "'chat_connection_notice','chat_report_ack','bot_reply')"
)
_NEW_PURPOSE = (
    "purpose IN ('ticket_accepted','work_verification','route_action_card',"
    "'signal_alert','chat_reading_notice','chat_safety_memo',"
    "'chat_connection_notice','chat_report_ack','bot_reply',"
    "'broadcast_chat','broadcast_dm','broadcast_staff','chat_ticket_status',"
    "'appeal_followup','staff_digest','reception_reminder')"
)
_SUBJECTS = "ticket_id, route_outcome_id, signal_id, reply_event_id, broadcast_id"


def _check(name: str, table: str, condition: str) -> None:
    op.drop_constraint(f"ck_{table}_{name}", table)
    op.create_check_constraint(name, table, sa.text(condition))


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    # --- профиль УК
    op.create_table(
        "company_profiles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("phone", sa.String(40)),
        sa.Column("email", sa.String(254)),
        sa.Column("dispatcher_phone", sa.String(40)),
        sa.Column("office_hours", sa.String(300)),
        sa.Column("reception_hours", sa.String(300)),
        sa.Column("website", sa.String(300)),
        sa.Column("office_address", sa.String(500)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.Uuid()),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["management_companies.id"],
            name="fk_company_profiles_tenant_id_management_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_company_profiles_updated_by_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_company_profiles"),
    )

    # --- дом: сведения «по данным УК»
    op.add_column("houses", sa.Column("entrance_count", sa.Integer()))
    op.add_column("houses", sa.Column("floor_count", sa.Integer()))
    op.add_column("houses", sa.Column("facts_updated_at", sa.DateTime(timezone=True)))
    op.add_column("houses", sa.Column("facts_updated_by", sa.Uuid()))
    op.create_foreign_key(
        "fk_houses_facts_updated_by_users",
        "houses",
        "users",
        ["facts_updated_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "entrance_count",
        "houses",
        sa.text("entrance_count IS NULL OR entrance_count BETWEEN 1 AND 100"),
    )
    op.create_check_constraint(
        "floor_count", "houses", sa.text("floor_count IS NULL OR floor_count BETWEEN 1 AND 200")
    )

    # --- настройки чата
    for column, default in (
        ("post_ticket_status", "true"),
        ("post_company_messages", "true"),
        ("post_polls", "true"),
        ("post_platform_messages", "false"),
    ):
        op.add_column(
            "chat_bindings",
            sa.Column(column, sa.Boolean(), server_default=default, nullable=False),
        )
    op.add_column(
        "chat_bindings",
        sa.Column("quiet_start_minute", sa.Integer(), server_default="1320", nullable=False),
    )
    op.add_column(
        "chat_bindings",
        sa.Column("quiet_end_minute", sa.Integer(), server_default="480", nullable=False),
    )
    op.add_column("chat_bindings", sa.Column("settings_changed_at", sa.DateTime(timezone=True)))
    op.add_column("chat_bindings", sa.Column("settings_changed_by", sa.Uuid()))
    op.create_foreign_key(
        "fk_chat_bindings_settings_changed_by_users",
        "chat_bindings",
        "users",
        ["settings_changed_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "quiet_hours",
        "chat_bindings",
        sa.text("quiet_start_minute BETWEEN 0 AND 1439 AND quiet_end_minute BETWEEN 0 AND 1439"),
    )

    # --- люди и сотрудники
    op.add_column("users", sa.Column("broadcast_opt_out_at", sa.DateTime(timezone=True)))
    op.add_column(
        "organization_memberships",
        sa.Column("daily_digest_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "reports", sa.Column("joined", sa.Boolean(), server_default="false", nullable=False)
    )

    # --- сопровождение обращения (A-09)
    op.add_column("appeal_drafts", sa.Column("followup_due_at", sa.DateTime(timezone=True)))
    op.add_column("appeal_drafts", sa.Column("followup_sent_at", sa.DateTime(timezone=True)))
    op.add_column("appeal_drafts", sa.Column("followup_answer", sa.String(30)))
    op.add_column("appeal_drafts", sa.Column("followup_answered_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "followup_answer",
        "appeal_drafts",
        sa.text(
            "followup_answer IS NULL OR followup_answer IN "
            "('resolved','answered_unresolved','no_answer')"
        ),
    )
    op.create_check_constraint(
        "followup_answered",
        "appeal_drafts",
        sa.text("(followup_answer IS NULL) = (followup_answered_at IS NULL)"),
    )
    op.create_index(
        "ix_appeal_drafts_followup_due",
        "appeal_drafts",
        ["followup_due_at"],
        postgresql_where=sa.text("followup_sent_at IS NULL AND followup_answer IS NULL"),
    )

    # --- объявления, рассылки, опросы
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("tenant_id", sa.Uuid()),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("topic", sa.String(20)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("audience", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_by", sa.Uuid()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", sa.Uuid()),
        sa.Column("retracted_at", sa.DateTime(timezone=True)),
        sa.Column("retracted_by", sa.Uuid()),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("origin IN ('company','platform')", name="ck_broadcasts_origin"),
        sa.CheckConstraint("kind IN ('announcement','mailing','poll')", name="ck_broadcasts_kind"),
        sa.CheckConstraint(
            "topic IS NULL OR topic IN ('outage','works','meeting','other')",
            name="ck_broadcasts_topic",
        ),
        sa.CheckConstraint(
            "status IN ('draft','scheduled','sent','cancelled')", name="ck_broadcasts_status"
        ),
        sa.CheckConstraint(
            "(origin = 'company') = (tenant_id IS NOT NULL)", name="ck_broadcasts_origin_tenant"
        ),
        sa.CheckConstraint("char_length(body) <= 3000", name="ck_broadcasts_body_length"),
        sa.CheckConstraint("version >= 1 AND content_version >= 1", name="ck_broadcasts_version"),
        sa.CheckConstraint(
            "status <> 'scheduled' OR (scheduled_at IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_broadcasts_scheduled",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["management_companies.id"],
            name="fk_broadcasts_tenant_id_management_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name="fk_broadcasts_confirmed_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"], ["users.id"], name="fk_broadcasts_cancelled_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["retracted_by"], ["users.id"], name="fk_broadcasts_retracted_by_users"
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name="fk_broadcasts_author_id_users"),
        sa.PrimaryKeyConstraint("id", name="pk_broadcasts"),
    )
    op.create_index("ix_broadcasts_tenant_created", "broadcasts", ["tenant_id", "created_at"])
    op.create_table(
        "broadcast_houses",
        sa.Column("broadcast_id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["broadcast_id"],
            ["broadcasts.id"],
            name="fk_broadcast_houses_broadcast_id_broadcasts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name="fk_broadcast_houses_house_id_houses",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("broadcast_id", "house_id", name="pk_broadcast_houses"),
    )
    op.create_index("ix_broadcast_houses_house_id", "broadcast_houses", ["house_id"])
    op.create_table(
        "broadcast_companies",
        sa.Column("broadcast_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["broadcast_id"],
            ["broadcasts.id"],
            name="fk_broadcast_companies_broadcast_id_broadcasts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["management_companies.id"],
            name="fk_broadcast_companies_tenant_id_management_companies",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("broadcast_id", "tenant_id", name="pk_broadcast_companies"),
    )
    op.create_index("ix_broadcast_companies_tenant_id", "broadcast_companies", ["tenant_id"])

    op.create_table(
        "polls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("broadcast_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.String(300), nullable=False),
        sa.Column("multiple", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_id"],
            ["broadcasts.id"],
            name="fk_polls_broadcast_id_broadcasts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_polls"),
        sa.UniqueConstraint("broadcast_id", name="uq_polls_broadcast_id"),
    )
    op.create_table(
        "poll_options",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 10", name="ck_poll_options_position"),
        sa.ForeignKeyConstraint(
            ["poll_id"], ["polls.id"], name="fk_poll_options_poll_id_polls", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_poll_options"),
        sa.UniqueConstraint("poll_id", "position", name="uq_poll_option_position"),
    )
    op.create_index("ix_poll_options_poll_id", "poll_options", ["poll_id"])
    op.create_table(
        "poll_ballots",
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["poll_id"], ["polls.id"], name="fk_poll_ballots_poll_id_polls", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_poll_ballots_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name="fk_poll_ballots_house_id_houses",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("poll_id", "user_id", name="pk_poll_ballots"),
    )
    op.create_table(
        "poll_choices",
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("option_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["poll_id", "user_id"],
            ["poll_ballots.poll_id", "poll_ballots.user_id"],
            name="fk_poll_choice_ballot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["option_id"],
            ["poll_options.id"],
            name="fk_poll_choices_option_id_poll_options",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("poll_id", "user_id", "option_id", name="pk_poll_choices"),
    )
    op.create_index("ix_poll_choices_option_id", "poll_choices", ["option_id"])

    # --- запись на приём
    op.create_table(
        "reception_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.SmallInteger(), server_default="30", nullable=False),
        sa.Column("capacity", sa.SmallInteger(), nullable=False),
        sa.Column("place", sa.String(500)),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("capacity BETWEEN 1 AND 50", name="ck_reception_slots_capacity"),
        sa.CheckConstraint(
            "duration_minutes BETWEEN 5 AND 240", name="ck_reception_slots_duration"
        ),
        sa.CheckConstraint("status IN ('open','cancelled')", name="ck_reception_slots_status"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["management_companies.id"],
            name="fk_reception_slots_tenant_id_management_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_reception_slots_created_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reception_slots"),
    )
    op.create_index(
        "ix_reception_slots_tenant_start", "reception_slots", ["tenant_id", "starts_at"]
    )
    op.create_table(
        "reception_bookings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slot_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), server_default="booked", nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint("status IN ('booked','cancelled')", name="ck_reception_bookings_status"),
        sa.ForeignKeyConstraint(
            ["slot_id"],
            ["reception_slots.id"],
            name="fk_reception_bookings_slot_id_reception_slots",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_reception_bookings_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name="fk_reception_bookings_house_id_houses",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reception_bookings"),
    )
    op.create_index("ix_reception_bookings_slot_id", "reception_bookings", ["slot_id"])
    op.create_index(
        "uq_reception_booking_active",
        "reception_bookings",
        ["slot_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'booked'"),
    )

    # --- доставки
    op.add_column("notification_deliveries", sa.Column("broadcast_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_notification_deliveries_broadcast_id_broadcasts",
        "notification_deliveries",
        "broadcasts",
        ["broadcast_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_notification_deliveries_broadcast_id", "notification_deliveries", ["broadcast_id"]
    )
    _check("purpose", "notification_deliveries", _NEW_PURPOSE)
    _check(
        "subject",
        "notification_deliveries",
        f"num_nonnulls({_SUBJECTS}) = 1 "
        f"OR (num_nonnulls({_SUBJECTS}) = 0 AND chat_binding_id IS NOT NULL)",
    )
    _check(
        "chat_subject",
        "notification_deliveries",
        f"purpose NOT IN {_NEW_CHAT} "
        "OR (chat_binding_id IS NOT NULL AND recipient_user_id IS NULL)",
    )
    _check(
        "recipient",
        "notification_deliveries",
        f"recipient_user_id IS NOT NULL OR purpose IN {_NEW_CHAT} "
        "OR (purpose = 'signal_alert' AND status = 'skipped')",
    )
    op.create_check_constraint(
        "broadcast_subject",
        "notification_deliveries",
        sa.text(
            "purpose NOT IN ('broadcast_chat','broadcast_dm','broadcast_staff') "
            "OR broadcast_id IS NOT NULL"
        ),
    )
    op.create_check_constraint(
        "ticket_chat_subject",
        "notification_deliveries",
        sa.text("purpose <> 'chat_ticket_status' OR ticket_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "keyed_subject",
        "notification_deliveries",
        sa.text(
            "purpose NOT IN ('appeal_followup','staff_digest','reception_reminder') "
            "OR (reply_event_id IS NOT NULL AND recipient_user_id IS NOT NULL)"
        ),
    )
    op.drop_index("uq_delivery_outbox_without_recipient", table_name="notification_deliveries")
    op.create_index(
        "uq_delivery_outbox_chat",
        "notification_deliveries",
        ["outbox_message_id", "chat_binding_id"],
        unique=True,
        postgresql_where=sa.text("recipient_user_id IS NULL"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_delivery_ticket_chat",
        "notification_deliveries",
        ["ticket_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'chat_ticket_status'"),
    )
    op.create_index(
        "uq_delivery_broadcast_chat",
        "notification_deliveries",
        ["broadcast_id", "chat_binding_id"],
        unique=True,
        postgresql_where=sa.text("purpose = 'broadcast_chat'"),
    )
    op.create_index(
        "uq_delivery_broadcast_person",
        "notification_deliveries",
        ["broadcast_id", "purpose", "recipient_user_id"],
        unique=True,
        postgresql_where=sa.text("purpose IN ('broadcast_dm','broadcast_staff')"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    retained = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM broadcasts) "
            "OR EXISTS (SELECT 1 FROM reception_slots) "
            "OR EXISTS (SELECT 1 FROM notification_deliveries WHERE purpose IN "
            "('broadcast_chat','broadcast_dm','broadcast_staff','chat_ticket_status',"
            "'appeal_followup','staff_digest','reception_reminder'))"
        )
    ).scalar()
    if retained:
        raise RuntimeError(
            "Mailings, polls, chat ticket posts or reception history is retained; "
            "restore a pre-D3 backup before downgrade"
        )
    op.drop_index("uq_delivery_broadcast_person", table_name="notification_deliveries")
    op.drop_index("uq_delivery_broadcast_chat", table_name="notification_deliveries")
    op.drop_index("uq_delivery_ticket_chat", table_name="notification_deliveries")
    op.drop_index("uq_delivery_outbox_chat", table_name="notification_deliveries")
    op.create_index(
        "uq_delivery_outbox_without_recipient",
        "notification_deliveries",
        ["outbox_message_id"],
        unique=True,
        postgresql_where=sa.text("recipient_user_id IS NULL"),
    )
    op.drop_constraint("ck_notification_deliveries_keyed_subject", "notification_deliveries")
    op.drop_constraint("ck_notification_deliveries_ticket_chat_subject", "notification_deliveries")
    op.drop_constraint("ck_notification_deliveries_broadcast_subject", "notification_deliveries")
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
        "num_nonnulls(ticket_id, route_outcome_id, signal_id, chat_binding_id, reply_event_id) = 1",
    )
    _check("purpose", "notification_deliveries", _OLD_PURPOSE)
    op.drop_index("ix_notification_deliveries_broadcast_id", table_name="notification_deliveries")
    op.drop_constraint(
        "fk_notification_deliveries_broadcast_id_broadcasts",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_column("notification_deliveries", "broadcast_id")

    op.drop_table("reception_bookings")
    op.drop_table("reception_slots")
    op.drop_table("poll_choices")
    op.drop_table("poll_ballots")
    op.drop_table("poll_options")
    op.drop_table("polls")
    op.drop_table("broadcast_companies")
    op.drop_table("broadcast_houses")
    op.drop_index("ix_broadcasts_tenant_created", table_name="broadcasts")
    op.drop_table("broadcasts")

    op.drop_index("ix_appeal_drafts_followup_due", table_name="appeal_drafts")
    op.drop_constraint("ck_appeal_drafts_followup_answered", "appeal_drafts")
    op.drop_constraint("ck_appeal_drafts_followup_answer", "appeal_drafts")
    for column in (
        "followup_answered_at",
        "followup_answer",
        "followup_sent_at",
        "followup_due_at",
    ):
        op.drop_column("appeal_drafts", column)

    op.drop_column("reports", "joined")
    op.drop_column("organization_memberships", "daily_digest_enabled")
    op.drop_column("users", "broadcast_opt_out_at")

    op.drop_constraint("ck_chat_bindings_quiet_hours", "chat_bindings")
    op.drop_constraint(
        "fk_chat_bindings_settings_changed_by_users", "chat_bindings", type_="foreignkey"
    )
    for column in (
        "settings_changed_by",
        "settings_changed_at",
        "quiet_end_minute",
        "quiet_start_minute",
        "post_platform_messages",
        "post_polls",
        "post_company_messages",
        "post_ticket_status",
    ):
        op.drop_column("chat_bindings", column)

    op.drop_constraint("ck_houses_floor_count", "houses")
    op.drop_constraint("ck_houses_entrance_count", "houses")
    op.drop_constraint("fk_houses_facts_updated_by_users", "houses", type_="foreignkey")
    for column in ("facts_updated_by", "facts_updated_at", "floor_count", "entrance_count"):
        op.drop_column("houses", column)

    op.drop_table("company_profiles")
