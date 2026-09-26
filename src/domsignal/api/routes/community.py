"""Жилищный навигатор и домовое сообщество для жителя (D3).

«Мой дом», «Выполненные работы», объявления и опросы, «Мои обращения»,
запись на приём. Все проверки доступа — в сервисах: житель дома видит свой
дом, посторонний получает маскированный 404.
"""

from __future__ import annotations

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.community import (
    ActivityList,
    AnnouncementList,
    CompletedWorkList,
    CouncilAnnouncementCreate,
    CouncilPollCreate,
    CouncilPublished,
    CouncilView,
    HouseOverview,
    PollView,
    PollVote,
    ProposalCreate,
    ProposalView,
    ReceptionBookingCreate,
    ReceptionOverview,
    ResidentPreferences,
)
from domsignal.services.errors import FieldValidationError

router = APIRouter(prefix="/api/v1", tags=["community"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


@router.get("/houses/{house_id}/overview", response_model=HouseOverview)
async def house_overview(
    house_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> HouseOverview:
    """«Мой дом»: адрес, УК и её контакты «по данным УК», чат, проверенные номера."""
    async with db.begin():
        return await container.navigator.overview(db, actor_id=user.id, house_id=house_id)


@router.get("/houses/{house_id}/completed-works", response_model=CompletedWorkList)
async def completed_works(
    house_id: UUID,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
    days: Annotated[int, Query(description="Период: 30 или 90 суток")] = 30,
    limit: Limit = 20,
    offset: Offset = 0,
) -> CompletedWorkList:
    """Закрытые и возвращённые в работу заявки: отчёт исполнителя и итог проверки."""
    if days not in (30, 90):
        raise FieldValidationError("Период: 30 или 90 суток", field="query.days")
    async with db.begin():
        return await container.navigator.completed_works(
            db,
            actor_id=user.id,
            house_id=house_id,
            days=cast(Literal[30, 90], days),
            limit=limit,
            offset=offset,
        )


@router.get("/houses/{house_id}/announcements", response_model=AnnouncementList)
async def announcements(
    house_id: UUID,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
    limit: Limit = 20,
    offset: Offset = 0,
) -> AnnouncementList:
    async with db.begin():
        return await container.broadcasts.feed(
            db, actor_id=user.id, house_id=house_id, limit=limit, offset=offset
        )


@router.get("/polls/{poll_id}", response_model=PollView)
async def poll(poll_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep) -> PollView:
    async with db.begin():
        return await container.broadcasts.poll_view(db, actor_id=user.id, poll_id=poll_id)


@router.post("/polls/{poll_id}/vote", response_model=PollView)
async def vote(
    poll_id: UUID, payload: PollVote, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> PollView:
    """Один голос на человека; повтор с теми же вариантами ничего не меняет."""
    async with db.begin():
        return await container.broadcasts.vote(
            db, actor_id=user.id, poll_id=poll_id, payload=payload
        )


@router.get("/me/activity", response_model=ActivityList)
async def my_activity(
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
    limit: Limit = 20,
    offset: Offset = 0,
) -> ActivityList:
    """«Мои обращения»: карточки, черновики, свои сообщения и «Меня тоже касается»."""
    async with db.begin():
        return await container.my_activity.list(db, actor_id=user.id, limit=limit, offset=offset)


@router.get("/me/preferences", response_model=ResidentPreferences)
async def preferences(
    user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> ResidentPreferences:
    async with db.begin():
        return await container.broadcasts.preferences(db, actor_id=user.id)


@router.post("/me/preferences", response_model=ResidentPreferences)
async def set_preferences(
    payload: ResidentPreferences, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> ResidentPreferences:
    """«Не получать рассылки» в личные сообщения и возврат рассылок."""
    async with db.begin():
        return await container.broadcasts.set_preferences(db, actor_id=user.id, payload=payload)


@router.get("/houses/{house_id}/reception", response_model=ReceptionOverview)
async def reception(
    house_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> ReceptionOverview:
    async with db.begin():
        return await container.reception.overview(db, actor_id=user.id, house_id=house_id)


@router.post("/houses/{house_id}/reception/bookings", response_model=ReceptionOverview)
async def book(
    house_id: UUID,
    payload: ReceptionBookingCreate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> ReceptionOverview:
    async with db.begin():
        return await container.reception.book(
            db, actor_id=user.id, house_id=house_id, payload=payload
        )


@router.post(
    "/houses/{house_id}/reception/bookings/{booking_id}/cancel", response_model=ReceptionOverview
)
async def cancel_booking(
    house_id: UUID, booking_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> ReceptionOverview:
    async with db.begin():
        return await container.reception.cancel_booking(
            db, actor_id=user.id, house_id=house_id, booking_id=booking_id
        )


# ------------------------------------------------ совет дома и предложения (D4)


@router.get("/houses/{house_id}/council", response_model=CouncilView)
async def council(
    house_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> CouncilView:
    """Член ли житель совета дома; предложения — все для совета, свои для остальных."""
    assert container.council is not None
    async with db.begin():
        return await container.council.resident_view(db, user_id=user.id, house_id=house_id)


@router.post(
    "/houses/{house_id}/proposals",
    response_model=ProposalView,
    status_code=status.HTTP_201_CREATED,
)
async def propose(
    house_id: UUID,
    payload: ProposalCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> ProposalView:
    """«Предложить вопрос»: тему видят совет дома и УК."""
    assert container.council is not None
    async with db.begin():
        return await container.council.propose(
            db, user_id=user.id, house_id=house_id, payload=payload, idempotency_key=key
        )


@router.post(
    "/houses/{house_id}/council/announcements",
    response_model=CouncilPublished,
    status_code=status.HTTP_201_CREATED,
)
async def council_announcement(
    house_id: UUID,
    payload: CouncilAnnouncementCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> CouncilPublished:
    """Объявление от совета дома: чат дома по его настройкам и лента «Объявления»."""
    assert container.council is not None
    async with db.begin():
        return await container.council.publish_announcement(
            db, user_id=user.id, house_id=house_id, payload=payload, idempotency_key=key
        )


@router.post(
    "/houses/{house_id}/council/polls",
    response_model=CouncilPublished,
    status_code=status.HTTP_201_CREATED,
)
async def council_poll(
    house_id: UUID,
    payload: CouncilPollCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> CouncilPublished:
    """Опрос от совета дома; с `proposal_id` — предложение жителя выносится на опрос."""
    assert container.council is not None
    async with db.begin():
        return await container.council.publish_poll(
            db, user_id=user.id, house_id=house_id, payload=payload, idempotency_key=key
        )
