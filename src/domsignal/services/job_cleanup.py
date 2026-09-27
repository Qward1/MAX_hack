"""Очистка очереди задач (D5, аудит v2 §4.2).

Таблица `jobs` растёт с каждым вебхуком, окном и доставкой: при тысячах чатов
это сотни тысяч строк в сутки. Выполненные задачи старше 14 дней и упавшие
старше 30 дней удаляются пачками — короткими транзакциями, чтобы не держать
блокировки и не раздувать WAL. Ожидающие и взятые в работу задачи не
трогаются никогда.

Задача периодическая: ставится при старте операционного воркера и
переставляет себя сама (`RescheduleJob`). Сроки хранения остальных растущих
таблиц описаны в docs/SCALING.md и этой задачей не чистятся.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.services.errors import RescheduleJob

logger = logging.getLogger(__name__)

TICK_JOB = "jobs.cleanup"
#: Приоритет ниже рабочих задач: очистка никогда не обгоняет доставку.
TICK_PRIORITY = 95
TICK_INTERVAL = timedelta(hours=1)
SUCCEEDED_RETENTION = timedelta(days=14)
FAILED_RETENTION = timedelta(days=30)
BATCH_SIZE = 2000
#: За один запуск не больше стольких пачек: остаток уйдёт через час.
MAX_BATCHES = 50

_DELETE = text(
    """
    DELETE FROM jobs WHERE id IN (
        SELECT id FROM jobs
        WHERE status = :status AND completed_at < :cutoff
        ORDER BY completed_at
        LIMIT :batch
        FOR UPDATE SKIP LOCKED
    )
    """
)

#: F1: счётчики токенов модели по минутам нужны только текущей минуте.
_DELETE_TOKEN_MINUTES = text("DELETE FROM ai_token_minutes WHERE minute < :cutoff")
TOKEN_MINUTES_RETENTION = timedelta(hours=1)


@dataclass(frozen=True)
class CleanupResult:
    succeeded: int
    failed: int
    batches: int


class JobCleanup:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        batch_size: int = BATCH_SIZE,
        max_batches: int = MAX_BATCHES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.sessions = sessions
        self.batch_size = batch_size
        self.max_batches = max_batches
        self.clock = clock or (lambda: datetime.now(UTC))

    async def purge(self, *, now: datetime | None = None) -> CleanupResult:
        """Удалить пачками старые выполненные и упавшие задачи."""
        at = now or self.clock()
        removed = {"succeeded": 0, "failed": 0}
        batches = 0
        for status, retention in (
            ("succeeded", SUCCEEDED_RETENTION),
            ("failed", FAILED_RETENTION),
        ):
            while batches < self.max_batches:
                async with self.sessions() as session, session.begin():
                    result = await session.execute(
                        _DELETE,
                        {"status": status, "cutoff": at - retention, "batch": self.batch_size},
                    )
                count = int(getattr(result, "rowcount", 0) or 0)
                batches += 1
                removed[status] += count
                if count < self.batch_size:
                    break
        async with self.sessions() as session, session.begin():
            await session.execute(
                _DELETE_TOKEN_MINUTES, {"cutoff": at - TOKEN_MINUTES_RETENTION}
            )
        outcome = CleanupResult(
            succeeded=removed["succeeded"], failed=removed["failed"], batches=batches
        )
        logger.info(
            "jobs_cleanup",
            extra={
                "jobs_succeeded_removed": outcome.succeeded,
                "jobs_failed_removed": outcome.failed,
                "batches": outcome.batches,
            },
        )
        return outcome

    async def tick(self, payload: dict[str, Any], *, now: datetime | None = None) -> None:
        del payload
        at = now or self.clock()
        await self.purge(now=at)
        raise RescheduleJob(at + TICK_INTERVAL)


__all__ = [
    "FAILED_RETENTION",
    "SUCCEEDED_RETENTION",
    "TICK_JOB",
    "TICK_PRIORITY",
    "CleanupResult",
    "JobCleanup",
]
