from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import House, Incident, Report
from domsignal.services.context import OperationContext


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_incident(
        self, *, context: OperationContext, category: str, title: str, description: str
    ) -> Incident:
        incident = Incident(
            house_id=context.house_id,
            management_id=context.management_id.value,
            category=category,
            title=title,
            description=description,
            status="open",
        )
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def create_report(
        self,
        *,
        incident_id: UUID,
        house_id: UUID,
        author_id: UUID,
        category: str,
        description: str,
        classification_mode: str,
        provenance: str,
    ) -> Report:
        report = Report(
            incident_id=incident_id,
            house_id=house_id,
            author_id=author_id,
            category=category,
            description=description,
            classification_mode=classification_mode,
            provenance=provenance,
        )
        self.session.add(report)
        await self.session.flush()
        return report

    async def list_for_house(
        self, context: OperationContext, *, limit: int, offset: int
    ) -> tuple[list[Incident], int]:
        items = list(
            await self.session.scalars(
                select(Incident)
                .where(
                    Incident.house_id == context.house_id,
                    Incident.management_id == context.management_id.value,
                )
                .order_by(Incident.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = await self.session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(
                Incident.house_id == context.house_id,
                Incident.management_id == context.management_id.value,
            )
        )
        return items, int(total or 0)

    async def incident_house_id(self, incident_id: UUID) -> UUID | None:
        # Only routing metadata may be read before resolving access; never content.
        return cast(
            UUID | None,
            await self.session.scalar(select(Incident.house_id).where(Incident.id == incident_id)),
        )

    async def incident(self, incident_id: UUID, *, context: OperationContext) -> Incident | None:
        return cast(
            Incident | None,
            await self.session.scalar(
                select(Incident).where(
                    Incident.id == incident_id,
                    Incident.house_id == context.house_id,
                    Incident.management_id == context.management_id.value,
                )
            ),
        )

    async def house_is_demo(self, house_id: UUID) -> bool:
        return bool(await self.session.scalar(select(House.is_demo).where(House.id == house_id)))

    async def counts(self, incident_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
        if not incident_ids:
            return {}
        rows = await self.session.execute(
            select(Report.incident_id, func.count(), func.count(func.distinct(Report.author_id)))
            .where(Report.incident_id.in_(incident_ids))
            .group_by(Report.incident_id)
        )
        return {incident_id: (reports, participants) for incident_id, reports, participants in rows}

    async def reports(self, incident_id: UUID) -> list[Report]:
        return list(
            await self.session.scalars(
                select(Report).where(Report.incident_id == incident_id).order_by(Report.created_at)
            )
        )
