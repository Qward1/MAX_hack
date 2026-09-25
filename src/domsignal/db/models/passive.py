"""Пассивное чтение подключённого чата: буфер, окна и сигналы.

`chat_messages` — временный буфер сырых реплик. Реплика живёт не дольше срока
хранения (`PASSIVE_BUFFER_HOURS`, не больше 72 часов) независимо от того,
разобрана она или нет. MAX не присылает боту ни правок, ни удалений сообщений,
поэтому удаление реплики в чате до продукта не доходит: единственная защита —
срок хранения.

`conversation_windows` — состояние окна переписки. Политика нарезки живёт в
ядре (`domsignal.ai.WindowPolicy`, `split_stream`); здесь только факты: когда
окно открыто, сколько в нём реплик, почему и когда оно закрыто и чем кончился
разбор.

`signals` — сигнал из окна: что, где, насколько похоже на проблему дома и куда
ведёт маршрут. Сигнал не является ни `Report`, ни `Incident`, ни `Ticket`:
заявку из него создаёт только оператор (очередь сигналов P5), и его решение
записывается вместе с автором, временем и причиной. После срока хранения буфера
от разговора остаются только цитаты сигнала (не больше трёх, с псевдонимом
автора и временем) и счётчики реплик и уникальных авторов.
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
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base

#: Состояния окна: открыто → закрыто → разбирается → разобрано.
WINDOW_STATES = ("open", "closed", "analyzing", "done")

#: Почему окно закрылось. Названия повторяют условия политики ядра.
WINDOW_CLOSE_REASONS = ("silence", "max_lines", "max_age", "danger")

#: Статусы сигнала. `in_review` — оператор выбрал маршрут, но ещё не решил.
SIGNAL_STATUSES = ("new", "in_review", "converted", "routed_external", "dismissed")

#: Открытые статусы: сигнал ещё может собирать ветку и ждёт решения оператора.
OPEN_SIGNAL_STATUSES = ("new", "in_review")

#: Решённые статусы: сигнал больше не решается повторно.
DECIDED_SIGNAL_STATUSES = ("converted", "routed_external", "dismissed")

#: Почему оператор закрыл сигнал. Причина — данные для оценки качества (P6).
DISMISS_REASONS = ("not_a_problem", "duplicate", "resolved", "out_of_scope", "spam")

#: Кто разобрал окно: AI-пул или сторож правил в операционном пуле.
WINDOW_ANALYZERS = ("ai", "fallback")

SIGNAL_STRENGTHS = ("critical", "strong", "medium", "weak", "filtered")
SIGNAL_DISPOSITIONS = ("inbox", "audit_pool")
SIGNAL_SOURCES = ("rules", "model", "rules+model")


class ChatAuthorAlias(Base):
    """Устойчивый псевдоним автора в пределах дома: «A», «B», … «AA».

    Связь псевдонима с человеком остаётся только здесь и никуда не уходит:
    провайдер получает свои псевдонимы по окну, оператор видит «Житель A».
    Номер не переиспользуется, поэтому один псевдоним в цитатах сигнала
    всегда означает одного человека.
    """

    __tablename__ = "chat_author_aliases"
    __table_args__ = (
        UniqueConstraint("house_id", "alias_index", name="uq_chat_author_alias_index"),
        CheckConstraint("alias_index >= 0", name="alias_index"),
    )

    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), primary_key=True
    )
    external_user_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    alias_index: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatMessage(Base):
    """Сырая реплика подключённого чата во временном буфере."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        # Повтор вебхука не создаёт второй строки.
        UniqueConstraint("max_chat_id", "mid", name="uq_chat_messages_chat_mid"),
        Index("ix_chat_messages_window_sent", "window_id", "sent_at"),
        Index("ix_chat_messages_binding_sent", "chat_binding_id", "sent_at"),
        Index("ix_chat_messages_received", "received_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    max_chat_id: Mapped[str] = mapped_column(String(200))
    mid: Mapped[str] = mapped_column(String(200))
    chat_binding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_bindings.id"))
    binding_version: Mapped[int] = mapped_column(Integer)
    external_user_id: Mapped[str] = mapped_column(String(200))
    author_ref: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    text_truncated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    reply_to_mid: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    window_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_windows.id", ondelete="SET NULL")
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationWindow(Base):
    """Окно переписки одной привязки чата."""

    __tablename__ = "conversation_windows"
    __table_args__ = (
        CheckConstraint(
            "state IN ('open', 'closed', 'analyzing', 'done')",
            name="state",
        ),
        CheckConstraint(
            "close_reason IS NULL OR close_reason IN ('silence', 'max_lines', 'max_age', 'danger')",
            name="close_reason",
        ),
        CheckConstraint("(state = 'open') = (closed_at IS NULL)", name="closed_at"),
        CheckConstraint("line_count >= 0", name="line_count"),
        CheckConstraint(
            "analyzed_by IS NULL OR analyzed_by IN ('ai', 'fallback')", name="analyzed_by"
        ),
        # Одно открытое окно на привязку.
        Index(
            "uq_conversation_window_open",
            "chat_binding_id",
            unique=True,
            postgresql_where=text("state = 'open'"),
        ),
        Index("ix_conversation_windows_house_created", "house_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"))
    chat_binding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_bindings.id"))
    binding_version: Mapped[int] = mapped_column(Integer)
    max_chat_id: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    close_reason: Mapped[str | None] = mapped_column(String(20))
    has_danger: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    line_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    first_line_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_line_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Отложенная задача проверки тишины. Одна на окно: тик переносит сам себя.
    tick_job_id: Mapped[uuid.UUID | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(100))
    analysis_mode: Mapped[str | None] = mapped_column(String(20))
    execution_state: Mapped[str | None] = mapped_column(String(40))
    # Кто разобрал окно: `ai` или `fallback` (сторож правил). Второй не трогает
    # уже разобранное окно: захват идёт только из `closed`.
    analyzed_by: Mapped[str | None] = mapped_column(String(20))
    # Происхождение разбора без текста: режим, версии, задержка, стоимость.
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Signal(Base):
    """Сигнал из окна переписки: наблюдение, а не заявка и не обращение."""

    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'in_review', 'converted', 'routed_external', 'dismissed')",
            name="status",
        ),
        CheckConstraint(
            "strength IN ('critical', 'strong', 'medium', 'weak', 'filtered')",
            name="strength",
        ),
        CheckConstraint("disposition IN ('inbox', 'audit_pool')", name="disposition"),
        CheckConstraint("source IN ('rules', 'model', 'rules+model')", name="source"),
        CheckConstraint(
            "report_count >= 0 AND author_count >= 0 AND author_count <= report_count",
            name="counters",
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "(status IN ('converted', 'routed_external', 'dismissed')) = (decided_at IS NOT NULL)",
            name="decided",
        ),
        CheckConstraint(
            "decision_reason IS NULL OR decision_reason IN "
            "('not_a_problem', 'duplicate', 'resolved', 'out_of_scope', 'spam')",
            name="decision_reason",
        ),
        Index("ix_signals_house_status_seen", "house_id", "status", "last_seen_at"),
        Index("ix_signals_house_dedupe", "house_id", "dedupe_key", "status"),
        Index("ix_signals_incident", "incident_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"))
    chat_binding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_bindings.id"))
    # Окно, из которого сигнал родился. Следующие окна ветки видны в `signal_lines`.
    window_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_windows.id", ondelete="SET NULL")
    )
    subtype: Mapped[str] = mapped_column(String(100))
    product_category: Mapped[str] = mapped_column(String(50))
    object_label: Mapped[str] = mapped_column(String(200))
    # Место и время — только значение вместе с дословной цитатой и репликой.
    entrance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    floor: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    since: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    location_scope: Mapped[str] = mapped_column(String(30))
    location: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    facets: Mapped[dict[str, Any]] = mapped_column(JSONB)
    strength: Mapped[str] = mapped_column(String(20))
    strength_reason: Mapped[str] = mapped_column(String(60))
    disposition: Mapped[str] = mapped_column(String(20))
    audit_reason: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20))
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Виды, источник, доказательства и понижения опасности.
    emergency: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dedupe_key: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new")
    report_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    author_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    route_outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "route_outcomes.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_signals_route_outcome_id_route_outcomes",
        )
    )
    # Версия для решений оператора: каждое изменение сигнала её увеличивает,
    # решение с устаревшей версией получает 409 `stale_version`.
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Решение оператора: кто, когда, почему. Решённый сигнал не решается снова.
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(30))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    # Заявка, которую создал или к которой присоединил сигнал оператор.
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL")
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SignalQuote(Base):
    """Дословная цитата реплики сигнала. Не больше трёх на сигнал."""

    __tablename__ = "signal_quotes"
    __table_args__ = (UniqueConstraint("signal_id", "line_mid", name="uq_signal_quote_line"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    signal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    line_mid: Mapped[str] = mapped_column(String(200))
    author_ref: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SignalLine(Base):
    """Роль реплики окна и её связь с сигналом. Без текста реплики.

    Строка без сигнала — роль реплики, не относящейся ни к одной проблеме; она
    удаляется вместе с буфером. Строки сигнала — основание его счётчиков.
    """

    __tablename__ = "signal_lines"
    __table_args__ = (
        UniqueConstraint("window_id", "line_mid", "signal_id", name="uq_signal_line"),
        Index("ix_signal_lines_signal", "signal_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    window_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation_windows.id", ondelete="CASCADE")
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE")
    )
    line_mid: Mapped[str] = mapped_column(String(200))
    author_ref: Mapped[str] = mapped_column(String(16))
    role: Mapped[str | None] = mapped_column(String(30))
    link_certainty: Mapped[str | None] = mapped_column(String(10))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SignalEvent(Base):
    """Событие аудита сигнала или окна: как есть из ядра и события продукта."""

    __tablename__ = "signal_events"
    __table_args__ = (Index("ix_signal_events_house_created", "house_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    house_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("houses.id", ondelete="CASCADE"))
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), index=True
    )
    window_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_windows.id", ondelete="SET NULL"), index=True
    )
    line_mid: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(60))
    details: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Версии таксономии, правил, схемы, промпта и модели того разбора.
    versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Автор решения оператора. У событий ядра и продукта автора нет.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
