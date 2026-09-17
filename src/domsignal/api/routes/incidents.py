from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.contracts.incidents import IncidentDetail, IncidentList, ReportCreate, ReportCreated

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


@router.get("/houses/{house_id}/incidents", response_model=IncidentList)
async def list_incidents(
    house_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentList:
    return await container.report_service.list_for_house(
        session,
        actor_id=current_user.id,
        house_id=house_id,
        limit=limit,
        offset=offset,
    )


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
async def incident_detail(
    incident_id: UUID,
    current_user: CurrentUserDep,
    session: DbDep,
    container: ContainerDep,
) -> IncidentDetail:
    return await container.report_service.detail(
        session, actor_id=current_user.id, incident_id=incident_id
    )
