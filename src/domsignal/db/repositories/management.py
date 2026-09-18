from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import House, HouseManagement


class ManagementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_house(self, house_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(House.id).where(House.id == house_id).with_for_update()
            )
        ) is not None

    async def overlaps(
        self,
        house_id: UUID,
        valid_from: datetime,
        valid_to: datetime | None,
    ) -> bool:
        statement = select(HouseManagement.id).where(
            HouseManagement.house_id == house_id,
            HouseManagement.status == "active",
            or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > valid_from),
        )
        if valid_to is not None:
            statement = statement.where(HouseManagement.valid_from < valid_to)
        return (await self.session.scalar(statement.limit(1))) is not None

    async def by_id(self, management_id: UUID) -> HouseManagement | None:
        return await self.session.get(HouseManagement, management_id)

    async def add(self, management: HouseManagement) -> HouseManagement:
        self.session.add(management)
        await self.session.flush()
        return management
