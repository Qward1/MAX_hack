"""Trusted management maintenance within caller-owned transactions, no public UI/API.

All management period changes must lock the physical house before modification.
Report creation holds the matching shared lock until commit. The exclusion
constraint also protects direct SQL and concurrent inserts outside this service.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import HouseManagement
from domsignal.db.repositories.management import ManagementRepository
from domsignal.services.errors import ResourceNotFound


class ManagementService:
    async def create(
        self,
        session: AsyncSession,
        *,
        house_id: UUID,
        tenant_id: UUID,
        valid_from: datetime,
        valid_to: datetime | None = None,
        basis_type: str | None = None,
        basis_reference: str | None = None,
        created_by: UUID | None = None,
        is_demo: bool = False,
    ) -> HouseManagement:
        if valid_from.tzinfo is None or (valid_to is not None and valid_to.tzinfo is None):
            raise ValueError("Management timestamps must be timezone-aware")
        if valid_to is not None and valid_to <= valid_from:
            raise ValueError("Management period must be nonempty")
        repo = ManagementRepository(session)
        if not await repo.lock_house(house_id):
            raise ResourceNotFound("Resource was not found")
        if await repo.overlaps(house_id, valid_from, valid_to):
            raise ValueError("Active management periods must not overlap")
        return await repo.add(
            HouseManagement(
                house_id=house_id,
                tenant_id=tenant_id,
                valid_from=valid_from,
                valid_to=valid_to,
                basis_type=basis_type,
                basis_reference=basis_reference,
                created_by=created_by,
                is_demo=is_demo,
            )
        )

    async def switch(
        self,
        session: AsyncSession,
        *,
        management_id: UUID,
        tenant_id: UUID,
        at: datetime,
        basis_reference: str | None = None,
    ) -> HouseManagement:
        repo = ManagementRepository(session)
        previous = await repo.by_id(management_id)
        if previous is None:
            raise ResourceNotFound("Resource was not found")
        await repo.lock_house(previous.house_id)
        await session.refresh(previous)
        if at.tzinfo is None or at <= previous.valid_from:
            raise ValueError("Switch must follow the start of the previous management")
        if previous.status != "active" or previous.valid_to is not None:
            raise ValueError("Only an open active management can be switched")
        previous.valid_to = at
        await session.flush()
        return await self.create(
            session,
            house_id=previous.house_id,
            tenant_id=tenant_id,
            valid_from=at,
            basis_type="management_switch",
            basis_reference=basis_reference,
            is_demo=previous.is_demo,
        )
