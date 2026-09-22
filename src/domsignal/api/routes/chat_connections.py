from uuid import UUID

from fastapi import APIRouter

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.chat_connections import (
    BindingView,
    ConnectionApprove,
    ConnectionCreate,
    ConnectionView,
    PassiveCaptureChange,
    PassiveCaptureView,
)
from domsignal.services.chat_connections import ChatConnectionError

router = APIRouter(prefix="/api/v1", tags=["chat-connections"])


@router.post("/houses/{house_id}/chat-connections", response_model=ConnectionView, status_code=201)
async def initiate(
    house_id: UUID,
    payload: ConnectionCreate,
    user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> ConnectionView:
    async with session.begin():
        request, token = await container.chat_connections.initiate(
            session,
            actor_id=user.id,
            house_id=house_id,
            scope=payload,
        )
        return await container.chat_connections.view(session, request, token)


@router.get("/chat-connections/{request_id}", response_model=ConnectionView)
async def connection(
    request_id: UUID,
    user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> ConnectionView:
    async with session.begin():
        request = await container.chat_connections.locked_request(session, request_id)
        await container.chat_connections.require_authority(session, request, user.id)
        container.chat_connections.expire(request)
        return await container.chat_connections.view(session, request)


@router.post("/chat-connections/{request_id}/approve", response_model=BindingView)
async def approve(
    request_id: UUID,
    payload: ConnectionApprove,
    user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> BindingView:
    del payload  # Literal True is the explicit confirmation; no client authority fields.
    error = None
    async with session.begin():
        try:
            binding = await container.chat_connections.approve(
                session,
                request_id=request_id,
                actor_id=user.id,
            )
        except ChatConnectionError as exc:
            error = exc  # Persist expiry / failed verification without rolling it back.
    if error:
        raise error
    return BindingView.model_validate(binding, from_attributes=True)


@router.post("/chat-connections/{request_id}/reject", response_model=ConnectionView)
async def reject(
    request_id: UUID,
    user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> ConnectionView:
    async with session.begin():
        request = await container.chat_connections.finish(
            session,
            request_id=request_id,
            actor_id=user.id,
            target="rejected",
        )
        return await container.chat_connections.view(session, request)


@router.post("/chat-connections/{request_id}/cancel", response_model=ConnectionView)
async def cancel(
    request_id: UUID,
    user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> ConnectionView:
    async with session.begin():
        request = await container.chat_connections.finish(
            session,
            request_id=request_id,
            actor_id=user.id,
            target="cancelled",
        )
        return await container.chat_connections.view(session, request)


@router.post("/chat-bindings/{binding_id}/passive-capture", response_model=PassiveCaptureView)
async def passive_capture(
    binding_id: UUID,
    payload: PassiveCaptureChange,
    user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> PassiveCaptureView:
    """Выключатель чтения чата в кабинете — то же право `chat.connect`, что у CLI.

    Включение ставит сообщение о чтении чата один раз на версию привязки;
    выключение сразу прекращает приём, собранные сигналы остаются.
    """
    async with session.begin():
        toggle = await container.passive.set_capture(
            session, binding_id=binding_id, actor_id=user.id, enabled=payload.enabled
        )
    return PassiveCaptureView(
        binding_id=toggle.binding_id,
        binding_version=toggle.binding_version,
        passive_capture_enabled=toggle.passive_capture_enabled,
        notice_queued=toggle.notice_queued,
    )
