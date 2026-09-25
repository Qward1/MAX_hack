"""Жилищный навигатор и домовое сообщество (срез D3).

* `CompanyProfile` — контакты УК «по данным УК» с датой обновления: их
  заполняет администратор УК, продукт их не проверяет и так и подписывает.
* `Broadcast` — сообщение от УК или платформы: объявление, рассылка или
  опрос. Один механизм: черновик → предпросмотр → подтверждение → отправка
  сразу или по расписанию; отмена до отправки. Доставка — существующие
  outbox и `NotificationDelivery` (BOT-VOICE-HUMAN-2026-09-27).
* `BroadcastHouse`/`BroadcastCompany` — аудитория, разрешённая в момент
  рассылки: по ней строится лента «Объявления» и уведомления платформы.
* `Poll`, `PollOption`, `PollBallot`, `PollChoice` — предварительный опрос:
  один голос на человека, итоги — только числа.
* `ReceptionSlot`, `ReceptionBooking` — запись на приём в УК.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

BROADCAST_ORIGINS = ("company", "platform")
BROADCAST_KINDS = ("announcement", "mailing", "poll")
BROADCAST_TOPICS = ("outage", "works", "meeting", "other")
BROADCAST_STATUSES = ("draft", "scheduled", "sent", "cancelled")


def _in(values: tuple[str, ...]) -> str:
    return "(" + ",".join(f"'{value}'" for value in values) + ")"


class CompanyProfile(Base):
    """Контакты УК для жителей. Все поля — «по данным УК», без проверки продуктом."""

    __tablename__ = "company_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="CASCADE"), primary_key=True
    )
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    #: Аварийно-диспетчерская служба УК.
    dispatcher_phone: Mapped[str | None] = mapped_column(String(40))
    office_hours: Mapped[str | None] = mapped_column(String(300))
    reception_hours: Mapped[str | None] = mapped_column(String(300))
    website: Mapped[str | None] = mapped_column(String(300))
    office_address: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Broadcast(Timestamps, Base):
    """Объявление, рассылка или опрос. Автор — сотрудник УК или суперадмин."""

    __tablename__ = "broadcasts"
    __table_args__ = (
        CheckConstraint(f"origin IN {_in(BROADCAST_ORIGINS)}", name="origin"),
        CheckConstraint(f"kind IN {_in(BROADCAST_KINDS)}", name="kind"),
        CheckConstraint(f"topic IS NULL OR topic IN {_in(BROADCAST_TOPICS)}", name="topic"),
        CheckConstraint(f"status IN {_in(BROADCAST_STATUSES)}", name="status"),
        CheckConstraint("(origin = 'company') = (tenant_id IS NOT NULL)", name="origin_tenant"),
        CheckConstraint("char_length(body) <= 3000", name="body_length"),
        CheckConstraint("version >= 1 AND content_version >= 1", name="version"),
        CheckConstraint(
            "status <> 'scheduled' OR (scheduled_at IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="scheduled",
        ),
        Index("ix_broadcasts_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    origin: Mapped[str] = mapped_column(String(20))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("management_companies.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(20))
    topic: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    #: Аудитория, как её выбрал автор: режим, дома/УК, фильтры.
    audience: Mapped[dict[str, Any]] = mapped_column(JSONB)
    #: Каналы: `chat`, `dm`, `feed`, `staff`.
    channels: Mapped[list[str]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    #: Отправленное сообщение удалено автором: пост в чате правится на пометку.
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retracted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Версия для команд (ожидаемая версия, 409 при расхождении).
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    #: Версия содержимого поста: растёт при правке, удалении, голосе и закрытии опроса.
    content_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class BroadcastHouse(Base):
    """Дом аудитории, разрешённой при отправке: лента «Объявления» жителей."""

    __tablename__ = "broadcast_houses"

    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), primary_key=True
    )
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class BroadcastCompany(Base):
    """УК аудитории сообщения платформы: лента уведомлений в кабинете."""

    __tablename__ = "broadcast_companies"

    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Poll(Base):
    """Предварительный опрос. Не является решением общего собрания собственников."""

    __tablename__ = "polls"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    broadcast_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="CASCADE"), unique=True
    )
    question: Mapped[str] = mapped_column(String(300))
    multiple: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PollOption(Base):
    __tablename__ = "poll_options"
    __table_args__ = (
        UniqueConstraint("poll_id", "position", name="uq_poll_option_position"),
        CheckConstraint("position BETWEEN 1 AND 10", name="position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    poll_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("polls.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger)
    label: Mapped[str] = mapped_column(String(100))


class PollBallot(Base):
    """Голос человека: один на опрос, до закрытия его можно изменить."""

    __tablename__ = "poll_ballots"

    poll_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("polls.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PollChoice(Base):
    __tablename__ = "poll_choices"
    __table_args__ = (
        ForeignKeyConstraint(
            ["poll_id", "user_id"],
            ["poll_ballots.poll_id", "poll_ballots.user_id"],
            name="fk_poll_choice_ballot",
            ondelete="CASCADE",
        ),
    )

    poll_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    option_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("poll_options.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class ReceptionSlot(Timestamps, Base):
    """Время приёма в УК: дата, время, вместимость."""

    __tablename__ = "reception_slots"
    __table_args__ = (
        CheckConstraint("capacity BETWEEN 1 AND 50", name="capacity"),
        CheckConstraint("duration_minutes BETWEEN 5 AND 240", name="duration"),
        CheckConstraint("status IN ('open','cancelled')", name="status"),
        Index("ix_reception_slots_tenant_start", "tenant_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("management_companies.id", ondelete="CASCADE")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, default=30, server_default="30")
    capacity: Mapped[int] = mapped_column(SmallInteger)
    place: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class ReceptionBooking(Timestamps, Base):
    """Запись жителя на приём: тема и дом. Отмена оставляет запись историей."""

    __tablename__ = "reception_bookings"
    __table_args__ = (
        CheckConstraint("status IN ('booked','cancelled')", name="status"),
        Index(
            "uq_reception_booking_active",
            "slot_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reception_slots.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="booked", server_default="booked")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
