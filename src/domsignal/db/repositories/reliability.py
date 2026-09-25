from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import IdempotencyRecord, InboxReceipt, Job, OutboxMessage
from domsignal.worker.pools import AI_KIND_PREFIX, WorkerPool


def stable_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ReliabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_idempotency(self, *, actor_id: UUID, action: str, key: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"domsignal:command:{actor_id}:{action}:{key}"},
        )

    async def idempotency_record(
        self, *, actor_id: UUID, action: str, key: str
    ) -> IdempotencyRecord | None:
        return cast(
            IdempotencyRecord | None,
            await self.session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_id == actor_id,
                    IdempotencyRecord.action == action,
                    IdempotencyRecord.key == key,
                )
            ),
        )

    def add_idempotency(
        self,
        *,
        actor_id: UUID,
        action: str,
        key: str,
        request_hash: str,
        response_status: int,
        response_body: dict[str, Any],
    ) -> None:
        self.session.add(
            IdempotencyRecord(
                actor_id=actor_id,
                action=action,
                key=key,
                request_hash=request_hash,
                response_status=response_status,
                response_body=response_body,
            )
        )

    def add_outbox(
        self,
        *,
        kind: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        dedupe_key: str | None = None,
    ) -> None:
        self.session.add(
            OutboxMessage(
                kind=kind,
                aggregate_id=aggregate_id,
                payload=payload,
                status="pending",
                dedupe_key=dedupe_key,
            )
        )

    async def inbox(self, event_id: str) -> InboxReceipt | None:
        return await self.session.get(InboxReceipt, event_id)

    async def add_inbox_and_job(
        self,
        *,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        job_kind: str,
        priority: int = 100,
    ) -> Job:
        self.session.add(InboxReceipt(event_id=event_id, event_type=event_type, payload=payload))
        job = Job(kind=job_kind, payload=payload, status="pending", priority=priority)
        self.session.add(job)
        await self.session.flush()
        return job

    async def add_job(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        priority: int = 100,
        delay_seconds: int = 0,
        now: datetime | None = None,
    ) -> Job:
        """Поставить задачу. `delay_seconds` отодвигает первую попытку."""
        job = Job(kind=kind, payload=payload, status="pending", priority=priority)
        if delay_seconds:
            job.next_attempt_at = (now or datetime.now(UTC)) + timedelta(seconds=delay_seconds)
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim_job(
        self, *, now: datetime, lease_seconds: int, pool: WorkerPool | None = None
    ) -> Job | None:
        """Взять задачу своего пула. Без пула видны все виды (как раньше).

        Фильтр строится по виду задачи, а не по составу обработчиков: иначе
        задача незнакомого вида не досталась бы ни одному пулу и осталась бы в
        очереди навсегда вместо честного отказа.
        """
        ai_kind = Job.kind.startswith(AI_KIND_PREFIX, autoescape=True)
        job = await self.session.scalar(
            select(Job)
            .where(
                Job.next_attempt_at <= now,
                or_(
                    Job.status == "pending",
                    (Job.status == "leased") & (Job.lease_until < now),
                ),
                *(() if pool is None else (ai_kind if pool == "ai" else ~ai_kind,)),
            )
            .order_by(Job.priority, Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "leased"
        job.attempts += 1
        job.lease_token = uuid4()
        job.lease_until = now + timedelta(seconds=lease_seconds)
        await self.session.flush()
        return job

    async def complete_job(self, *, job_id: UUID, lease_token: UUID, now: datetime) -> bool:
        job = await self.session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "leased" or job.lease_token != lease_token:
            return False
        job.status = "succeeded"
        job.completed_at = now
        job.lease_until = None
        return True

    async def retry_job(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        now: datetime,
        error_code: str,
        retry_seconds: int,
    ) -> bool:
        job = await self.session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "leased" or job.lease_token != lease_token:
            return False
        job.status = "pending"
        job.next_attempt_at = now + timedelta(seconds=retry_seconds)
        job.lease_until = None
        job.lease_token = None
        job.last_error_code = error_code[:100]
        return True

    async def fail_job(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        now: datetime,
        error_code: str,
    ) -> bool:
        job = await self.session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status != "leased" or job.lease_token != lease_token:
            return False
        job.status = "failed"
        job.completed_at = now
        job.lease_until = None
        job.lease_token = None
        job.last_error_code = error_code[:100]
        return True

    async def defer_job(self, *, job_id: UUID, lease_token: UUID, until: datetime) -> None:
        job = await self.session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is not None and job.lease_token == lease_token and job.status == "leased":
            job.status = "pending"
            job.next_attempt_at = until
            job.attempts = max(0, job.attempts - 1)
            job.lease_until = None
            job.lease_token = None


async def authority_lock(db: AsyncSession, *, exclusive: bool = False) -> None:
    """MVP authority changes exclusive; protected writes shared, before house/credential locks."""
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    await db.execute(text(f"SELECT {function}(hashtextextended('domsignal:authority', 0))"))
