"""Периодические задачи D3: постановка при старте воркера.

Задача переставляет себя сама (`RescheduleJob`), поэтому в очереди всегда
одна живая запись вида; повторный старт воркера второй не ставит.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.db.models import Job
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.db.repositories.reliability import ReliabilityRepository


async def ensure_periodic(
    sessions: async_sessionmaker[AsyncSession],
    kind: str,
    *,
    priority: int = 90,
    first_at: datetime | None = None,
) -> bool:
    """Поставить задачу вида `kind`, если живой записи нет. `True` — поставлена."""
    async with sessions() as session, session.begin():
        await ChatRepository(session).lock(f"periodic:{kind}")
        alive = await session.scalar(
            select(Job.id).where(Job.kind == kind, Job.status.in_(("pending", "leased"))).limit(1)
        )
        if alive is not None:
            return False
        job = await ReliabilityRepository(session).add_job(kind=kind, payload={}, priority=priority)
        if first_at is not None:
            job.next_attempt_at = first_at
        return True


__all__ = ["ensure_periodic"]
