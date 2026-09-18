from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import (
    House,
    HouseAssignment,
    HouseManagement,
    ManagementCompany,
    OrganizationMembership,
    ResidentMembership,
    User,
)


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_by_id(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def user_by_demo_alias(self, alias: str) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(select(User).where(User.demo_alias == alias)),
        )

    async def user_by_max_id(self, max_user_id: str) -> User | None:
        return cast(
            User | None,
            await self.session.scalar(select(User).where(User.max_user_id == max_user_id)),
        )

    async def create_max_user(self, max_user_id: str, display_name: str) -> User:
        user = User(max_user_id=max_user_id, display_name=display_name)
        self.session.add(user)
        await self.session.flush()
        return user

    async def lock_house(self, house_id: UUID) -> None:
        # Writers and management switching share this lock protocol. A management
        # switch cannot race a report into the previous management after commit.
        await self.session.execute(
            select(House.id).where(House.id == house_id).with_for_update(read=True)
        )

    async def access_bases(
        self,
        user_id: UUID,
        *,
        now: datetime,
        house_id: UUID | None = None,
    ) -> list[
        tuple[
            House,
            HouseManagement,
            OrganizationMembership | None,
            HouseAssignment | None,
            ResidentMembership | None,
        ]
    ]:
        statement = (
            select(
                House, HouseManagement, OrganizationMembership, HouseAssignment, ResidentMembership
            )
            .join(HouseManagement, HouseManagement.house_id == House.id)
            .join(ManagementCompany, ManagementCompany.id == HouseManagement.tenant_id)
            .outerjoin(
                OrganizationMembership,
                and_(
                    OrganizationMembership.tenant_id == HouseManagement.tenant_id,
                    OrganizationMembership.user_id == user_id,
                    OrganizationMembership.status == "active",
                ),
            )
            .outerjoin(
                HouseAssignment,
                and_(
                    HouseAssignment.management_id == HouseManagement.id,
                    HouseAssignment.user_id == user_id,
                    HouseAssignment.status == "active",
                ),
            )
            .outerjoin(
                ResidentMembership,
                and_(
                    ResidentMembership.house_id == House.id,
                    ResidentMembership.user_id == user_id,
                    ResidentMembership.status == "active",
                    or_(
                        ResidentMembership.expires_at.is_(None), ResidentMembership.expires_at > now
                    ),
                ),
            )
            .where(
                ManagementCompany.status == "active",
                HouseManagement.status == "active",
                HouseManagement.valid_from <= now,
                or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > now),
                or_(OrganizationMembership.id.is_not(None), ResidentMembership.id.is_not(None)),
            )
            .order_by(House.address)
        )
        if house_id is not None:
            statement = statement.where(House.id == house_id)
        return list((await self.session.execute(statement)).tuples())
