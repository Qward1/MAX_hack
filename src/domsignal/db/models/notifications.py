from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

#: Назначения доставки в групповой чат: получатель — чат, а не человек.
CHAT_PURPOSES = (
    "chat_reading_notice",
    "chat_safety_memo",
    "chat_connection_notice",
    "chat_report_ack",
    # D3 (BOT-VOICE-HUMAN-2026-09-27): пост по решению человека.
    "broadcast_chat",
    "chat_ticket_status",
)

#: Оповещение оператора о критическом сигнале.
SIGNAL_ALERT_PURPOSE = "signal_alert"

#: Ответ личного бота на событие жителя (D1).
BOT_REPLY_PURPOSE = "bot_reply"

#: D3: объявление/рассылка/опрос — в чат, жителю в личку, сотруднику в личку.
BROADCAST_CHAT_PURPOSE = "broadcast_chat"
BROADCAST_DM_PURPOSE = "broadcast_dm"
BROADCAST_STAFF_PURPOSE = "broadcast_staff"
BROADCAST_PURPOSES = (BROADCAST_CHAT_PURPOSE, BROADCAST_DM_PURPOSE, BROADCAST_STAFF_PURPOSE)
#: D3: одно сообщение бота в чате о заявке, созданной по решению человека.
TICKET_CHAT_PURPOSE = "chat_ticket_status"
#: D3: личные сообщения по ключу (`reply_event_id`): сопровождение обращения
#: (A-09), ежедневная сводка сотруднику, напоминание о записи на приём.
APPEAL_FOLLOWUP_PURPOSE = "appeal_followup"
STAFF_DIGEST_PURPOSE = "staff_digest"
RECEPTION_REMINDER_PURPOSE = "reception_reminder"
KEYED_PURPOSES = (APPEAL_FOLLOWUP_PURPOSE, STAFF_DIGEST_PURPOSE, RECEPTION_REMINDER_PURPOSE)

ALL_PURPOSES = (
    "ticket_accepted",
    "work_verification",
    "route_action_card",
    SIGNAL_ALERT_PURPOSE,
    *CHAT_PURPOSES[:4],
    BOT_REPLY_PURPOSE,
    BROADCAST_CHAT_PURPOSE,
    BROADCAST_DM_PURPOSE,
    BROADCAST_STAFF_PURPOSE,
    TICKET_CHAT_PURPOSE,
    *KEYED_PURPOSES,
)


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{value}'" for value in values) + ")"


PURPOSE_CHECK = f"purpose IN {_in(ALL_PURPOSES)}"
_CHAT_IN = _in(CHAT_PURPOSES)
_SUBJECTS = "ticket_id, route_outcome_id, signal_id, reply_event_id, broadcast_id"
#: Предмет доставки ровно один; у сообщений бота о чате (подключение, чтение,
#: памятка) предмет — сама привязка.
SUBJECT_CHECK = (
    f"num_nonnulls({_SUBJECTS}) = 1 "
    f"OR (num_nonnulls({_SUBJECTS}) = 0 AND chat_binding_id IS NOT NULL)"
)


class NotificationDelivery(Timestamps, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("outbox_message_id", "recipient_user_id", "channel", name="uq_delivery"),
        # У сообщения в чат получателя-человека нет: одна доставка на пару
        # «запись outbox, чат» (рассылка — одна запись на много чатов).
        Index(
            "uq_delivery_outbox_chat",
            "outbox_message_id",
            "chat_binding_id",
            unique=True,
            postgresql_where=text("recipient_user_id IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        # Одно сообщение бота в чате на заявку (B-06).
        Index(
            "uq_delivery_ticket_chat",
            "ticket_id",
            unique=True,
            postgresql_where=text("purpose = 'chat_ticket_status'"),
        ),
        # Повтор рассылки не дублирует: один пост на чат, одно сообщение на человека.
        Index(
            "uq_delivery_broadcast_chat",
            "broadcast_id",
            "chat_binding_id",
            unique=True,
            postgresql_where=text("purpose = 'broadcast_chat'"),
        ),
        Index(
            "uq_delivery_broadcast_person",
            "broadcast_id",
            "purpose",
            "recipient_user_id",
            unique=True,
            postgresql_where=text("purpose IN ('broadcast_dm','broadcast_staff')"),
        ),
        CheckConstraint("channel = 'max'", name="channel"),
        CheckConstraint(PURPOSE_CHECK, name="purpose"),
        # Предмет доставки: заявка, исход маршрутизации, сигнал, ключ ответа
        # или сообщение УК/платформы; привязка чата — адрес поста в чат.
        CheckConstraint(SUBJECT_CHECK, name="subject"),
        CheckConstraint(
            "purpose <> 'route_action_card' OR route_outcome_id IS NOT NULL",
            name="route_card_subject",
        ),
        CheckConstraint(
            "purpose <> 'signal_alert' OR signal_id IS NOT NULL",
            name="signal_alert_subject",
        ),
        CheckConstraint(
            f"purpose NOT IN {_CHAT_IN} "
            "OR (chat_binding_id IS NOT NULL AND recipient_user_id IS NULL)",
            name="chat_subject",
        ),
        CheckConstraint(
            "purpose <> 'bot_reply' OR (reply_event_id IS NOT NULL "
            "AND recipient_user_id IS NOT NULL)",
            name="bot_reply_subject",
        ),
        CheckConstraint(
            f"purpose NOT IN {_in(BROADCAST_PURPOSES)} OR broadcast_id IS NOT NULL",
            name="broadcast_subject",
        ),
        CheckConstraint(
            "purpose <> 'chat_ticket_status' OR ticket_id IS NOT NULL",
            name="ticket_chat_subject",
        ),
        CheckConstraint(
            f"purpose NOT IN {_in(KEYED_PURPOSES)} "
            "OR (reply_event_id IS NOT NULL AND recipient_user_id IS NOT NULL)",
            name="keyed_subject",
        ),
        # Без получателя — только сообщение в чат или оповещение, которому
        # честно некого оповестить (`skipped` с причиной).
        CheckConstraint(
            f"recipient_user_id IS NOT NULL OR purpose IN {_CHAT_IN} "
            "OR (purpose = 'signal_alert' AND status = 'skipped')",
            name="recipient",
        ),
        CheckConstraint(
            "status IN ('pending','processing','accepted','retry_wait','unknown',"
            "'failed','superseded','skipped')",
            name="status",
        ),
        CheckConstraint("accepted_at IS NULL OR provider_message_id IS NOT NULL", name="accepted"),
        Index("ix_delivery_claim", "status", "next_attempt_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    outbox_message_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_messages.id"))
    # Пусто у сообщения в групповой чат и у оповещения без получателей.
    recipient_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(20), default="max")
    purpose: Mapped[str] = mapped_column(String(40))
    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id"), index=True)
    route_outcome_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("route_outcomes.id", ondelete="CASCADE"), index=True
    )
    signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    chat_binding_id: Mapped[UUID | None] = mapped_column(ForeignKey("chat_bindings.id"), index=True)
    work_attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("work_attempts.id"))
    # Входящее событие, на которое отвечает личный бот (D1), или ключ личного
    # сообщения D3 (`followup:<черновик>`, `digest:<день>:<УК>`, `reception:<запись>`).
    reply_event_id: Mapped[str | None] = mapped_column(String(200))
    # Объявление, рассылка или опрос (D3).
    broadcast_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True
    )
    launch_ref: Mapped[str] = mapped_column(String(64), unique=True)
    destination: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    provider_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    attempt_count: Mapped[int] = mapped_column(default=0)
    retry_count: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    desired_version: Mapped[int]
    applied_version: Mapped[int] = mapped_column(default=0)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaxDestinationLimit(Base):
    """One shared durable send/edit/answer gate per personal MAX destination."""

    __tablename__ = "max_destination_limits"
    destination: Mapped[str] = mapped_column(String(200), primary_key=True)
    next_allowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
