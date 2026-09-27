from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.incidents import (
    IncidentDetail,
    IncidentList,
    IncidentListState,
    ReportCreate,
    ReportCreated,
    ReportPreview,
    ReportPreviewRequest,
    ReportSubmitRequest,
    ReportSubmitted,
)
from domsignal.contracts.routing import RouteOutcomeView

router = APIRouter(prefix="/api/v1", tags=["incidents"])


@router.post("/reports", response_model=ReportCreated, status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: ReportCreate,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> ReportCreated:
    return await container.report_service.create(
        session,
        actor_id=current_user.id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/houses/{house_id}/reports/preview",
    response_model=ReportPreview,
    status_code=status.HTTP_200_OK,
)
async def preview_report(
    house_id: UUID,
    payload: ReportPreviewRequest,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> ReportPreview:
    """Разбор описания и карточка следующего шага. Ничего не создаёт."""
    return await container.explicit_reports.preview(
        session,
        actor_id=current_user.id,
        house_id=house_id,
        description=payload.description,
    )


@router.post(
    "/houses/{house_id}/reports/submit",
    response_model=ReportSubmitted,
    status_code=status.HTTP_201_CREATED,
)
async def submit_report(
    house_id: UUID,
    payload: ReportSubmitRequest,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> ReportSubmitted:
    """Отправка формы через ту же цепочку решения, что и сообщение в чате."""
    return await container.explicit_reports.submit(
        session,
        actor_id=current_user.id,
        house_id=house_id,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/route-outcomes/{outcome_id}", response_model=RouteOutcomeView)
async def route_outcome(
    outcome_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> RouteOutcomeView:
    """Карточка маршрута по исходу. Чужой и несуществующий исход дают 404."""
    return await container.explicit_reports.outcome_view(
        session, actor_id=current_user.id, outcome_id=outcome_id
    )


@router.post("/incidents/{incident_id}/join", response_model=IncidentDetail)
async def join_incident(
    incident_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
) -> IncidentDetail:
    """Присоединиться к уже созданной проблеме. Новый Ticket не создаётся."""
    return await container.report_service.join(
        session,
        actor_id=current_user.id,
        incident_id=incident_id,
        idempotency_key=idempotency_key,
    )


@router.get("/houses/{house_id}/incidents", response_model=IncidentList)
async def list_incidents(
    house_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    state: IncidentListState = "all",
) -> IncidentList:
    """Проблемы дома. `state=open` — открытые, `resolved_recent` — решённые за 30 дней."""
    return await container.report_service.list_for_house(
        session,
        actor_id=current_user.id,
        house_id=house_id,
        limit=limit,
        offset=offset,
        state=state,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def incident_detail(
    incident_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    house_id: Annotated[UUID | None, Query()] = None,
) -> IncidentDetail:
    return await container.report_service.detail(
        session, actor_id=current_user.id, incident_id=incident_id, house_id=house_id
    )
