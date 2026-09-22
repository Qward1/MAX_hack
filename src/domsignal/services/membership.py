from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.contracts.identity import HouseAccess, MeResponse
from domsignal.core.access import AccessPolicy
from domsignal.db.models import House, User
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.reliability import authority_lock
from domsignal.services.context import OperationContext, OperationSource, ScopeState, ScopeValue
from domsignal.services.errors import AccessDenied, ResourceNotFound


class MembershipService:
    async def me(
        self, session: AsyncSession, *, user_id: UUID, capabilities: CapabilityFlags
    ) -> MeResponse:
        repo = AccessRepository(session)
        user = await repo.user_by_id(user_id)
        if user is None:
            raise ResourceNotFound("User no longer exists")
        contexts = await self._contexts(session, user_id=user_id)
        return MeResponse(
            id=user.id,
            display_name=user.display_name,
            capabilities=capabilities,
            houses=[
                HouseAccess(
                    id=house.id,
                    name=house.name,
                    address=house.address,
                    is_demo=house.is_demo,
                    role=cast(
                        Literal["resident", "admin", "operator", "responsible"],
                        "admin"
                        if context.organization_role == "company_admin"
                        else context.house_assignment_role or "resident",
                    ),
                )
                for house, context in contexts
            ],
        )

    async def _contexts(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        house_id: UUID | None = None,
        source: OperationSource = "api",
    ) -> list[tuple[House, OperationContext]]:
        rows = await AccessRepository(session).access_bases(
            user_id,
            now=datetime.now(UTC),
            house_id=house_id,
        )
        result = []
        for house, management, organization, assignment, resident in rows:
            org_role = organization.role if organization else None
            assignment_role = assignment.role if assignment and organization else None
            permissions = AccessPolicy.permissions(
                organization_role=org_role,
                assignment_role=assignment_role,
                resident=resident is not None,
            )
            if not permissions:
                continue
            roles = frozenset(
                role
                for role in (
                    org_role,
                    assignment_role,
                    "resident" if resident else None,
                )
                if role
            )
            result.append(
                (
                    house,
                    OperationContext(
                        actor_user_id=user_id,
                        house_id=house.id,
                        source=source,
                        roles=roles,
                        permissions=permissions,
                        tenant_id=ScopeValue(ScopeState.KNOWN, management.tenant_id),
                        management_id=ScopeValue(ScopeState.KNOWN, management.id),
                        organization_role=org_role,
                        house_assignment_role=assignment_role,
                        resident_membership_id=resident.id if resident else None,
                    ),
                )
            )
        return result

    async def contexts_with(
        self, session: AsyncSession, *, user_id: UUID, permission: str
    ) -> list[tuple[House, OperationContext]]:
        """Все дома, где у пользователя есть право, — как «все дома» очереди заявок."""
        return [
            (house, context)
            for house, context in await self._contexts(session, user_id=user_id)
            if permission in context.permissions
        ]

    async def require_house(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        house_id: UUID | None,
        source: OperationSource = "api",
        for_write: bool = False,
    ) -> OperationContext:
        if house_id is None:
            raise AccessDenied("An explicit authorized house context is required")
        if for_write:
            await authority_lock(session)
            await AccessRepository(session).lock_house(house_id)
        contexts = await self._contexts(session, user_id=user_id, house_id=house_id, source=source)
        if not contexts:
            raise ResourceNotFound("Resource was not found")
        return contexts[0][1]

    @staticmethod
    def require_permission(context: OperationContext, permission: str) -> None:
        if permission not in context.permissions:
            raise AccessDenied("This action is not permitted in the selected context")

    async def user_for_external_id(self, session: AsyncSession, *, external_user_id: str) -> User:
        user = await AccessRepository(session).user_by_max_id(external_user_id)
        if user is None:
            raise AccessDenied("The inbound actor is not linked to a known user")
        return user
