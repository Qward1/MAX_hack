from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.messaging import MessagingError
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.errors import RescheduleJob
from domsignal.services.notifications import DeferredNotification, TicketNotificationHandler
from domsignal.worker.handlers import JobHandler
from domsignal.worker.pools import DEFAULT_POOL, OPERATIONAL_LEASE_SECONDS, WorkerPool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    kind: str
    payload: dict[str, Any]
    lease_token: UUID
    attempts: int


class WorkerRunner:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        handlers: dict[str, JobHandler],
        lease_seconds: int = OPERATIONAL_LEASE_SECONDS,
        max_attempts: int = 5,
        notifications: TicketNotificationHandler | None = None,
        pool: WorkerPool = DEFAULT_POOL,
    ) -> None:
        self.session_factory = session_factory
        self.handlers = handlers
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.pool = pool
        # Доставка уведомлений остаётся только в операционном пуле: отказ
        # провайдера модели не должен задерживать сообщения жителям.
        self.notifications = notifications if pool == DEFAULT_POOL else None

    async def claim(self, *, now: datetime | None = None) -> ClaimedJob | None:
        claimed_at = now or datetime.now(UTC)
        async with self.session_factory() as session, session.begin():
            job = await ReliabilityRepository(session).claim_job(
                now=claimed_at, lease_seconds=self.lease_seconds, pool=self.pool
            )
            if job is None or job.lease_token is None:
                return None
            return ClaimedJob(
                id=job.id,
                kind=job.kind,
                payload=job.payload,
                lease_token=job.lease_token,
                attempts=job.attempts,
            )

    async def process(self, job: ClaimedJob) -> bool:
        handler = self.handlers.get(job.kind)
        try:
            if handler is None:
                raise LookupError(f"unknown_job_kind:{job.kind}")
            await handler(job.payload)
        except Exception as exc:
            async with self.session_factory() as session, session.begin():
                repo = ReliabilityRepository(session)
                code = exc.code if isinstance(exc, MessagingError) else type(exc).__name__
                if isinstance(exc, DeferredNotification | RescheduleJob):
                    # Перенос себя не расходует попытку: тик окна ждёт тишины,
                    # очистка буфера повторяется по расписанию.
                    await repo.defer_job(
                        job_id=job.id,
                        lease_token=job.lease_token,
                        until=exc.until,
                    )
                elif job.attempts >= self.max_attempts or (
                    isinstance(exc, MessagingError) and exc.kind == "permanent"
                ):
                    await repo.fail_job(
                        job_id=job.id,
                        lease_token=job.lease_token,
                        now=datetime.now(UTC),
                        error_code=code,
                    )
                else:
                    await repo.retry_job(
                        job_id=job.id,
                        lease_token=job.lease_token,
                        now=datetime.now(UTC),
                        error_code=code,
                        retry_seconds=max(
                            min(60, 2**job.attempts),
                            int(
                                (exc.retry_after or 0) if isinstance(exc, MessagingError) else 0,
                            ),
                        ),
                    )
            return False
        async with self.session_factory() as session, session.begin():
            return await ReliabilityRepository(session).complete_job(
                job_id=job.id,
                lease_token=job.lease_token,
                now=datetime.now(UTC),
            )

    async def run_once(self, *, now: datetime | None = None) -> bool:
        """Один шаг воркера. `now` задаётся только проверками времени."""
        handled = False
        if self.notifications:
            try:
                handled = await self.notifications.consume_once()
                handled = await self.notifications.consume_route_cards_once() or handled
                handled = await self.notifications.consume_chat_messages_once() or handled
                handled = await self.notifications.consume_ticket_chat_once() or handled
                handled = await self.notifications.consume_bot_replies_once() or handled
                handled = await self.notifications.deliver_once(now=now) or handled
            except Exception as exc:
                # A rolled-back consumer or leased operation remains recoverable. Do not
                # leak SQL parameters/upstream content, or stop unrelated durable jobs.
                logger.error("notification_worker_error", extra={"error_type": type(exc).__name__})
        job = await self.claim(now=now)
        if job is None:
            return handled
        await self.process(job)
        return True


#: Пауза цикла, когда работы нет.
IDLE_SECONDS = 1.0


async def run_loops(
    runner: WorkerRunner,
    *,
    concurrency: int,
    stop: asyncio.Event,
    idle_seconds: float = IDLE_SECONDS,
) -> None:
    """N параллельных циклов «claim → обработка» одного процесса (D5).

    Циклы делят только настройки воркера: каждая операция открывает свою
    сессию БД, задачу забирает `FOR UPDATE SKIP LOCKED` с арендой — двойного
    разбора нет ни между циклами, ни между процессами. Семафор провайдера и
    бюджет модели живут в общем анализаторе процесса.

    Остановка: после `stop` новые задачи не забираются, начатые доходят до
    конца. Ошибка цикла вне обработчика (например, БД недоступна) завершает
    процесс, как и раньше, — перезапуск делает Compose.
    """
    if concurrency < 1:
        raise ValueError("worker concurrency must be at least 1")

    async def loop() -> None:
        while not stop.is_set():
            if await runner.run_once():
                continue
            try:
                await asyncio.wait_for(stop.wait(), idle_seconds)
            except TimeoutError:
                pass

    async with asyncio.TaskGroup() as group:
        for _ in range(concurrency):
            group.create_task(loop())
