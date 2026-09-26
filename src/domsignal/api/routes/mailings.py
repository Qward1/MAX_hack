"""Кабинет D3: профиль УК, рассылки и опросы, настройки чата, сводка, приём.

Сообщения УК и платформы — один механизм (BOT-VOICE-HUMAN-2026-09-27):
черновик → предпросмотр → подтверждение → отправка сразу или по расписанию.
Сообщения платформы создаёт только суперадмин (вход с паролем и MFA).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status
from sqlalchemy import select

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.api.routes.administration import Employee
from domsignal.contracts.community import (
    BroadcastCommand,
    BroadcastConfirm,
    BroadcastContentEdit,
    BroadcastCreate,
    BroadcastHouseOption,
    BroadcastList,
    BroadcastPreview,
    BroadcastUpdate,
    BroadcastView,
    ChatSettingsUpdate,
    ChatSettingsView,
    CompanyProfileUpdate,
    CompanyProfileView,
    HouseFactsUpdate,
    HouseFactsView,
    PlatformNoticeList,
    ReceptionSlotCreate,
    ReceptionSlotView,
    StaffSettings,
    StaffSettingsUpdate,
)
from domsignal.db.models import HouseRoutingProfile
from domsignal.services.onboarding import require_platform

router = APIRouter(prefix="/api/v1", tags=["mailings"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


# ------------------------------------------------------------- профиль УК


@router.get("/companies/{company_id}/profile", response_model=CompanyProfileView)
async def company_profile(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> CompanyProfileView:
    async with db.begin():
        return await container.navigator.profile(db, actor_id=user.id, company_id=company_id)


@router.post("/companies/{company_id}/profile", response_model=CompanyProfileView)
async def update_company_profile(
    company_id: UUID,
    payload: CompanyProfileUpdate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> CompanyProfileView:
    """Контакты УК для жителей — «по данным УК», с датой обновления."""
    async with db.begin():
        return await container.navigator.update_profile(
            db, actor_id=user.id, company_id=company_id, payload=payload
        )


@router.post("/companies/{company_id}/houses/{house_id}/facts", response_model=HouseFactsView)
async def update_house_facts(
    company_id: UUID,
    house_id: UUID,
    payload: HouseFactsUpdate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> HouseFactsView:
    async with db.begin():
        return await container.navigator.update_house_facts(
            db, actor_id=user.id, company_id=company_id, house_id=house_id, payload=payload
        )


# --------------------------------------------------------------- рассылки УК


@router.get("/companies/{company_id}/broadcast-houses", response_model=list[BroadcastHouseOption])
async def broadcast_houses(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> list[BroadcastHouseOption]:
    """Дома, которые сотрудник может выбрать в аудитории."""
    async with db.begin():
        return await container.broadcasts.house_options(db, actor_id=user.id, company_id=company_id)


@router.get("/companies/{company_id}/broadcasts", response_model=BroadcastList)
async def company_broadcasts(
    company_id: UUID,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
    limit: Limit = 20,
    offset: Offset = 0,
) -> BroadcastList:
    async with db.begin():
        return await container.broadcasts.list_company(
            db, actor_id=user.id, company_id=company_id, limit=limit, offset=offset
        )


@router.post(
    "/companies/{company_id}/broadcasts",
    response_model=BroadcastView,
    status_code=status.HTTP_201_CREATED,
)
async def create_company_broadcast(
    company_id: UUID,
    payload: BroadcastCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    """Черновик объявления, рассылки или опроса. Отправки ещё нет."""
    async with db.begin():
        return await container.broadcasts.create(
            db, actor_id=user.id, company_id=company_id, payload=payload, idempotency_key=key
        )


# ----------------------------------------------------------- сообщения платформы


@router.get("/platform/broadcasts", response_model=BroadcastList)
async def platform_broadcasts(
    user: Employee, db: DbDep, container: ContainerDep, limit: Limit = 20, offset: Offset = 0
) -> BroadcastList:
    async with db.begin():
        return await container.broadcasts.list_platform(
            db, actor_id=user.id, limit=limit, offset=offset
        )


@router.post(
    "/platform/broadcasts", response_model=BroadcastView, status_code=status.HTTP_201_CREATED
)
async def create_platform_broadcast(
    payload: BroadcastCreate, key: Key, user: Employee, db: DbDep, container: ContainerDep
) -> BroadcastView:
    async with db.begin():
        return await container.broadcasts.create(
            db, actor_id=user.id, company_id=None, payload=payload, idempotency_key=key
        )


@router.get("/platform/broadcast-regions", response_model=list[str])
async def broadcast_regions(user: Employee, db: DbDep) -> list[str]:
    """Коды регионов домов для выбора аудитории сообщения платформы."""
    async with db.begin():
        await require_platform(db, user.id)
        rows = await db.scalars(
            select(HouseRoutingProfile.region_code)
            .where(HouseRoutingProfile.region_code.is_not(None))
            .distinct()
            .order_by(HouseRoutingProfile.region_code)
        )
        return [row for row in rows if row]


# ------------------------------------------------------------ общие команды


@router.get("/broadcasts/{broadcast_id}", response_model=BroadcastView)
async def broadcast(
    broadcast_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> BroadcastView:
    async with db.begin():
        return await container.broadcasts.detail(db, actor_id=user.id, broadcast_id=broadcast_id)


@router.get("/broadcasts/{broadcast_id}/preview", response_model=BroadcastPreview)
async def preview(
    broadcast_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> BroadcastPreview:
    """Сколько получателей по каждому каналу — без отправки."""
    async with db.begin():
        return await container.broadcasts.preview(db, actor_id=user.id, broadcast_id=broadcast_id)


@router.post("/broadcasts/{broadcast_id}/update", response_model=BroadcastView)
async def update_draft(
    broadcast_id: UUID,
    payload: BroadcastUpdate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    async with db.begin():
        return await container.broadcasts.update_draft(
            db, actor_id=user.id, broadcast_id=broadcast_id, payload=payload
        )


@router.post("/broadcasts/{broadcast_id}/confirm", response_model=BroadcastView)
async def confirm(
    broadcast_id: UUID,
    payload: BroadcastConfirm,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    """Подтверждение: отправить сейчас или в указанное время."""
    async with db.begin():
        return await container.broadcasts.confirm(
            db, actor_id=user.id, broadcast_id=broadcast_id, payload=payload
        )


@router.post("/broadcasts/{broadcast_id}/cancel", response_model=BroadcastView)
async def cancel(
    broadcast_id: UUID,
    payload: BroadcastCommand,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    async with db.begin():
        return await container.broadcasts.cancel(
            db, actor_id=user.id, broadcast_id=broadcast_id, payload=payload
        )


@router.post("/broadcasts/{broadcast_id}/edit", response_model=BroadcastView)
async def edit_content(
    broadcast_id: UUID,
    payload: BroadcastContentEdit,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    """Правка отправленного: тот же пост в чате правится."""
    async with db.begin():
        return await container.broadcasts.edit_content(
            db, actor_id=user.id, broadcast_id=broadcast_id, payload=payload
        )


@router.post("/broadcasts/{broadcast_id}/retract", response_model=BroadcastView)
async def retract(
    broadcast_id: UUID,
    payload: BroadcastCommand,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    """Удалить отправленное: пост в чате правится на «Сообщение удалено автором»."""
    async with db.begin():
        return await container.broadcasts.retract(
            db, actor_id=user.id, broadcast_id=broadcast_id, payload=payload
        )


@router.post("/broadcasts/{broadcast_id}/close-poll", response_model=BroadcastView)
async def close_poll(
    broadcast_id: UUID,
    payload: BroadcastCommand,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> BroadcastView:
    async with db.begin():
        return await container.broadcasts.close_poll(
            db, actor_id=user.id, broadcast_id=broadcast_id, payload=payload
        )


# ---------------------------------------------------- уведомления и настройки


@router.get("/companies/{company_id}/platform-notices", response_model=PlatformNoticeList)
async def platform_notices(
    company_id: UUID,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
    limit: Limit = 20,
    offset: Offset = 0,
) -> PlatformNoticeList:
    """Лента уведомлений платформы в кабинете УК."""
    async with db.begin():
        return await container.broadcasts.platform_notices(
            db, actor_id=user.id, company_id=company_id, limit=limit, offset=offset
        )


@router.get("/companies/{company_id}/me/settings", response_model=StaffSettings)
async def staff_settings(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> StaffSettings:
    async with db.begin():
        return await container.digest.settings(db, actor_id=user.id, company_id=company_id)


@router.post("/companies/{company_id}/me/settings", response_model=StaffSettings)
async def update_staff_settings(
    company_id: UUID,
    payload: StaffSettingsUpdate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> StaffSettings:
    """Ежедневная сводка в 09:00 по местному времени УК в личку MAX — включает сам сотрудник."""
    async with db.begin():
        return await container.digest.update_settings(
            db, actor_id=user.id, company_id=company_id, payload=payload
        )


@router.get("/chat-bindings/{binding_id}/settings", response_model=ChatSettingsView)
async def chat_settings(
    binding_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> ChatSettingsView:
    async with db.begin():
        return await container.chat_settings.view(db, binding_id=binding_id, actor_id=user.id)


@router.post("/chat-bindings/{binding_id}/settings", response_model=ChatSettingsView)
async def update_chat_settings(
    binding_id: UUID,
    payload: ChatSettingsUpdate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> ChatSettingsView:
    """Что бот публикует по решению человека и тихие часы; история с автором."""
    async with db.begin():
        return await container.chat_settings.update(
            db, binding_id=binding_id, actor_id=user.id, payload=payload
        )


# ------------------------------------------------------------ запись на приём


@router.get("/companies/{company_id}/reception-slots", response_model=list[ReceptionSlotView])
async def reception_slots(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> list[ReceptionSlotView]:
    async with db.begin():
        return await container.reception.list_slots(db, actor_id=user.id, company_id=company_id)


@router.post(
    "/companies/{company_id}/reception-slots",
    response_model=ReceptionSlotView,
    status_code=status.HTTP_201_CREATED,
)
async def create_reception_slot(
    company_id: UUID,
    payload: ReceptionSlotCreate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> ReceptionSlotView:
    async with db.begin():
        return await container.reception.create_slot(
            db, actor_id=user.id, company_id=company_id, payload=payload
        )


@router.post(
    "/companies/{company_id}/reception-slots/{slot_id}/cancel", response_model=ReceptionSlotView
)
async def cancel_reception_slot(
    company_id: UUID, slot_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> ReceptionSlotView:
    async with db.begin():
        return await container.reception.cancel_slot(
            db, actor_id=user.id, company_id=company_id, slot_id=slot_id
        )
