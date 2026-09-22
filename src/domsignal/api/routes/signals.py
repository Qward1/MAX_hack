"""Очередь сигналов оператора (P5): список, деталь и одно решение на сигнал."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.signals import (
    SignalChooseRoute,
    SignalCreateTicket,
    SignalDismiss,
    SignalJoin,
    SignalList,
    SignalMutation,
    SignalRouteExternal,
    SignalStatus,
    SignalStrength,
    SignalView,
)

router = APIRouter(prefix="/api/v1", tags=["signals"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


@router.get("/signals", response_model=SignalList)
async def signals(
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    house_id: UUID | None = None,
    status: Annotated[list[SignalStatus] | None, Query()] = None,
    strength: Annotated[list[SignalStrength] | None, Query()] = None,
    limit: Limit = 20,
    offset: Offset = 0,
) -> SignalList:
    """Только Signal Inbox: критические сверху, внутри силы — свежие первыми.

    Без `house_id` — все дома, доступные сотруднику. `status` и `strength`
    можно повторять; пусто — без фильтра.
    """
    return await container.signal_inbox.queue(
        session,
        actor_id=current_user.id,
        house_id=house_id,
        statuses=status or [],
        strengths=strength or [],
        limit=limit,
        offset=offset,
    )


@router.get("/signals/{signal_id}", response_model=SignalView)
async def signal_detail(
    signal_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> SignalView:
    return await container.signal_inbox.detail(
        session, actor_id=current_user.id, signal_id=signal_id
    )


@router.post("/signals/{signal_id}/create-ticket", response_model=SignalMutation)
async def create_ticket(
    signal_id: UUID,
    payload: SignalCreateTicket,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> SignalMutation:
    """Заявка из сигнала в контексте сотрудника. Автоматически не создаётся никогда."""
    return await container.signal_inbox.create_ticket(
        session,
        actor_id=current_user.id,
        signal_id=signal_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/signals/{signal_id}/join", response_model=SignalMutation)
async def join(
    signal_id: UUID,
    payload: SignalJoin,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> SignalMutation:
    """Новый Report под открытой проблемой того же дома; второй Ticket не создаётся."""
    return await container.signal_inbox.join(
        session,
        actor_id=current_user.id,
        signal_id=signal_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/signals/{signal_id}/route-external", response_model=SignalMutation)
async def route_external(
    signal_id: UUID,
    payload: SignalRouteExternal,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> SignalMutation:
    """Отметка внешнего маршрута со снимком. Продукт никуда ничего не отправляет."""
    return await container.signal_inbox.route_external(
        session,
        actor_id=current_user.id,
        signal_id=signal_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/signals/{signal_id}/choose-route", response_model=SignalMutation)
async def choose_route(
    signal_id: UUID,
    payload: SignalChooseRoute,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> SignalMutation:
    """Выбор маршрута, когда роутер вернул `unknown` или требует выбора оператора."""
    return await container.signal_inbox.choose_route(
        session,
        actor_id=current_user.id,
        signal_id=signal_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/signals/{signal_id}/dismiss", response_model=SignalMutation)
async def dismiss(
    signal_id: UUID,
    payload: SignalDismiss,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> SignalMutation:
    """Закрыть сигнал с обязательной причиной: она нужна оценке качества."""
    return await container.signal_inbox.dismiss(
        session,
        actor_id=current_user.id,
        signal_id=signal_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )
