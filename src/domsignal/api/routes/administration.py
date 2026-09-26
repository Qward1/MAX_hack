from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.api.routes.employee_auth import cookie, ip, preauth, result
from domsignal.contracts.employee_auth import EmployeeSession
from domsignal.contracts.onboarding import (
    AdminBootstrap,
    ApplicationDecision,
    ApplicationReceived,
    ApplicationView,
    AssignmentChange,
    AuditView,
    CompanyApplicationCreate,
    CompanyApproved,
    CompanyHouseView,
    CompanyOverview,
    CompanyView,
    HouseApproval,
    HouseBatchApproval,
    HouseBatchApproved,
    HouseBatchCreate,
    HouseBatchSubmitted,
    HouseRegionChange,
    HouseRequestCreate,
    HouseRequestView,
    InvitationCreate,
    InvitationPreview,
    InvitationRegister,
    InvitationToken,
    InvitationView,
    MembershipView,
    OpenAccessChange,
    OpenAccessClose,
    OpenAccessView,
    PlatformBindingView,
    PlatformBootstrap,
    PlatformHealth,
    PlatformHouseView,
    PlatformOpenHouseView,
    RegionPackView,
    ReviewDecision,
    Role,
    StaffDetail,
)
from domsignal.db.models import (
    CompanyOnboardingRequest,
    EmployeeCredential,
    EmployeeInvitation,
    HouseManagementRequest,
    ManagementCompany,
    User,
)
from domsignal.db.repositories.reliability import authority_lock
from domsignal.services.employee_auth import (
    COOKIE,
    HASHER,
    PRE_COOKIE,
    EmployeeAuthService,
    normalize_login,
)
from domsignal.services.errors import AuthenticationRequired, ResourceNotFound
from domsignal.services.house_region import region_packs
from domsignal.services.onboarding import (
    AdministrationConflict,
    AdministrationService,
    accept_invitation,
    audit,
    require_company,
    require_platform,
)
from domsignal.services.sessions import AuthenticatedUser

