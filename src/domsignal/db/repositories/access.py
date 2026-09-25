from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import (
    ChatBinding,
    House,
    HouseAssignment,
    HouseManagement,
    ManagementCompany,
    MAXChat,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.db.models.access import CHAT_MEMBER_SOURCE, EVENT_SOURCES, OPEN_ACCESS_SOURCE
from domsignal.db.repositories.reliability import authority_lock


def _basis_holds() -> ColumnElement[bool]:
    """Основание членства по-прежнему в силе.

    `chat_member` — привязка той же версии активна, бот в чате, управление
    дома то же, что у привязки: отзыв, приостановка и `bot_removed` снимают
    доступ сразу, без записи в членство. `open_access` — переключатель дома
    включён. Прежние источники проверяются как раньше.
    """
    binding_ok = (
        select(ChatBinding.id)
        .join(MAXChat, MAXChat.max_chat_id == ChatBinding.max_chat_id)
        .where(
            ChatBinding.id == ResidentMembership.chat_binding_id,
            ChatBinding.house_id == ResidentMembership.house_id,
            ChatBinding.management_id == HouseManagement.id,
            ChatBinding.status == "active",
            ChatBinding.binding_version == ResidentMembership.binding_version,
            MAXChat.bot_present.is_(True),
            MAXChat.binding_version == ResidentMembership.binding_version,
        )
        .exists()
    )
    return or_(
        ResidentMembership.source.not_in(EVENT_SOURCES),
        and_(ResidentMembership.source == OPEN_ACCESS_SOURCE, House.open_resident_access.is_(True)),
        and_(ResidentMembership.source == CHAT_MEMBER_SOURCE, binding_ok),
    )


class AccessRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resident_ids(
        self, house_ids: list[UUID], *, now: datetime
    ) -> list[tuple[UUID, UUID]]:
        """Жители домов с действующим основанием: пары «пользователь, дом».

        То же основание, что у политики доступа, кроме суточного срока
        проверки участия в чате: рассылка в личку идёт участникам, которых
        чат не исключил (`user_removed`), даже если mini app они давно не
        открывали. Доступа к данным дома это не даёт.
        """
        if not house_ids:
            return []
        rows = await self.session.execute(
            select(ResidentMembership.user_id, ResidentMembership.house_id)
            .join(House, House.id == ResidentMembership.house_id)
            .join(HouseManagement, HouseManagement.house_id == House.id)
            .join(ManagementCompany, ManagementCompany.id == HouseManagement.tenant_id)
            .where(
                ResidentMembership.house_id.in_(house_ids),
                ResidentMembership.status == "active",
                ManagementCompany.status == "active",
                HouseManagement.status == "active",
                HouseManagement.valid_from <= now,
                or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > now),
                _basis_holds(),
            )
            .distinct()
            .order_by(ResidentMembership.user_id, ResidentMembership.house_id)
        )
        return [(row[0], row[1]) for row in rows]

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
        await authority_lock(self.session)
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
                    _basis_holds(),
                ),
            )
            .where(
                ManagementCompany.status == "active",
                HouseManagement.status == "active",
                HouseManagement.valid_from <= now,
                or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > now),
                or_(OrganizationMembership.id.is_not(None), ResidentMembership.id.is_not(None)),
            )
            .order_by(House.address, House.id, ResidentMembership.created_at)
        )
        if house_id is not None:
            statement = statement.where(House.id == house_id)
        rows = list((await self.session.execute(statement)).tuples())
        # У жителя может быть несколько действующих оснований в одном доме
        # (чат и открытый доступ, два чата дома) — дом в ответе один.
        unique: dict[UUID, int] = {}
        result: list[
            tuple[
                House,
                HouseManagement,
                OrganizationMembership | None,
                HouseAssignment | None,
                ResidentMembership | None,
            ]
        ] = []
        for row in rows:
            index = unique.get(row[0].id)
            if index is None:
                unique[row[0].id] = len(result)
                result.append(row)
            elif result[index][4] is None and row[4] is not None:
                result[index] = row
        return result
