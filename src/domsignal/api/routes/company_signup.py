"""D2: страница статуса заявки, сброс пароля/MFA, открытая регистрация, квота, вход.

Публичные ссылки несут секрет только в пути страницы (журналы его скрывают);
в API секрет передаётся телом запроса, а не адресом.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from domsignal.api.dependencies import ContainerDep, CurrentUserDep, DbDep
from domsignal.api.routes.administration import Employee
from domsignal.api.routes.employee_auth import cookie, ip, preauth, result
from domsignal.contracts.employee_auth import EmployeeSession
from domsignal.contracts.onboarding import (
    AdminInvitationLink,
    ApplicationReply,
    ApplicationStatusToken,
    ApplicationStatusView,
    CredentialResetComplete,
    CredentialResetCreate,
    CredentialResetIssued,
    CredentialResetPreview,
    CredentialResetToken,
    EmployeeDestinations,
    JoinCode,
    JoinPreview,
    JoinRegister,
    NotifyLink,
    OpenRegistrationChange,
    OpenRegistrationView,
)
from domsignal.contracts.quota import (
    ChatQuotaDecision,
    ChatQuotaRequestCreate,
    ChatQuotaRequestView,
    ChatQuotaSet,
    CompanyQuotaView,
)
from domsignal.db.models import EmployeeCredential, User
from domsignal.db.repositories.reliability import authority_lock
from domsignal.services.chat_quota import ChatQuotaService
from domsignal.services.company_signup import CompanySignupService
from domsignal.services.employee_auth import HASHER, PRE_COOKIE, normalize_login
from domsignal.services.onboarding import (
    AdministrationConflict,
    audit,
    require_company,
    require_platform,
)

router = APIRouter(prefix="/api/v1", tags=["company-signup"])
Key = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]
Offset = Annotated[int, Query(ge=0, le=100000)]


# --- страница статуса заявки УК ------------------------------------------------------


@router.post("/onboarding/application-status", response_model=ApplicationStatusView)
async def application_status(
    payload: ApplicationStatusToken, request: Request, db: DbDep, container: ContainerDep
) -> ApplicationStatusView:
    service = CompanySignupService(container.settings)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"status:{service.auth.digest(payload.token)}"
    )
    async with db.begin():
        return await service.status(db, payload.token)


@router.post("/onboarding/application-status/reply", response_model=ApplicationStatusView)
async def application_reply(
    payload: ApplicationReply, request: Request, db: DbDep, container: ContainerDep
) -> ApplicationStatusView:
    service = CompanySignupService(container.settings)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"status:{service.auth.digest(payload.token)}"
    )
    async with db.begin():
        return await service.reply(db, payload.token, payload.text.strip())


@router.post("/onboarding/application-status/admin-invitation", response_model=AdminInvitationLink)
async def application_admin_invitation(
    payload: ApplicationStatusToken, request: Request, db: DbDep, container: ContainerDep
) -> AdminInvitationLink:
    """«Создать аккаунт администратора»: приглашение первого администратора A-10."""
    service = CompanySignupService(container.settings)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"status:{service.auth.digest(payload.token)}"
    )
    async with db.begin():
        url = await service.admin_invitation(db, payload.token)
    return AdminInvitationLink(invitation_url=url)


@router.post("/onboarding/application-status/notify-link", response_model=NotifyLink)
async def application_notify_link(
    payload: ApplicationStatusToken, request: Request, db: DbDep, container: ContainerDep
) -> NotifyLink:
    """«Получать уведомления в MAX»: ссылка на бота с одноразовым кодом `ca_…`."""
    service = CompanySignupService(container.settings)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"status:{service.auth.digest(payload.token)}"
    )
    async with db.begin():
        return NotifyLink(bot_url=await service.notify_link(db, payload.token))


# --- единый вход ---------------------------------------------------------------------


@router.get("/auth/employee/destinations", response_model=EmployeeDestinations)
async def destinations(user: Employee, db: DbDep, container: ContainerDep) -> EmployeeDestinations:
    """Куда вести сотрудника после входа: платформа и/или его УК."""
    async with db.begin():
        return await CompanySignupService(container.settings).destinations(db, user.id)


# --- сброс пароля/MFA ----------------------------------------------------------------


@router.post(
    "/companies/{company_id}/staff/{user_id}/credential-reset",
    response_model=CredentialResetIssued,
    status_code=201,
)
async def issue_credential_reset(
    company_id: UUID,
    user_id: UUID,
    payload: CredentialResetCreate,
    user: CurrentUserDep,
    db: DbDep,
    container: ContainerDep,
) -> CredentialResetIssued:
    async with db.begin():
        return await CompanySignupService(container.settings).issue_reset(
            db, actor=user.id, company=company_id, user=user_id, kind=payload.kind
        )


@router.post("/auth/employee/credential-reset/preview", response_model=CredentialResetPreview)
async def preview_credential_reset(
    payload: CredentialResetToken, request: Request, db: DbDep, container: ContainerDep
) -> CredentialResetPreview:
    service = CompanySignupService(container.settings)
    preauth(request, service.auth)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"reset:{service.auth.digest(payload.token)}"
    )
    async with db.begin():
        return await service.preview_reset(db, payload.token)


@router.post("/auth/employee/credential-reset/complete", response_model=EmployeeSession)
async def complete_credential_reset(
    payload: CredentialResetComplete,
    request: Request,
    response: Response,
    db: DbDep,
    container: ContainerDep,
) -> EmployeeSession:
    service = CompanySignupService(container.settings)
    auth = service.auth
    pre_token = preauth(request, auth)
    await auth.rate(db, ip=ip(request), identifier=f"reset:{auth.digest(payload.token)}")
    auth.validate_password(payload.password)
    auth.cipher()
    async with db.begin():
        await authority_lock(db, exclusive=True)
        challenge, _ = await auth.challenge(db, pre_token, {"login"})
        token, stage = await service.complete_reset(
            db, token=payload.token, password=payload.password, challenge=challenge
        )
    cookie(response, PRE_COOKIE, token, container.settings.auth_challenge_seconds)
    return result(auth, token, stage)


# --- открытая регистрация сотрудников ---------------------------------------------------


@router.get(
    "/platform/companies/{company_id}/open-registration", response_model=OpenRegistrationView
)
async def open_registration(
    company_id: UUID, user: Employee, db: DbDep, container: ContainerDep
) -> OpenRegistrationView:
    async with db.begin():
        await require_platform(db, user.id)
        return await CompanySignupService(container.settings).open_registration(db, company_id)


@router.post(
    "/platform/companies/{company_id}/open-registration", response_model=OpenRegistrationView
)
async def set_open_registration(
    company_id: UUID,
    payload: OpenRegistrationChange,
    user: Employee,
    db: DbDep,
    container: ContainerDep,
) -> OpenRegistrationView:
    async with db.begin():
        return await CompanySignupService(container.settings).set_open_registration(
            db, actor=user.id, company_id=company_id, enabled=payload.enabled, reason=payload.reason
        )


@router.post("/auth/employee/join/preview", response_model=JoinPreview)
async def join_preview(
    payload: JoinCode, request: Request, db: DbDep, container: ContainerDep
) -> JoinPreview:
    service = CompanySignupService(container.settings)
    preauth(request, service.auth)
    await service.auth.rate(
        db, ip=ip(request), identifier=f"join:{service.auth.digest(payload.code)}"
    )
    async with db.begin():
        company = await service.company_by_code(db, payload.code)
        return JoinPreview(company_name=company.name)


@router.post("/auth/employee/join/register", response_model=EmployeeSession)
async def join_register(
    payload: JoinRegister,
    request: Request,
    response: Response,
    db: DbDep,
    container: ContainerDep,
) -> EmployeeSession:
    """Регистрация по открытой ссылке: логин, пароль, затем обязательный TOTP.

    Роль оператора и назначения на дома появляются только после второго
    фактора — тем же путём, что принятие приглашения A-10.
    """
    service = CompanySignupService(container.settings)
    auth = service.auth
    pre_token = preauth(request, auth)
    await auth.rate(db, ip=ip(request), identifier=f"join:{auth.digest(payload.code)}")
    auth.validate_password(payload.password)
    auth.cipher()
    try:
        login = normalize_login(payload.login_name)
    except ValueError as exc:
        raise AdministrationConflict("Логин: 3–100 латинских букв, цифр, точек, дефисов") from exc
    async with db.begin():
        await authority_lock(db, exclusive=True)
        challenge, _ = await auth.challenge(db, pre_token, {"login"})
        company = await service.company_by_code(db, payload.code)
        if await db.scalar(
            select(EmployeeCredential.id).where(EmployeeCredential.login_name == login)
        ):
            raise AdministrationConflict(
                "Логин недоступен. Если у вас есть аккаунт, используйте вход."
            )
        new_user = User(display_name=payload.display_name.strip())
        db.add(new_user)
        await db.flush()
        credential = EmployeeCredential(
            user_id=new_user.id,
            login_name=login,
            password_hash=await run_in_threadpool(HASHER.hash, payload.password),
            password_changed_at=datetime.now(UTC),
            password_change_required=False,
        )
        db.add(credential)
        invitation = service.join_invitation(company.id, new_user.id)
        db.add(invitation)
        await db.flush()
        challenge.consumed_at = datetime.now(UTC)
        token = auth.new_challenge(
            db, stage="mfa_enroll", credential_id=credential.id, invitation_id=invitation.id
        )
        audit(db, "open_registration.registered", new_user.id, company.id)
    cookie(response, PRE_COOKIE, token, container.settings.auth_challenge_seconds)
    return result(auth, token, "mfa_enroll")


# --- квота чатов -----------------------------------------------------------------------


@router.get("/companies/{company_id}/chat-quota", response_model=CompanyQuotaView)
async def company_quota(company_id: UUID, user: CurrentUserDep, db: DbDep) -> CompanyQuotaView:
    """Квота и история УК; оператору — только просмотр."""
    async with db.begin():
        await require_company(db, user.id, company_id, admin=False)
        return await ChatQuotaService().overview(db, company_id)


@router.post(
    "/companies/{company_id}/chat-quota/requests",
    response_model=ChatQuotaRequestView,
    status_code=201,
)
async def request_quota(
    company_id: UUID,
    payload: ChatQuotaRequestCreate,
    key: Key,
    user: CurrentUserDep,
    db: DbDep,
) -> ChatQuotaRequestView:
    async with db.begin():
        await require_company(db, user.id, company_id)
        view = await ChatQuotaService().request_expansion(
            db,
            actor_id=user.id,
            company_id=company_id,
            delta=payload.requested_delta,
            reason=payload.reason.strip(),
            key=key,
        )
        audit(db, "chat_quota_request.submitted", user.id, company_id)
        return view


@router.post(
    "/companies/{company_id}/chat-quota/requests/{request_id}/cancel",
    response_model=ChatQuotaRequestView,
)
async def cancel_quota_request(
    company_id: UUID, request_id: UUID, user: CurrentUserDep, db: DbDep
) -> ChatQuotaRequestView:
    async with db.begin():
        await require_company(db, user.id, company_id)
        return await ChatQuotaService().cancel_request(
            db, company_id=company_id, request_id=request_id
        )


@router.get("/platform/companies/{company_id}/chat-quota", response_model=CompanyQuotaView)
async def platform_company_quota(company_id: UUID, user: Employee, db: DbDep) -> CompanyQuotaView:
    async with db.begin():
        await require_platform(db, user.id)
        return await ChatQuotaService().overview(db, company_id)


@router.post("/platform/companies/{company_id}/chat-quota", response_model=CompanyQuotaView)
async def platform_set_quota(
    company_id: UUID, payload: ChatQuotaSet, user: Employee, db: DbDep
) -> CompanyQuotaView:
    async with db.begin():
        await require_platform(db, user.id)
        view = await ChatQuotaService().set_limit(
            db,
            actor_id=user.id,
            company_id=company_id,
            limit=payload.limit,
            reason=payload.reason.strip(),
        )
        audit(db, "chat_quota.set", user.id, company_id, payload.reason.strip())
        return view


@router.get("/platform/chat-quota-requests", response_model=list[ChatQuotaRequestView])
async def platform_quota_requests(
    user: Employee, db: DbDep, pending: bool = True, offset: Offset = 0
) -> list[ChatQuotaRequestView]:
    async with db.begin():
        await require_platform(db, user.id)
        return await ChatQuotaService().platform_requests(db, only_pending=pending, offset=offset)


@router.post(
    "/platform/chat-quota-requests/{request_id}/decide", response_model=ChatQuotaRequestView
)
async def platform_decide_quota(
    request_id: UUID, payload: ChatQuotaDecision, user: Employee, db: DbDep
) -> ChatQuotaRequestView:
    async with db.begin():
        await require_platform(db, user.id)
        view = await ChatQuotaService().decide(
            db,
            actor_id=user.id,
            request_id=request_id,
            granted=payload.granted_delta,
            reason=payload.reason.strip(),
        )
        audit(
            db, f"chat_quota_request.{view.status}", user.id, view.company_id, view.decision_reason
        )
        return view
