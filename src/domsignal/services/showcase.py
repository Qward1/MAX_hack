"""Витрина для проверяющих защищена от случайной поломки (F1 §5.5, B-03).

Жюри входит в продукт проверочными аккаунтами (`users.reviewer`) — несколько
человек, иногда одновременно. Разрушающее действие одного из них над витриной
(демо-УК `management_companies.showcase`, её дома и чаты, другие проверочные
аккаунты) сорвало бы сценарий остальным: отключить чат или чтение, снять
открытый доступ, уменьшить квоту, приостановить УК, отозвать управление домом,
снять назначения или заблокировать другой проверочный аккаунт.

Для проверочного аккаунта такие действия над витриной отказаны: HTTP 403 с
кодом `showcase_protected` и понятным текстом. Над своими данными — например
над своей УК «с нуля» — всё работает полностью. Обычные сотрудники и
администраторы платформы ограничений не получают. Признаки задаёт штатный
инструмент `python -m domsignal.tools.showcase`, а не правка базы руками.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import ChatBinding, HouseManagement, ManagementCompany, User
from domsignal.services.errors import AccessDenied

MESSAGE = (
    "Недоступно для проверочного аккаунта: это действие изменило бы витрину, "
    "которую проверяют и другие."
)


class ShowcaseProtected(AccessDenied):
    code = "showcase_protected"
    title = "Showcase is protected"


async def is_reviewer(db: AsyncSession, user_id: UUID) -> bool:
    return bool(await db.scalar(select(User.reviewer).where(User.id == user_id)))


async def house_is_showcase(db: AsyncSession, house_id: UUID) -> bool:
    return bool(
        await db.scalar(
            select(ManagementCompany.showcase)
            .join(HouseManagement, HouseManagement.tenant_id == ManagementCompany.id)
            .where(HouseManagement.house_id == house_id, ManagementCompany.showcase.is_(True))
            .limit(1)
        )
    )


async def guard(
    db: AsyncSession,
    actor_id: UUID,
    *,
    company_id: UUID | None = None,
    house_id: UUID | None = None,
    binding_id: UUID | None = None,
    target_user_id: UUID | None = None,
) -> None:
    """Отказать проверочному аккаунту в разрушающем действии над витриной."""
    if not await is_reviewer(db, actor_id):
        return
    protected = False
    if target_user_id is not None and target_user_id != actor_id:
        protected |= await is_reviewer(db, target_user_id)
    if company_id is not None:
        protected |= bool(
            await db.scalar(
                select(ManagementCompany.showcase).where(ManagementCompany.id == company_id)
            )
        )
    if binding_id is not None:
        house_id = house_id or await db.scalar(
            select(ChatBinding.house_id).where(ChatBinding.id == binding_id)
        )
    if house_id is not None:
        protected |= await house_is_showcase(db, house_id)
    if protected:
        raise ShowcaseProtected(MESSAGE)
