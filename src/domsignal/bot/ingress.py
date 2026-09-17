from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.jobs import InboundAccepted, NormalizedInboundEvent
from domsignal.db.repositories.reliability import ReliabilityRepository


class InboundService:
    async def accept(
        self, session: AsyncSession, *, event: NormalizedInboundEvent
    ) -> InboundAccepted:
        async with session.begin():
            repo = ReliabilityRepository(session)
            if await repo.inbox(event.event_id) is not None:
                return InboundAccepted(
                    event_id=event.event_id,
                    accepted=True,
                    duplicate=True,
                    job_id=None,
                )
            job = await repo.add_inbox_and_job(
                event_id=event.event_id,
                event_type=event.event_type,
                payload=event.model_dump(mode="json"),
                job_kind="inbound.report",
                priority=50,
            )
        return InboundAccepted(
            event_id=event.event_id,
            accepted=True,
            duplicate=False,
            job_id=job.id,
        )
