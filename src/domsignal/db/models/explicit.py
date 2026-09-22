"""Явный путь: приём свободного текста, исход маршрутизации и черновик обращения.

`explicit_intakes` — запись приёма одной реплики `/report <свободный текст>`.
Её атомарно захватывает либо разбор моделью, либо сторожевая задача правил:
кто первым перевёл `pending` в `claimed`, тот и обрабатывает. Это страховка
явного пути, а не кеш: остановленный AI-пул задерживает результат, но не
отменяет его.

`route_outcomes` хранит исход маршрутизации и для внешних маршрутов, где
заявка УК не создаётся. Без него внешний маршрут не оставлял бы следа.

`appeal_drafts` — текст обращения, который житель правит и отправляет **сам**.
Отметка подачи остаётся отметкой жителя и никогда не становится
подтверждением внешней регистрации.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

#: Состояния записи приёма явного пути.
INTAKE_STATES = ("pending", "claimed", "done", "failed")

#: Чем закончился разбор одной реплики.
INTAKE_RESULT_KINDS = ("ticket", "external_route", "needs_clarification", "ignored")

#: Решение маршрутизации, сохранённое для метрик и карточки жителя.
ROUTE_DECISIONS = ("ticket", "external", "needs_clarification")


class ExplicitIntake(Base):
    """Приём одной реплики `/report <свободный текст>`.

    Первичный ключ — `event_id` вебхука: повторная доставка того же события не
    создаёт второй записи и второго результата.
    """

    __tablename__ = "explicit_intakes"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'claimed', 'done', 'failed')",
            name="state",
        ),
        CheckConstraint(
            "result_kind IS NULL OR result_kind IN "
            "('ticket', 'external_route', 'needs_clarification', 'ignored')",
            name="result_kind",
        ),
        CheckConstraint(
            "(state = 'pending') = (claimed_at IS NULL)",
            name="claimed_at",
        ),
        Index("ix_explicit_intakes_state", "state"),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(200), index=True)
    chat_binding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_bindings.id"))
    binding_version: Mapped[int] = mapped_column(Integer)
    external_user_id: Mapped[str] = mapped_column(String(200))
    # Текст реплики нужен для разбора и для черновика; он живёт здесь, а не в
    # `inbox_receipts`, который умышленно не хранит содержимое сообщений.
    text: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Деловая переформулировка от модели, прошедшая guard `no_new_facts`.
    # Живёт рядом с исходной репликой, а не в `reports.analysis`: провенанс
    # разбора остаётся без текста, а черновик обращения получает абзац
    # описания, который правит человек. Текст модели не попадает ни в одно
    # сообщение от имени системы.
    clean_description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(100))
    result_kind: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RouteOutcome(Base):
    """Исход маршрутизации явного пути (и будущих пассивных сигналов).

    Для внешнего маршрута заявка УК не создаётся, поэтому `report_id` пуст.
    Запись остаётся единственным следом такого разбора.
    """

    __tablename__ = "route_outcomes"
    __table_args__ = (
        CheckConstraint("source IN ('group_report', 'form')", name="source"),
        CheckConstraint(
            "decision IN ('ticket', 'external', 'needs_clarification')",
            name="decision",
        ),
        Index("ix_route_outcomes_house_created", "house_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(20))
    subtype: Mapped[str] = mapped_column(String(100))
    location_scope: Mapped[str] = mapped_column(String(30))
    route_type: Mapped[str] = mapped_column(String(30))
    # Организация и канал — идентификаторы справочника, не внешние ключи БД.
    organization_id: Mapped[str | None] = mapped_column(String(100))
    channel_id: Mapped[str | None] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(30))
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL")
    )
    # Откуда пришёл исход: черновик обращения берёт отсюда исходный текст
    # жителя и проверенную переформулировку. У формы записи приёма нет.
    intake_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("explicit_intakes.event_id", ondelete="SET NULL")
    )
    # Автор исхода. Карточку маршрута по ссылке `r_…` и по `?card=` видит
    # только он: исход — это ответ конкретному человеку, а не запись дома.
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # Слова жителя из формы. Для чатового пути текст остаётся в записи приёма,
    # поэтому здесь он пуст; без него черновик внешнего обращения из формы
    # остался бы без описания проблемы.
    submitted_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AppealDraft(Timestamps, Base):
    """Черновик обращения: текст готовит продукт, отправляет человек.

    Один черновик на один исход маршрутизации — требование канала ПОС «одна
    проблема — одно обращение».
    """

    __tablename__ = "appeal_drafts"
    __table_args__ = (
        UniqueConstraint("route_outcome_id", "author_id", name="uq_appeal_draft_outcome_author"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "filed_at IS NOT NULL OR filed_reference IS NULL",
            name="filed_reference",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), index=True
    )
    route_outcome_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("route_outcomes.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # `true`, когда абзац описания пришёл от модели и прошёл guard no_new_facts.
    ai_assisted: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Отметка жителя «я отправил сам». Не подтверждение внешней регистрации.
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filed_reference: Mapped[str | None] = mapped_column(String(200))


class AiCallBudget(Base):
    """Дневной счётчик вызовов модели, общий для всех реплик воркера.

    Счётчик в PostgreSQL, а не в памяти процесса: атомарный инкремент — то
    единственное, что не даёт параллельным репликам перебрать дневной лимит.
    Строка со `scope_key = ''` — общий дневной счёт, остальные — доли областей.
    """

    __tablename__ = "ai_call_budget"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


#: Значение `scope_key` для общего дневного счёта.
GLOBAL_BUDGET_SCOPE = ""
