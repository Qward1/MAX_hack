from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base


class HouseRoutingProfile(Base):
    """Регион, муниципалитет и профиль территории дома для Responsibility Router.

    Профиль — администрируемые данные, а не вывод модели. Отсутствие строки
    означает «регион неизвестен»: применяется только федеральный слой
    справочника, территория считается `unknown`.
    """

    __tablename__ = "house_routing_profiles"
    __table_args__ = (
        CheckConstraint(
            "territory_policy IN ('uk', 'municipal', 'mixed', 'unknown')",
            name="territory_policy",
        ),
    )

    house_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("houses.id", ondelete="CASCADE"), primary_key=True
    )
    region_code: Mapped[str | None] = mapped_column(String(20))
    municipality_code: Mapped[str | None] = mapped_column(String(60))
    territory_policy: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
