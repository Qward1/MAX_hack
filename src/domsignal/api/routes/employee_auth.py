from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, cast

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update

from domsignal.api.dependencies import ContainerDep, DbDep
from domsignal.contracts.employee_auth import (
    EmployeeCode,
    EmployeeEnrollment,
    EmployeeLogin,
    EmployeePassword,
    EmployeeSession,
)
from domsignal.db.models import AppSession, AuthChallenge, EmployeeCredential
from domsignal.services.employee_auth import (
    COOKIE,
    INVALID,
    PRE_COOKIE,
    SOURCE,
    EmployeeAuthService,
    audit,
    normalize_login,
)
from domsignal.services.errors import AuthenticationRequired

router = APIRouter(prefix="/api/v1/auth/employee", tags=["employee-auth"])
Stage = Literal["login", "password_change", "mfa_enroll", "mfa_challenge", "authenticated"]


def cookie(response: Response, name: str, token: str, ttl: int) -> None:
    response.set_cookie(
        name, token, max_age=ttl, secure=True, httponly=True, samesite="lax", path="/"
    )


def clear_cookie(response: Response, name: str) -> None:
    response.delete_cookie(name, secure=True, httponly=True, samesite="lax", path="/")


def preauth(request: Request, service: EmployeeAuthService) -> str:
    token = request.cookies.get(PRE_COOKIE, "")
    service.require_csrf(token, request.headers.get("X-CSRF-Token"), request.headers.get("Origin"))
    return token


def result(service: EmployeeAuthService, token: str, stage: str) -> EmployeeSession:
    return EmployeeSession(stage=cast(Stage, stage), csrf_token=service.csrf(token))


def ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/session", response_model=EmployeeSession)
async def current_session(
    request: Request, response: Response, db: DbDep, container: ContainerDep
) -> EmployeeSession:
    service = EmployeeAuthService(container.settings)
    token = request.cookies.get(COOKIE, "")
    if token:
        try:
            await service.authenticate(db, token)
            return result(service, token, "authenticated")
        except AuthenticationRequired:
            clear_cookie(response, COOKIE)
    token = request.cookies.get(PRE_COOKIE, "")
    if token:
        try:
            async with db.begin():
                row, _ = await service.challenge(
                    db, token, {"login", "password_change", "mfa_enroll", "mfa_challenge"}
                )
                return result(service, token, row.stage)
        except AuthenticationRequired:
            pass
    await service.rate(db, ip=ip(request), identifier=f"bootstrap:{ip(request)}")
    async with db.begin():
        await service.cleanup(db)
        token = service.new_challenge(db, stage="login")
    cookie(response, PRE_COOKIE, token, container.settings.auth_challenge_seconds)
    return result(service, token, "login")


@router.post("/login", response_model=EmployeeSession)
async def login(
    payload: EmployeeLogin, request: Request, response: Response, db: DbDep, container: ContainerDep
) -> EmployeeSession:
    service = EmployeeAuthService(container.settings)
    token = preauth(request, service)
    try:
        name = normalize_login(payload.login_name)
    except ValueError:
        name = "invalid-identifier"
    await service.rate(db, ip=ip(request), identifier=name)
    if len(payload.password) > container.settings.auth_password_max_length:
        raise AuthenticationRequired(INVALID)
    token, stage = await service.login(db, token, name, payload.password)
    cookie(response, PRE_COOKIE, token, container.settings.auth_challenge_seconds)
    return result(service, token, stage)


@router.post("/password/change", response_model=EmployeeSession)
async def change_password(
    payload: EmployeePassword,
    request: Request,
    response: Response,
    db: DbDep,
    container: ContainerDep,
) -> EmployeeSession:
    service = EmployeeAuthService(container.settings)
    token = preauth(request, service)
    await service.rate(db, ip=ip(request), identifier=f"change:{service.digest(token)}")
    token, stage = await service.change_password(db, token, payload.password)
    cookie(response, PRE_COOKIE, token, container.settings.auth_challenge_seconds)
    return result(service, token, stage)


@router.post("/mfa/enroll", response_model=EmployeeEnrollment)
async def enroll(request: Request, db: DbDep, container: ContainerDep) -> EmployeeEnrollment:
    service = EmployeeAuthService(container.settings)
    secret, uri = await service.enroll(db, preauth(request, service))
    svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).to_string().decode()
    return EmployeeEnrollment(secret=secret, otpauth_uri=uri, qr_svg=svg)


async def complete(
    payload: EmployeeCode,
    request: Request,
    response: Response,
    db: DbDep,
    container: ContainerDep,
    *,
    enrollment: bool = False,
    recovery: bool = False,
) -> EmployeeSession:
    service = EmployeeAuthService(container.settings)
    token = preauth(request, service)
    # Credential-wide attempts survive new preauth flows, API restarts and IP changes.
    async with db.begin():
        challenge = await db.get(AuthChallenge, service.digest(token))
        credential = (
            await db.get(EmployeeCredential, challenge.credential_id)
            if (challenge and challenge.credential_id)
            else None
        )
        identifier = credential.login_name if credential else "unknown-mfa"
    await service.rate(db, ip=ip(request), identifier=identifier)
    token, codes = await service.finish(
        db, token, payload.code, enrollment=enrollment, recovery=recovery
    )
    cookie(response, COOKIE, token, container.settings.auth_session_absolute_seconds)
    clear_cookie(response, PRE_COOKIE)
    return EmployeeSession(
        stage="authenticated", csrf_token=service.csrf(token), recovery_codes=codes
    )


@router.post("/mfa/verify", response_model=EmployeeSession)
async def verify(
    payload: EmployeeCode, request: Request, response: Response, db: DbDep, container: ContainerDep
) -> EmployeeSession:
    return await complete(payload, request, response, db, container, enrollment=True)


@router.post("/mfa/challenge", response_model=EmployeeSession)
async def challenge(
    payload: EmployeeCode, request: Request, response: Response, db: DbDep, container: ContainerDep
) -> EmployeeSession:
    return await complete(payload, request, response, db, container)


@router.post("/recovery", response_model=EmployeeSession)
async def recovery(
    payload: EmployeeCode, request: Request, response: Response, db: DbDep, container: ContainerDep
) -> EmployeeSession:
    return await complete(payload, request, response, db, container, recovery=True)


@router.post("/logout")
async def logout(
    request: Request, response: Response, db: DbDep, container: ContainerDep
) -> dict[str, bool]:
    service = EmployeeAuthService(container.settings)
    token = request.cookies.get(COOKIE) or request.cookies.get(PRE_COOKIE) or ""
    if token:
        service.require_csrf(
            token, request.headers.get("X-CSRF-Token"), request.headers.get("Origin")
        )
        async with db.begin():
            row = await db.scalar(
                select(AppSession)
                .where(AppSession.token_hash == service.digest(token), AppSession.source == SOURCE)
                .with_for_update()
            )
            if row and row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)
                audit(db, "logout", row.user_id)
                audit(db, "session_revoked", row.user_id)
            await db.execute(
                update(AuthChallenge)
                .where(AuthChallenge.token_hash == service.digest(token))
                .values(consumed_at=datetime.now(UTC), encrypted_totp_secret=None)
            )
    elif request.headers.get("Origin") != container.settings.public_base_url.rstrip("/"):
        service.require_csrf("", None, None)
    clear_cookie(response, COOKIE)
    clear_cookie(response, PRE_COOKIE)
    return {"logged_out": True}