router = APIRouter(prefix="/api/v1", tags=["administration"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
Offset = Annotated[int, Query(ge=0, le=100000)]


async def employee_identity(request: Request, container: ContainerDep) -> AuthenticatedUser:
    token = request.cookies.get(COOKIE, "")
    if not token:
        raise AuthenticationRequired("Войдите с паролем и MFA")
    auth = EmployeeAuthService(container.settings)
    if request.method != "GET":
        auth.require_csrf(token, request.headers.get("X-CSRF-Token"), request.headers.get("Origin"))
    async with container.session_factory() as db:
        return await auth.authenticate(db, token)


Employee = Annotated[AuthenticatedUser, Depends(employee_identity)]


@router.post(
    "/onboarding/company-applications", response_model=ApplicationReceived, status_code=202
)
async def public_application(
    payload: CompanyApplicationCreate, request: Request, db: DbDep, container: ContainerDep
) -> ApplicationReceived:
    service = AdministrationService(container.settings)
    await service.auth.rate(db, ip=ip(request), identifier=f"application:{payload.inn}")
    async with db.begin():
        status_url = await service.submit_company(db, payload)
    return ApplicationReceived(status_url=status_url)


@router.get("/admin/bootstrap", response_model=AdminBootstrap)
async def bootstrap(user: CurrentUserDep, db: DbDep, container: ContainerDep) -> AdminBootstrap:
    async with db.begin():
        return await AdministrationService(container.settings).bootstrap(db, user.id)


@router.post("/auth/employee/invitations/preview", response_model=InvitationPreview)
async def invitation_preview(
    payload: InvitationToken, request: Request, db: DbDep, container: ContainerDep
) -> InvitationPreview:
    service = AdministrationService(container.settings)
    preauth(request, service.auth)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"invite:{service.auth.digest(payload.token)}"
    )
    async with db.begin():
        row = await service.token_invitation(db, payload.token)
        company = await db.get(ManagementCompany, row.company_id)
        assert company is not None
        return InvitationPreview(
            company_name=company.name,
            organization_role=cast(Role, row.organization_role),
            expires_at=row.expires_at,
        )


@router.post("/auth/employee/invitations/register", response_model=EmployeeSession)
async def register(
    payload: InvitationRegister,
    request: Request,
    response: Response,
    db: DbDep,
    container: ContainerDep,
) -> EmployeeSession:
    service = AdministrationService(container.settings)
    auth = service.auth
    pre_token = preauth(request, auth)
    await auth.rate(db, ip=ip(request), identifier=f"invite:{auth.digest(payload.token)}")
    auth.validate_password(payload.password)
    auth.cipher()
    try:
        login = normalize_login(payload.login_name)
    except ValueError as exc:
        raise AdministrationConflict("Логин: 3–100 латинских букв, цифр, точек, дефисов") from exc
    async with db.begin():
        await authority_lock(db, exclusive=True)
        challenge, _ = await auth.challenge(db, pre_token, {"login"})
        invite = await service.token_invitation(db, payload.token)
        if await db.scalar(
            select(EmployeeCredential.id).where(EmployeeCredential.login_name == login)
        ):
            raise AdministrationConflict(
                "Логин недоступен. Если у вас есть аккаунт, используйте вход."
            )
        user = User(display_name=payload.display_name)
        db.add(user)
        await db.flush()
        credential = EmployeeCredential(
            user_id=user.id,
            login_name=login,
            password_hash=await run_in_threadpool(HASHER.hash, payload.password),
            password_changed_at=datetime.now(UTC),
            password_change_required=False,
        )
        db.add(credential)
        await db.flush()
        invite.status, invite.claimed_by_user_id, invite.claimed_at = (
            "claimed",
            user.id,
            datetime.now(UTC),
        )
        challenge.consumed_at = datetime.now(UTC)
        token = auth.new_challenge(
            db, stage="mfa_enroll", credential_id=credential.id, invitation_id=invite.id
        )
        audit(db, "invitation.claimed", user.id, invite.id)
    cookie(response, PRE_COOKIE, token, container.settings.auth_challenge_seconds)
    return result(auth, token, "mfa_enroll")


@router.post("/auth/employee/invitations/claim", response_model=InvitationView)
async def claim(
    payload: InvitationToken, user: Employee, db: DbDep, container: ContainerDep
) -> InvitationView:
    service = AdministrationService(container.settings)
    async with db.begin():
        await authority_lock(db, exclusive=True)
        row = await service.claim(db, payload.token, user.id)
        return service.invitation_view(row)


@router.post("/auth/employee/invitations/accept", response_model=InvitationView)
async def accept(
    payload: InvitationToken, user: Employee, db: DbDep, container: ContainerDep
) -> InvitationView:
    service = AdministrationService(container.settings)
    async with db.begin():
        await authority_lock(db, exclusive=True)
        row = await service.token_invitation(db, payload.token, user.id)
        await accept_invitation(db, row.id, user.id)
        await db.flush()
        return service.invitation_view(row)


@router.get("/companies/{company_id}/staff", response_model=list[MembershipView])
async def staff(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> list[MembershipView]:
    async with db.begin():
        return await AdministrationService(container.settings).staff(db, user.id, company_id)


@router.get("/companies/{company_id}/staff/{user_id}", response_model=StaffDetail)
async def staff_detail(
    company_id: UUID, user_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> StaffDetail:
    async with db.begin():
        return await AdministrationService(container.settings).staff_detail(
            db, user.id, company_id, user_id
        )


@router.post("/companies/{company_id}/staff/{user_id}/assignments", response_model=StaffDetail)
async def assignments(
    company_id: UUID,
    user_id: UUID,
    payload: AssignmentChange,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> StaffDetail:
    async with db.begin():
        return await AdministrationService(container.settings).assign(
            db, user.id, company_id, user_id, payload
        )


@router.post("/companies/{company_id}/staff/{user_id}/revoke")
async def revoke_member(
    company_id: UUID, user_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> dict[str, bool]:
    async with db.begin():
        await AdministrationService(container.settings).revoke_member(
            db, user.id, company_id, user_id
        )
    return {"revoked": True}


@router.get("/companies/{company_id}/employee-invitations", response_model=list[InvitationView])
async def invitations(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[InvitationView]:
    async with db.begin():
        await require_company(db, user.id, company_id)
        rows = await db.scalars(
            select(EmployeeInvitation)
            .where(EmployeeInvitation.company_id == company_id)
            .order_by(EmployeeInvitation.created_at.desc())
            .offset(offset)
            .limit(100)
        )
        return [AdministrationService.invitation_view(r) for r in rows]


@router.post(
    "/companies/{company_id}/employee-invitations", response_model=InvitationView, status_code=201
)
async def invite(
    company_id: UUID,
    payload: InvitationCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> InvitationView:
    async with db.begin():
        return await AdministrationService(container.settings).invite(
            db, user.id, company_id, payload.organization_role, key
        )


@router.post(
    "/companies/{company_id}/employee-invitations/{invite_id}/revoke", response_model=InvitationView
)
async def revoke_invite(
    company_id: UUID, invite_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> InvitationView:
    async with db.begin():
        return await AdministrationService(container.settings).revoke_invitation(
            db, user.id, company_id, invite_id
        )


@router.get("/companies/{company_id}/houses", response_model=list[CompanyHouseView])
async def houses(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> list[CompanyHouseView]:
    async with db.begin():
        return await AdministrationService(container.settings).houses(db, user.id, company_id)


@router.get("/companies/{company_id}/houses/{house_id}", response_model=CompanyHouseView)
async def house_detail(
    company_id: UUID, house_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> CompanyHouseView:
    rows = await houses(company_id, user, db, container)
    found = next((h for h in rows if h.house_id == house_id), None)
    if found is None:
        raise ResourceNotFound("Дом не найден")
    return found


@router.post(
    "/companies/{company_id}/houses/{house_id}/open-access", response_model=OpenAccessView
)
async def set_open_access(
    company_id: UUID,
    house_id: UUID,
    payload: OpenAccessChange,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> OpenAccessView:
    """Открытый доступ к дому (OPEN-HOUSE-ACCESS-2026-09-25), с аудитом."""
    async with db.begin():
        return await AdministrationService(container.settings).set_open_access(
            db, user.id, company_id, house_id, payload
        )


@router.get("/companies/{company_id}/organization", response_model=CompanyView)
async def organization(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> CompanyView:
    async with db.begin():
        await require_company(db, user.id, company_id)
        return await AdministrationService(container.settings).company(db, company_id)


@router.get("/companies/{company_id}/overview", response_model=CompanyOverview)
async def overview(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep
) -> CompanyOverview:
    async with db.begin():
        return await AdministrationService(container.settings).overview(db, user.id, company_id)


@router.post(
    "/companies/{company_id}/house-management-requests",
    response_model=HouseRequestView,
    status_code=201,
)
async def request_house(
    company_id: UUID,
    payload: HouseRequestCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> HouseRequestView:
    async with db.begin():
        return await AdministrationService(container.settings).submit_house(
            db, user.id, company_id, payload, key
        )


@router.post(
    "/companies/{company_id}/house-management-requests/batch",
    response_model=HouseBatchSubmitted,
    status_code=201,
)
async def request_houses_batch(
    company_id: UUID,
    payload: HouseBatchCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> HouseBatchSubmitted:
    """Список до 200 адресов → заявки на дома (D5); результат по каждому адресу."""
    async with db.begin():
        return await AdministrationService(container.settings).submit_houses_batch(
            db, user.id, company_id, payload, key
        )


@router.get(
    "/companies/{company_id}/house-management-requests", response_model=list[HouseRequestView]
)
async def house_requests(
    company_id: UUID, user: CurrentUserDep, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[HouseRequestView]:
    async with db.begin():
        await require_company(db, user.id, company_id)
        rows = await db.scalars(
            select(HouseManagementRequest)
            .where(HouseManagementRequest.company_id == company_id)
            .order_by(HouseManagementRequest.created_at.desc())
            .offset(offset)
            .limit(100)
        )
        return [HouseRequestView.model_validate(r, from_attributes=True) for r in rows]


@router.get("/platform/bootstrap", response_model=PlatformBootstrap)
async def platform_bootstrap(user: Employee, db: DbDep) -> PlatformBootstrap:
    async with db.begin():
        actor = await require_platform(db, user.id)
        return PlatformBootstrap(
            display_name=actor.display_name,
            surfaces=[
                "overview",
                "applications",
                "quota-requests",
                "companies",
                "house-management-requests",
                "houses",
                "binding-disputes",
                "health",
                "audit",
                # D3: сообщения платформы УК и в домовые чаты.
                "mailings",
            ],
        )


@router.get("/platform/company-applications", response_model=list[ApplicationView])
async def applications(
    user: Employee, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[ApplicationView]:
    async with db.begin():
        await require_platform(db, user.id)
        service = AdministrationService(container.settings)
        return [
            await service.application_view(db, r)
            for r in await db.scalars(
                select(CompanyOnboardingRequest)
                .order_by(CompanyOnboardingRequest.submitted_at.desc())
                .offset(offset)
                .limit(100)
            )
        ]


@router.get("/platform/company-applications/{obj}", response_model=ApplicationView)
async def application(
    obj: UUID, user: Employee, db: DbDep, container: ContainerDep
) -> ApplicationView:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).application(db, obj)


ReviewAction = Literal["start-review", "request-info", "approve", "reject"]
TARGET = {
    "start-review": "under_review",
    "request-info": "needs_info",
    "approve": "approved",
    "reject": "rejected",
}


@router.post(
    "/platform/company-applications/{obj}/{action}",
    response_model=ApplicationView | CompanyApproved,
)
async def decide_application(
    obj: UUID,
    action: ReviewAction,
    payload: ApplicationDecision,
    user: Employee,
    db: DbDep,
    container: ContainerDep,
) -> ApplicationView | CompanyApproved:
    async with db.begin():
        return await AdministrationService(container.settings).decide_company(
            db,
            obj,
            user.id,
            TARGET[action],
            payload.reason,
            chat_quota=payload.chat_quota,
            unlimited=payload.unlimited,
        )


@router.get("/platform/companies", response_model=list[CompanyView])
async def companies(
    user: Employee, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[CompanyView]:
    async with db.begin():
        await require_platform(db, user.id)
        ids = await db.scalars(
            select(ManagementCompany.id).order_by(ManagementCompany.name).offset(offset).limit(100)
        )
        return [await AdministrationService(container.settings).company(db, obj) for obj in ids]


@router.get("/platform/companies/{obj}", response_model=CompanyView)
async def company(obj: UUID, user: Employee, db: DbDep, container: ContainerDep) -> CompanyView:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).company(db, obj)


@router.post("/platform/companies/{obj}/{action}", response_model=CompanyView)
async def company_status(
    obj: UUID,
    action: Literal["suspend", "reactivate"],
    payload: ReviewDecision,
    user: Employee,
    db: DbDep,
    container: ContainerDep,
) -> CompanyView:
    async with db.begin():
        return await AdministrationService(container.settings).company_status(
            db, user.id, obj, "suspended" if action == "suspend" else "active", payload.reason
        )


@router.get("/platform/house-management-requests", response_model=list[HouseRequestView])
async def platform_requests(
    user: Employee, db: DbDep, offset: Offset = 0
) -> list[HouseRequestView]:
    async with db.begin():
        await require_platform(db, user.id)
        return [
            HouseRequestView.model_validate(r, from_attributes=True)
            for r in await db.scalars(
                select(HouseManagementRequest)
                .order_by(HouseManagementRequest.created_at.desc())
                .offset(offset)
                .limit(100)
            )
        ]


@router.post(
    "/platform/house-management-requests/approve-batch", response_model=HouseBatchApproved
)
async def approve_houses_batch(
    payload: HouseBatchApproval, user: Employee, db: DbDep, container: ContainerDep
) -> HouseBatchApproved:
    """Одобрить выбранные заявки на дома одним действием с одним регионом (D5)."""
    async with db.begin():
        return await AdministrationService(container.settings).approve_houses_batch(
            db, user.id, payload, container.routing.directory
        )


@router.get("/platform/house-management-requests/{obj}", response_model=HouseRequestView)
async def platform_request(
    obj: UUID, user: Employee, db: DbDep, container: ContainerDep
) -> HouseRequestView:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).house_request(db, obj)


@router.post("/platform/house-management-requests/{obj}/approve", response_model=HouseRequestView)
async def approve_house(
    obj: UUID, payload: HouseApproval, user: Employee, db: DbDep, container: ContainerDep
) -> HouseRequestView:
    async with db.begin():
        return await AdministrationService(container.settings).decide_house(
            db, obj, user.id, "approved", payload.reason, payload, container.routing.directory
        )


@router.get("/platform/region-packs", response_model=list[RegionPackView])
async def platform_region_packs(
    user: Employee, db: DbDep, container: ContainerDep
) -> list[RegionPackView]:
    """Регионы загруженного справочника — варианты при одобрении дома (D4)."""
    async with db.begin():
        await require_platform(db, user.id)
    return region_packs(container.routing.directory)


@router.post("/platform/houses/{house_id}/region", response_model=PlatformHouseView)
async def platform_house_region(
    house_id: UUID, payload: HouseRegionChange, user: Employee, db: DbDep, container: ContainerDep
) -> PlatformHouseView:
    async with db.begin():
        return await AdministrationService(container.settings).set_house_region(
            db, user.id, house_id, payload, container.routing.directory
        )


@router.post("/platform/house-management-requests/{obj}/{action}", response_model=HouseRequestView)
async def decide_house(
    obj: UUID,
    action: Literal["start-review", "request-info", "reject"],
    payload: ReviewDecision,
    user: Employee,
    db: DbDep,
    container: ContainerDep,
) -> HouseRequestView:
    async with db.begin():
        return await AdministrationService(container.settings).decide_house(
            db, obj, user.id, TARGET[action], payload.reason
        )


@router.get("/platform/houses", response_model=list[PlatformHouseView])
async def platform_houses(
    user: Employee, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[PlatformHouseView]:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).platform_houses(db, offset)


@router.get("/platform/open-houses", response_model=list[PlatformOpenHouseView])
async def platform_open_houses(
    user: Employee, db: DbDep, container: ContainerDep
) -> list[PlatformOpenHouseView]:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).platform_open_houses(db)


@router.post("/platform/houses/{house_id}/open-access/close", response_model=OpenAccessView)
async def platform_close_open_access(
    house_id: UUID, payload: OpenAccessClose, user: Employee, db: DbDep, container: ContainerDep
) -> OpenAccessView:
    async with db.begin():
        return await AdministrationService(container.settings).platform_close_open_access(
            db, user.id, house_id, payload.reason
        )


@router.post(
    "/platform/companies/{obj}/invitations/first-admin",
    response_model=InvitationView,
    status_code=201,
)
async def reissue_first_admin(
    obj: UUID, payload: ReviewDecision, key: Key, user: Employee, db: DbDep, container: ContainerDep
) -> InvitationView:
    async with db.begin():
        return await AdministrationService(container.settings).reissue_first_admin(
            db, user.id, obj, key, payload.reason
        )


@router.get("/platform/binding-disputes", response_model=list[PlatformBindingView])
async def disputes(
    user: Employee, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[PlatformBindingView]:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).disputes(db, offset)


@router.get("/platform/health", response_model=PlatformHealth)
async def health(user: Employee, db: DbDep, container: ContainerDep) -> PlatformHealth:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).health(db)


@router.get("/platform/audit", response_model=list[AuditView])
async def platform_audit(
    user: Employee, db: DbDep, container: ContainerDep, offset: Offset = 0
) -> list[AuditView]:
    async with db.begin():
        await require_platform(db, user.id)
        return await AdministrationService(container.settings).history(db, offset=offset)
