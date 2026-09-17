from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.jobs import InboundAccepted, NormalizedInboundEvent
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.errors import AccessDenied
from domsignal.services.membership import MembershipService


class InboundService:
    async def accept(
        self, session: AsyncSession, *, event: NormalizedInboundEvent, actor_id: UUID
    ) -> InboundAccepted:
        async with session.begin():
            memberships = MembershipService()
            actor = await memberships.user_for_external_id(
                session, external_user_id=event.external_user_id
            )
            if actor.id != actor_id:
                raise AccessDenied("The replay identity does not match the authenticated actor")
            await memberships.require_house(
                session, user_id=actor_id, house_id=event.house_id, source="max_replay"
            )
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
