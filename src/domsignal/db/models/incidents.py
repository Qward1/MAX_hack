from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("id", "management_id", "house_id", name="uq_incident_scope"),
        ForeignKeyConstraint(
            ["management_id", "house_id"],
            ["house_managements.id", "house_managements.house_id"],
            name="fk_incident_management_house",
            ondelete="RESTRICT",
        ),
        Index("ix_incident_house_status", "house_id", "status"),
        Index("ix_incident_management_status", "management_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    management_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True)
    # Место и «с какого времени» заполняются только значениями, у которых есть
    # дословная цитата из реплики жителя. Из свободного текста не извлекаются.
    location_entrance: Mapped[str | None] = mapped_column(String(50))
    location_floor: Mapped[str | None] = mapped_column(String(50))
    location_label: Mapped[str | None] = mapped_column(String(200))
    observed_since: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), index=True
    )
    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    classification_mode: Mapped[str] = mapped_column(String(30), default="manual")
    provenance: Mapped[str] = mapped_column(String(30), default="api")
    # Происхождение разбора: режим, состояния, версии, подтип, территория,
    # флаги, число отброшенных полей, идентификатор модели. **Без текста
    # реплики** — он уже лежит в `description`, дублировать его незачем.
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
