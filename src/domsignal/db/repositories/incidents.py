from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import Incident, Report


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_incident(
        self, *, house_id: UUID, category: str, title: str, description: str
    ) -> Incident:
        incident = Incident(
            house_id=house_id,
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
        self, house_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[Incident], int]:
        items = list(
            await self.session.scalars(
                select(Incident)
                .where(Incident.house_id == house_id)
                .order_by(Incident.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = await self.session.scalar(
            select(func.count()).select_from(Incident).where(Incident.house_id == house_id)
        )
        return items, int(total or 0)

    async def incident(self, incident_id: UUID) -> Incident | None:
        return await self.session.get(Incident, incident_id)

    async def reports(self, incident_id: UUID) -> list[Report]:
        return list(
            await self.session.scalars(
                select(Report).where(Report.incident_id == incident_id).order_by(Report.created_at)
            )
        )
