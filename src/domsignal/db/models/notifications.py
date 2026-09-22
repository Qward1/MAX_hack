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
CHAT_PURPOSES = ("chat_reading_notice", "chat_safety_memo")

#: Оповещение оператора о критическом сигнале.
SIGNAL_ALERT_PURPOSE = "signal_alert"

PURPOSE_CHECK = (
    "purpose IN ('ticket_accepted','work_verification','route_action_card',"
    "'signal_alert','chat_reading_notice','chat_safety_memo')"
)


class NotificationDelivery(Timestamps, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("outbox_message_id", "recipient_user_id", "channel", name="uq_delivery"),
        # У сообщения в чат получателя-человека нет: одна доставка на запись outbox.
        Index(
            "uq_delivery_outbox_without_recipient",
            "outbox_message_id",
            unique=True,
            postgresql_where=text("recipient_user_id IS NULL"),
        ),
        CheckConstraint("channel = 'max'", name="channel"),
        CheckConstraint(PURPOSE_CHECK, name="purpose"),
        # Предмет доставки ровно один: заявка, исход маршрутизации, сигнал
        # или привязка чата. Внешний маршрут заявку не создаёт, сообщение в чат
        # относится к привязке, оповещение оператора — к сигналу.
        CheckConstraint(
            "num_nonnulls(ticket_id, route_outcome_id, signal_id, chat_binding_id) = 1",
            name="subject",
        ),
        CheckConstraint(
            "purpose <> 'route_action_card' OR route_outcome_id IS NOT NULL",
            name="route_card_subject",
        ),
        CheckConstraint(
            "purpose <> 'signal_alert' OR signal_id IS NOT NULL",
            name="signal_alert_subject",
        ),
        CheckConstraint(
            "purpose NOT IN ('chat_reading_notice','chat_safety_memo') "
            "OR (chat_binding_id IS NOT NULL AND recipient_user_id IS NULL)",
            name="chat_subject",
        ),
        # Без получателя — только сообщение в чат или оповещение, которому
        # честно некого оповестить (`skipped` с причиной).
        CheckConstraint(
            "recipient_user_id IS NOT NULL "
            "OR purpose IN ('chat_reading_notice','chat_safety_memo') "
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
    chat_binding_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat_bindings.id"), index=True
    )
    work_attempt_id: Mapped[UUID | None] = mapped_column(ForeignKey("work_attempts.id"))
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
