from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.identity import HouseAccess, MeResponse
from domsignal.db.models import User
from domsignal.db.repositories.access import AccessRepository
from domsignal.services.errors import AccessDenied, ResourceNotFound


class MembershipService:
    async def me(self, session: AsyncSession, *, user_id: UUID) -> MeResponse:
        repo = AccessRepository(session)
        user = await repo.user_by_id(user_id)
        if user is None:
            raise ResourceNotFound("User no longer exists")
        memberships = await repo.memberships(user_id)
        return MeResponse(
            id=user.id,
            display_name=user.display_name,
            houses=[
                HouseAccess(
                    id=house.id,
                    name=house.name,
                    address=house.address,
                    role=cast(Literal["resident", "admin"], membership.role),
                    is_demo=house.is_demo,
                )
                for membership, house in memberships
            ],
        )

    async def require_house(self, session: AsyncSession, *, user_id: UUID, house_id: UUID) -> None:
        membership = await AccessRepository(session).membership(user_id, house_id)
        if membership is None:
            raise AccessDenied("The authenticated user is not a member of this house")

    async def user_for_external_id(self, session: AsyncSession, *, external_user_id: str) -> User:
        user = await AccessRepository(session).user_by_max_id(external_user_id)
        if user is None:
            raise AccessDenied("The inbound actor is not linked to a known user")
        return user
