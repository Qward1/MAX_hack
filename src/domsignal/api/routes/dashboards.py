"""Дашборды платформы и УК (D2): агрегаты без текстов жителей."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.api.routes.administration import Employee
from domsignal.contracts.dashboards import CompanyDashboard, PeriodDays, PlatformDashboard
from domsignal.services.dashboards import DashboardService, company_csv
from domsignal.services.errors import FieldValidationError
from domsignal.services.onboarding import require_platform

router = APIRouter(prefix="/api/v1", tags=["dashboards"])
#: Период обзора: 7, 14 или 30 суток.
Days = Annotated[int, Query(ge=7, le=30, description="Период: 7, 14 или 30 суток")]


def period_days(days: int) -> PeriodDays:
    if days not in (7, 14, 30):
        raise FieldValidationError("Период: 7, 14 или 30 суток", field="query.days")
    return cast(PeriodDays, days)


def service(container: ContainerDep) -> DashboardService:
    return DashboardService(container.settings.llm_daily_call_budget)


@router.get("/platform/dashboard", response_model=PlatformDashboard)
async def platform_dashboard(
    user: Employee, db: DbDep, container: ContainerDep, days: Days = 7
) -> PlatformDashboard:
    async with db.begin():
        await require_platform(db, user.id)
        return await service(container).platform(db, period_days(days))


@router.get("/companies/{company_id}/dashboard", response_model=CompanyDashboard)
async def company_dashboard(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep, days: Days = 7
) -> CompanyDashboard:
    """Администратор видит все дома УК, оператор — только назначенные."""
    async with db.begin():
        return await service(container).company(db, user.id, company_id, period_days(days))


@router.get(
    "/companies/{company_id}/dashboard.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
)
async def company_dashboard_csv(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep, days: Days = 7
) -> Response:
    async with db.begin():
        dashboard = await service(container).company(db, user.id, company_id, period_days(days))
    return Response(
        content=company_csv(dashboard).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="domsignal-overview-{days}d.csv"'},
    )
