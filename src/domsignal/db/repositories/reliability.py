from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import IdempotencyRecord, InboxReceipt, Job, OutboxMessage


class ReliabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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

    def add_outbox(self, *, kind: str, aggregate_id: UUID, payload: dict[str, Any]) -> None:
        self.session.add(
            OutboxMessage(kind=kind, aggregate_id=aggregate_id, payload=payload, status="pending")
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

    async def add_job(self, *, kind: str, payload: dict[str, Any], priority: int = 100) -> Job:
        job = Job(kind=kind, payload=payload, status="pending", priority=priority)
        self.session.add(job)
        await self.session.flush()
        return job

    async def claim_job(self, *, now: datetime, lease_seconds: int) -> Job | None:
        job = await self.session.scalar(
            select(Job)
            .where(
                Job.next_attempt_at <= now,
                or_(
                    Job.status == "pending",
                    (Job.status == "leased") & (Job.lease_until < now),
                ),
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
