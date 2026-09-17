from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import House, HouseMembership, User


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

    async def memberships(self, user_id: UUID) -> list[tuple[HouseMembership, House]]:
        result = await self.session.execute(
            select(HouseMembership, House)
            .join(House, House.id == HouseMembership.house_id)
            .where(HouseMembership.user_id == user_id)
            .order_by(House.address)
        )
        return list(result.tuples())

    async def membership(self, user_id: UUID, house_id: UUID) -> HouseMembership | None:
        return cast(
            HouseMembership | None,
            await self.session.scalar(
                select(HouseMembership).where(
                    HouseMembership.user_id == user_id,
                    HouseMembership.house_id == house_id,
                )
            ),
        )
