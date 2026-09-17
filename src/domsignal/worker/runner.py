from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.worker.handlers import JobHandler


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
        lease_seconds: int = 30,
        max_attempts: int = 5,
    ) -> None:
        self.session_factory = session_factory
        self.handlers = handlers
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    async def claim(self, *, now: datetime | None = None) -> ClaimedJob | None:
        claimed_at = now or datetime.now(UTC)
        async with self.session_factory() as session, session.begin():
            job = await ReliabilityRepository(session).claim_job(
                now=claimed_at, lease_seconds=self.lease_seconds
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
                if job.attempts >= self.max_attempts:
                    await repo.fail_job(
                        job_id=job.id,
                        lease_token=job.lease_token,
                        now=datetime.now(UTC),
                        error_code=type(exc).__name__,
                    )
                else:
                    await repo.retry_job(
                        job_id=job.id,
                        lease_token=job.lease_token,
                        now=datetime.now(UTC),
                        error_code=type(exc).__name__,
                        retry_seconds=min(60, 2**job.attempts),
                    )
            return False
        async with self.session_factory() as session, session.begin():
            return await ReliabilityRepository(session).complete_job(
                job_id=job.id,
                lease_token=job.lease_token,
                now=datetime.now(UTC),
            )

    async def run_once(self) -> bool:
        job = await self.claim()
        if job is None:
            return False
        await self.process(job)
        return True
