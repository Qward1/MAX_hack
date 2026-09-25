from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.notifications import NotificationLaunch
from domsignal.contracts.tickets import (
    AssignCommand,
    AssigneeList,
    AttemptList,
    DeadlineCreate,
    DeadlineList,
    EventList,
    ObservationCreate,
    ObservationList,
    ObservationRecorded,
    OwnObservationList,
    ReasonCommand,
    ResidentWorkStatus,
    TicketCommand,
    TicketList,
    TicketMutation,
    TicketView,
    WorkAttemptCreate,
)
from domsignal.core.tickets import TicketAction, TicketStatus

router = APIRouter(prefix="/api/v1", tags=["tickets"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100000)]


@router.get("/notification-launch/{ref}", response_model=NotificationLaunch)
async def notification_launch(
    ref: str,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> NotificationLaunch:
    return await container.notifications.launch(session, actor_id=current_user.id, ref=ref)


@router.get("/tickets", response_model=TicketList)
async def tickets(
    house_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
    status: TicketStatus | None = None,
    assignee_id: UUID | None = None,
    unassigned: bool = False,
) -> TicketList:
    return await container.ticket_service.list_for_house(
        session,
        actor_id=current_user.id,
        house_id=house_id,
        limit=limit,
        offset=offset,
        status=status,
        assignee_id=assignee_id,
        unassigned=unassigned,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketView)
async def ticket_detail(
    ticket_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> TicketView:
    return await container.ticket_service.detail(
        session, actor_id=current_user.id, ticket_id=ticket_id
    )


@router.get("/tickets/{ticket_id}/assignees", response_model=AssigneeList)
async def assignees(
    ticket_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> AssigneeList:
    return await container.ticket_service.assignees(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        limit=limit,
        offset=offset,
    )


@router.post("/tickets/{ticket_id}/assign", response_model=TicketMutation)
async def assign(
    ticket_id: UUID,
    payload: AssignCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.ASSIGN,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/accept", response_model=TicketMutation)
async def accept(
    ticket_id: UUID,
    payload: TicketCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.ACCEPT,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/start", response_model=TicketMutation)
async def start(
    ticket_id: UUID,
    payload: TicketCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.START,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/clarify", response_model=TicketMutation)
async def clarify(
    ticket_id: UUID,
    payload: ReasonCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.CLARIFY,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/wait-external", response_model=TicketMutation)
async def wait_external(
    ticket_id: UUID,
    payload: ReasonCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.WAIT_EXTERNAL,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/resume", response_model=TicketMutation)
async def resume(
    ticket_id: UUID,
    payload: ReasonCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.RESUME,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/cancel", response_model=TicketMutation)
async def cancel(
    ticket_id: UUID,
    payload: ReasonCommand,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.CANCEL,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/work-attempts", response_model=TicketMutation)
async def report_work(
    ticket_id: UUID,
    payload: WorkAttemptCreate,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.WORK_REPORT,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post("/tickets/{ticket_id}/deadlines", response_model=TicketMutation)
async def deadline(
    ticket_id: UUID,
    payload: DeadlineCreate,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> TicketMutation:
    return await container.ticket_service.command(
        session,
        actor_id=current_user.id,
        ticket_id=ticket_id,
        action=TicketAction.DEADLINE,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/tickets/{ticket_id}/events", response_model=EventList)
async def events(
    ticket_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> EventList:
    return cast(
        EventList,
        await container.ticket_service.history(
            session,
            actor_id=current_user.id,
            ticket_id=ticket_id,
            kind="events",
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/tickets/{ticket_id}/work-attempts", response_model=AttemptList)
async def attempts(
    ticket_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> AttemptList:
    return cast(
        AttemptList,
        await container.ticket_service.history(
            session,
            actor_id=current_user.id,
            ticket_id=ticket_id,
            kind="attempts",
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/tickets/{ticket_id}/deadlines", response_model=DeadlineList)
async def deadlines(
    ticket_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> DeadlineList:
    return cast(
        DeadlineList,
        await container.ticket_service.history(
            session,
            actor_id=current_user.id,
            ticket_id=ticket_id,
            kind="deadlines",
            limit=limit,
            offset=offset,
        ),
    )


@router.post("/work-attempts/{attempt_id}/observations", response_model=ObservationRecorded)
async def observe(
    attempt_id: UUID,
    payload: ObservationCreate,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Key,
) -> ObservationRecorded:
    return await container.ticket_service.observe(
        session,
        actor_id=current_user.id,
        attempt_id=attempt_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/incidents/{incident_id}/work-status", response_model=ResidentWorkStatus)
async def work_status(
    incident_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> ResidentWorkStatus:
    return await container.ticket_service.work_status(
        session, actor_id=current_user.id, incident_id=incident_id
    )


@router.get("/work-attempts/{attempt_id}/observations", response_model=ObservationList)
async def observations(
    attempt_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> ObservationList:
    return cast(
        ObservationList,
        await container.ticket_service.observations(
            session,
            actor_id=current_user.id,
            attempt_id=attempt_id,
            own=False,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/work-attempts/{attempt_id}/my-observations", response_model=OwnObservationList)
async def my_observations(
    attempt_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> OwnObservationList:
    return cast(
        OwnObservationList,
        await container.ticket_service.observations(
            session,
            actor_id=current_user.id,
            attempt_id=attempt_id,
            own=True,
            limit=limit,
            offset=offset,
        ),
    )
