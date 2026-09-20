from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import House, HouseManagement, HouseRoutingProfile


class RoutingRepository:
    """Чтение контекста дома для Responsibility Router."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def house(self, house_id: UUID) -> House | None:
        return await self.session.get(House, house_id)

    async def profile(self, house_id: UUID) -> HouseRoutingProfile | None:
        return await self.session.get(HouseRoutingProfile, house_id)

    async def current_management(self, house_id: UUID, at: datetime) -> HouseManagement | None:
        """Только управление, действующее на указанный момент."""
        found: HouseManagement | None = await self.session.scalar(
            select(HouseManagement)
            .where(
                HouseManagement.house_id == house_id,
                HouseManagement.status == "active",
                HouseManagement.valid_from <= at,
                or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > at),
            )
            .order_by(HouseManagement.valid_from.desc())
            .limit(1)
        )
        return found

    async def upsert_profile(
        self,
        *,
        house_id: UUID,
        region_code: str | None,
        municipality_code: str | None,
        territory_policy: str,
        updated_by: UUID | None,
    ) -> HouseRoutingProfile:
        profile = await self.profile(house_id)
        if profile is None:
            profile = HouseRoutingProfile(house_id=house_id)
            self.session.add(profile)
        profile.region_code = region_code
        profile.municipality_code = municipality_code
        profile.territory_policy = territory_policy
        profile.updated_by = updated_by
        await self.session.flush()
        return profile
