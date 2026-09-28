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

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bot.chat_provider import MaxChatProvider, MaxProviderError
from domsignal.db.models import (
    ChatBinding,
    EmployeeCredential,
    House,
    HouseManagement,
    ManagementCompany,
    OrganizationMembership,
    User,
)
from domsignal.services import chat_quota
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


async def health(db: AsyncSession, chats: MaxChatProvider | None = None) -> dict[str, bool]:
    """Инварианты витрины для ежедневной самопроверки — только да/нет, без данных.

    Нарушение одного из них сорвёт сценарий проверяющих; как восстановить
    каждый — `docs/RELEASE.md`, «Витрина жюри».
    """
    now = datetime.now(UTC)
    company = await db.scalar(select(ManagementCompany).where(ManagementCompany.showcase.is_(True)))
    if company is None:
        return {"showcase_marked": False}
    checks: dict[str, bool] = {
        "showcase_marked": True,
        "company_active": company.status == "active",
    }
    state = await chat_quota.quota_state(db, company.id)
    checks["quota_covers_chats"] = state.limit is None or state.used <= state.limit
    managements = (
        (
            await db.execute(
                select(HouseManagement.house_id).where(
                    HouseManagement.tenant_id == company.id,
                    HouseManagement.status == "active",
                    HouseManagement.valid_from <= now,
                    or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > now),
                )
            )
        )
        .scalars()
        .all()
    )
    checks["house_managed"] = bool(managements)
    checks["open_access_on"] = bool(managements) and bool(
        await db.scalar(
            select(func.count())
            .select_from(House)
            .where(House.id.in_(managements), House.open_resident_access.is_(True))
        )
    )
    bindings = (
        (
            await db.execute(
                select(ChatBinding).where(
                    ChatBinding.house_id.in_(managements),
                    ChatBinding.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    checks["chat_active"] = bool(bindings)
    checks["chat_reading_on"] = any(b.passive_capture_enabled for b in bindings)
    reviewers = (
        await db.execute(
            select(User.id, EmployeeCredential.revoked_at)
            .join(EmployeeCredential, EmployeeCredential.user_id == User.id)
            .where(User.reviewer.is_(True))
        )
    ).all()
    checks["reviewers_present"] = bool(reviewers)
    # Временная блокировка после неудачных попыток снимается сама за 5 минут;
    # здесь — только отозванный вход.
    checks["reviewers_not_revoked"] = all(revoked is None for _, revoked in reviewers)
    memberships = (
        (
            await db.execute(
                select(OrganizationMembership.status).where(
                    OrganizationMembership.user_id.in_([r[0] for r in reviewers]),
                    OrganizationMembership.tenant_id == company.id,
                )
            )
        )
        .scalars()
        .all()
    )
    checks["reviewer_staff_active"] = all(status == "active" for status in memberships)
    if chats is not None and bindings:
        try:
            info = await chats.get_chat_info(bindings[0].max_chat_id)
            checks["bot_in_chat"] = info.bot_present
        except MaxProviderError:
            checks["bot_in_chat"] = False
    return checks
