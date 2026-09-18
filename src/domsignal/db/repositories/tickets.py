from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.base import Base
from domsignal.db.models import (
    HouseAssignment,
    Incident,
    OrganizationMembership,
    Report,
    ResultObservation,
    Ticket,
    TicketDeadline,
    User,
    WorkAttempt,
)
from domsignal.services.context import OperationContext


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_incident(self, incident_id: UUID) -> None:
        # Aggregate lock also serializes absence/ensure and closed -> reopen.
        await self.session.execute(
            select(Incident.id).where(Incident.id == incident_id).with_for_update()
        )

    async def ticket(self, ticket_id: UUID, context: OperationContext) -> Ticket | None:
        return cast(
            Ticket | None,
            await self.session.scalar(
                select(Ticket)
                .where(
                    Ticket.id == ticket_id,
                    Ticket.house_id == context.house_id,
                    Ticket.management_id == context.management_id.value,
                )
                .execution_options(populate_existing=True)
            ),
        )

    async def latest(self, incident_id: UUID) -> Ticket | None:
        return cast(
            Ticket | None,
            await self.session.scalar(
                select(Ticket)
                .where(Ticket.incident_id == incident_id)
                .order_by(Ticket.number.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            ),
        )

    async def participant(self, ticket: Ticket, actor_id: UUID) -> bool:
        return bool(
            await self.session.scalar(
                select(Report.id)
                .where(
                    Report.incident_id == ticket.incident_id,
                    Report.author_id == actor_id,
                    Report.house_id == ticket.house_id,
                )
                .limit(1)
            )
        )

    def employees(
        self, context: OperationContext, *, responsible_only: bool = False
    ) -> Select[tuple[User]]:
        query = (
            select(User)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .outerjoin(
                HouseAssignment,
                and_(
                    HouseAssignment.user_id == User.id,
                    HouseAssignment.management_id == context.management_id.value,
                    HouseAssignment.status == "active",
                ),
            )
            .where(
                OrganizationMembership.tenant_id == context.tenant_id.value,
                OrganizationMembership.status == "active",
                or_(
                    OrganizationMembership.role == "company_admin",
                    and_(
                        OrganizationMembership.role == "operator",
                        HouseAssignment.role.in_(["responsible", "operator"]),
                    ),
                ),
            )
        )
        if responsible_only:
            query = query.where(HouseAssignment.role == "responsible")
        return query.order_by(User.id)

    async def available(self, context: OperationContext, user_id: UUID | None) -> bool:
        return user_id is not None and bool(
            await self.session.scalar(self.employees(context).where(User.id == user_id).limit(1))
        )

    async def latest_attempt(self, ticket: Ticket) -> WorkAttempt | None:
        if ticket.latest_attempt_id is None:
            return None
        return await self.session.get(WorkAttempt, ticket.latest_attempt_id)

    async def current_observations(self, attempt_id: UUID) -> list[ResultObservation]:
        return list(
            await self.session.scalars(
                select(ResultObservation)
                .where(ResultObservation.attempt_id == attempt_id)
                .distinct(ResultObservation.actor_id)
                .order_by(ResultObservation.actor_id, ResultObservation.revision.desc())
            )
        )

    async def deadlines(self, ticket_id: UUID) -> list[TicketDeadline]:
        return list(
            await self.session.scalars(
                select(TicketDeadline)
                .where(TicketDeadline.ticket_id == ticket_id)
                .distinct(TicketDeadline.kind, TicketDeadline.basis)
                .order_by(TicketDeadline.kind, TicketDeadline.basis, TicketDeadline.revision.desc())
            )
        )

    async def page[T: Base](
        self, query: Select[tuple[T]], *, limit: int, offset: int
    ) -> tuple[list[T], int]:
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        items = list(await self.session.scalars(query.limit(limit).offset(offset)))
        return items, total or 0

    @staticmethod
    def changed(ticket: Ticket) -> None:
        ticket.version += 1
        ticket.updated_at = datetime.now(UTC)
