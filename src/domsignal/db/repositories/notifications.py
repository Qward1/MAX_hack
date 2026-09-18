from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import MaxDestinationLimit, NotificationDelivery, OutboxMessage, Report


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def intent(self) -> OutboxMessage | None:
        return cast(
            OutboxMessage | None,
            await self.session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.kind == "ticket.notification_intent.v1",
                    OutboxMessage.status == "pending",
                )
                .order_by(OutboxMessage.created_at, OutboxMessage.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )

    async def recipients(self, incident_id: UUID) -> list[UUID]:
        return list(
            await self.session.scalars(
                select(Report.author_id).where(Report.incident_id == incident_id).distinct()
            )
        )

    async def affected(self, ticket_id: UUID) -> list[NotificationDelivery]:
        return list(
            await self.session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.ticket_id == ticket_id)
                .order_by(NotificationDelivery.id)
                .with_for_update()
            )
        )

    async def by_ref(self, ref: str) -> NotificationDelivery | None:
        return cast(
            NotificationDelivery | None,
            await self.session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.launch_ref == ref)
            ),
        )

    async def due(self, now: datetime) -> NotificationDelivery | None:
        d = NotificationDelivery
        return cast(
            NotificationDelivery | None,
            await self.session.scalar(
                select(d)
                .where(
                    or_(d.next_attempt_at.is_(None), d.next_attempt_at <= now),
                    or_(
                        d.status.in_(["pending", "retry_wait"]),
                        and_(d.status == "accepted", d.desired_version > d.applied_version),
                        and_(d.status == "processing", d.lease_until <= now),
                    ),
                )
                .order_by(d.updated_at, d.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )

    async def reserve_destination(
        self,
        destination: str,
        token: UUID,
        now: datetime,
    ) -> datetime | None:
        await self.session.execute(
            insert(MaxDestinationLimit)
            .values(
                destination=destination,
                next_allowed_at=now,
            )
            .on_conflict_do_nothing(index_elements=["destination"])
        )
        gate = await self.session.scalar(
            select(MaxDestinationLimit)
            .where(
                MaxDestinationLimit.destination == destination,
            )
            .with_for_update()
        )
        assert gate is not None
        if gate.lease_until and gate.lease_until > now:
            return gate.lease_until
        if gate.next_allowed_at > now:
            return gate.next_allowed_at
        gate.lease_token = token
        gate.lease_until = now + timedelta(seconds=90)
        gate.next_allowed_at = now + timedelta(milliseconds=500)
        return None

    async def release_destination(self, destination: str, token: UUID, now: datetime) -> None:
        gate = await self.session.scalar(
            select(MaxDestinationLimit)
            .where(
                MaxDestinationLimit.destination == destination,
            )
            .with_for_update()
        )
        if gate and gate.lease_token == token:
            gate.lease_token = None
            gate.lease_until = None
            gate.next_allowed_at = max(gate.next_allowed_at, now + timedelta(milliseconds=500))
