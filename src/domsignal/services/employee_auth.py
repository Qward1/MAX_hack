from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from domsignal.db.models import (
    AppSession,
    AuthChallenge,
    AuthRateLimit,
    EmployeeCredential,
    InboxReceipt,
    OrganizationMembership,
    RecoveryCode,
    User,
)
from domsignal.services.errors import AccessDenied, AuthenticationRequired, FeatureUnavailable
from domsignal.services.sessions import AuthenticatedUser
from domsignal.settings import Settings

SOURCE = "employee_password_mfa"
COOKIE = "__Host-domsignal_employee"
PRE_COOKIE = "__Host-domsignal_preauth"
HASHER = PasswordHasher()
# Same verification cost for unknown, revoked and valid identifiers.
DUMMY_HASH = HASHER.hash(secrets.token_urlsafe(32))
PASSWORD_WORKERS = threading.BoundedSemaphore(2)
INVALID = "Неверные данные для входа"


class AuthRateLimited(AuthenticationRequired):
    status = 429
    code = "auth_rate_limited"
    title = "Попробуйте позднее"
    retryable = True


def normalize_login(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,99}", value):
        raise ValueError("Login must be 3-100 ASCII letters, digits, dot, underscore or dash")
    return value


def audit(db: AsyncSession, event: str, user_id: uuid.UUID | None = None) -> None:
    # Existing operator/audit receipt pattern; only allowlisted facts, never request bodies.
    db.add(
        InboxReceipt(
            event_id=f"employee-auth:{uuid.uuid4()}",
            event_type=f"employee_auth.{event}",
            payload={"user_id": str(user_id) if user_id else None},
        )
    )


async def verify_password(encoded: str, password: str) -> bool:
    def bounded_verify() -> bool:
        with PASSWORD_WORKERS:
            return HASHER.verify(encoded, password)

    try:
        return await run_in_threadpool(bounded_verify)
    except (VerificationError, InvalidHashError):
        return False


class EmployeeAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def digest(self, value: str, purpose: str = "token") -> str:
        return hmac.new(
            self.settings.session_secret.encode(), f"{purpose}:{value}".encode(), hashlib.sha256
        ).hexdigest()

    def cipher(self) -> Fernet:
        key = self.settings.auth_mfa_encryption_key
        if not key:
            raise FeatureUnavailable("Employee MFA encryption is not configured")
        return Fernet(key.encode())

    def csrf(self, token: str) -> str:
        return self.digest(token, "csrf")

    def require_csrf(self, token: str, submitted: str | None, origin: str | None) -> None:
        if (
            origin != self.settings.public_base_url.rstrip("/")
            or not token
            or not submitted
            or not hmac.compare_digest(self.csrf(token), submitted)
        ):
            raise AccessDenied("Invalid request origin or CSRF token")

    async def rate(self, db: AsyncSession, *, ip: str, identifier: str) -> None:
        """Own short transaction: failures/rollbacks cannot erase attempt counters.

        Slots 0..65535 are IPs, 65536..131071 identifiers (collisions conservatively
        share a bounded, temporary limit). Forwarded headers are never read here.
        """
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            ip = "unknown"
        slots = [
            (int(self.digest(ip, "rate-ip")[:8], 16) % 65536, 5),
            (65536 + int(self.digest(identifier, "rate-id")[:8], 16) % 65536, 1),
        ]
        now = datetime.now(UTC)
        blocked = False
        async with db.begin():
            for slot, multiplier in slots:
                await db.execute(
                    insert(AuthRateLimit)
                    .values(slot=slot, attempts=0, window_at=now)
                    .on_conflict_do_nothing()
                )
                row = await db.scalar(
                    select(AuthRateLimit).where(AuthRateLimit.slot == slot).with_for_update()
                )
                assert row is not None
                if row.locked_until and row.locked_until > now:
                    blocked = True
                    continue
                if (now - row.window_at).total_seconds() >= self.settings.auth_rate_window_seconds:
                    row.attempts = 0
                    row.window_at = now
                    row.locked_until = None
                row.attempts += 1
                if row.attempts > self.settings.auth_rate_threshold * multiplier:
                    row.locked_until = now + timedelta(
                        seconds=self.settings.auth_rate_backoff_seconds
                    )
                    blocked = True
        if blocked:
            raise AuthRateLimited("Слишком много попыток. Повторите вход позднее.")

    async def reset_rate(self, db: AsyncSession, login: str) -> None:
        slot = 65536 + int(self.digest(login, "rate-id")[:8], 16) % 65536
        await db.execute(
            update(AuthRateLimit)
            .where(AuthRateLimit.slot == slot)
            .values(attempts=0, locked_until=None, window_at=datetime.now(UTC))
        )

    def new_challenge(
        self,
        db: AsyncSession,
        *,
        stage: str,
        credential_id: uuid.UUID | None = None,
        expires_at: datetime | None = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        db.add(
            AuthChallenge(
                token_hash=self.digest(token),
                stage=stage,
                credential_id=credential_id,
                created_at=now,
                expires_at=expires_at
                or now + timedelta(seconds=self.settings.auth_challenge_seconds),
            )
        )
        return token

    async def challenge(
        self,
        db: AsyncSession,
        token: str,
        stages: set[str],
    ) -> tuple[AuthChallenge, EmployeeCredential | None]:
        row = await db.get(AuthChallenge, self.digest(token))
        if row is None:
            raise AuthenticationRequired(INVALID)
        # Fixed lock order across MFA, resets and cookie authentication.
        credential = None
        if row.credential_id:
            credential = await db.scalar(
                select(EmployeeCredential)
                .where(EmployeeCredential.id == row.credential_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if credential is None or credential.revoked_at:
                raise AuthenticationRequired(INVALID)
        await db.refresh(row, with_for_update=True)
        if row.consumed_at or row.expires_at <= datetime.now(UTC) or row.stage not in stages:
            raise AuthenticationRequired(INVALID)
        return row, credential

    async def login(
        self,
        db: AsyncSession,
        token: str,
        login: str,
        password: str,
    ) -> tuple[str, str]:
        error = False
        next_token, stage = "", "login"
        async with db.begin():
            challenge, _ = await self.challenge(db, token, {"login"})
            credential = await db.scalar(
                select(EmployeeCredential)
                .where(EmployeeCredential.login_name == login)
                .with_for_update()
            )
            valid = await verify_password(
                credential.password_hash if credential else DUMMY_HASH, password
            )
            now = datetime.now(UTC)
            if (
                not credential
                or not valid
                or credential.revoked_at
                or (
                    credential.password_change_required
                    and (
                        credential.temporary_used_at is not None
                        or credential.temporary_expires_at is None
                        or credential.temporary_expires_at <= now
                    )
                )
            ):
                audit(db, "login_failure")
                error = True
            else:
                if credential.password_change_required:
                    credential.temporary_used_at = now
                elif HASHER.check_needs_rehash(credential.password_hash):
                    credential.password_hash = await run_in_threadpool(HASHER.hash, password)
                challenge.consumed_at = now
                stage = (
                    "password_change"
                    if credential.password_change_required
                    else "mfa_challenge"
                    if credential.mfa_enabled
                    else "mfa_enroll"
                )
                next_token = self.new_challenge(db, stage=stage, credential_id=credential.id)
        if error:
            raise AuthenticationRequired(INVALID)
        return next_token, stage

    async def change_password(self, db: AsyncSession, token: str, password: str) -> tuple[str, str]:
        weak = {
            "passwordpassword",
            "password123456",
            "qwerty12345678",
            "123456789012",
            "administrator",
            "changemechangeme",
            "correct horse battery staple",
        }
        if (
            len(password) < 12
            or len(password) > self.settings.auth_password_max_length
            or password.casefold() in weak
            or len(set(password)) < 5
        ):
            raise AccessDenied("Пароль: минимум 12 символов; выберите длинный уникальный пароль.")
        async with db.begin():
            row, credential = await self.challenge(db, token, {"password_change"})
            assert credential is not None
            if await verify_password(credential.password_hash, password):
                raise AccessDenied("Выберите новый пароль")
            credential.password_hash = await run_in_threadpool(HASHER.hash, password)
            credential.password_changed_at = datetime.now(UTC)
            credential.password_change_required = False
            credential.temporary_expires_at = None
            await self.revoke_sessions(db, credential)
            row.consumed_at = datetime.now(UTC)
            stage = "mfa_challenge" if credential.mfa_enabled else "mfa_enroll"
            next_token = self.new_challenge(
                db, stage=stage, credential_id=credential.id, expires_at=row.expires_at
            )
            audit(db, "password_changed", credential.user_id)
        return next_token, stage

    async def enroll(self, db: AsyncSession, token: str) -> tuple[str, str]:
        async with db.begin():
            row, credential = await self.challenge(db, token, {"mfa_enroll"})
            assert credential is not None
            if credential.mfa_enabled:
                raise AuthenticationRequired(INVALID)
            cipher = self.cipher()
            if row.encrypted_totp_secret is None:
                row.encrypted_totp_secret = cipher.encrypt(pyotp.random_base32().encode()).decode()
            secret = cipher.decrypt(row.encrypted_totp_secret.encode()).decode()
            uri = pyotp.TOTP(secret).provisioning_uri(
                credential.login_name, issuer_name="ДомСигнал"
            )
            return secret, uri

    async def finish(
        self,
        db: AsyncSession,
        token: str,
        code: str,
        *,
        enrollment: bool = False,
        recovery: bool = False,
    ) -> tuple[str, list[str]]:
        codes: list[str] = []
        session_token = ""
        async with db.begin():
            row, credential = await self.challenge(
                db, token, {"mfa_enroll" if enrollment else "mfa_challenge"}
            )
            assert credential is not None
            now = datetime.now(UTC)
            valid = False
            if recovery and credential.mfa_enabled:
                recovery_row = await db.scalar(
                    select(RecoveryCode)
                    .where(
                        RecoveryCode.credential_id == credential.id,
                        RecoveryCode.code_hash == self.digest(code.strip().upper(), "recovery"),
                        RecoveryCode.used_at.is_(None),
                    )
                    .with_for_update()
                )
                if recovery_row:
                    recovery_row.used_at = now
                    valid = True
                    audit(db, "recovery_used", credential.user_id)
            else:
                encrypted = (
                    row.encrypted_totp_secret if enrollment else credential.encrypted_totp_secret
                )
                if encrypted and re.fullmatch(r"[0-9]{6}", code):
                    totp = pyotp.TOTP(self.cipher().decrypt(encrypted.encode()).decode())
                    step = int(now.timestamp()) // 30
                    for candidate in (step - 1, step, step + 1):
                        if (
                            credential.last_totp_step is None
                            or candidate > credential.last_totp_step
                        ) and totp.verify(
                            code, for_time=datetime.fromtimestamp(candidate * 30, UTC)
                        ):
                            credential.last_totp_step = candidate
                            valid = True
                            break
            if not valid or credential.password_change_required:
                audit(db, "mfa_failure", credential.user_id)
            else:
                if enrollment:
                    if credential.mfa_enabled:
                        raise AuthenticationRequired(INVALID)
                    credential.encrypted_totp_secret = row.encrypted_totp_secret
                    credential.mfa_enabled = True
                    codes = [secrets.token_hex(10).upper() for _ in range(10)]
                    db.add_all(
                        [
                            RecoveryCode(
                                credential_id=credential.id, code_hash=self.digest(c, "recovery")
                            )
                            for c in codes
                        ]
                    )
                    audit(db, "mfa_enrolled", credential.user_id)
                audit(db, "mfa_success", credential.user_id)
                await self.reset_rate(db, credential.login_name)
                # Consume every sibling preauth flow, atomically with the final session.
                await db.execute(
                    update(AuthChallenge)
                    .where(
                        AuthChallenge.credential_id == credential.id,
                        AuthChallenge.consumed_at.is_(None),
                    )
                    .values(consumed_at=now, encrypted_totp_secret=None)
                )
                session_token = secrets.token_urlsafe(32)
                db.add(
                    AppSession(
                        token_hash=self.digest(session_token),
                        user_id=credential.user_id,
                        source=SOURCE,
                        created_at=now,
                        last_seen_at=now,
                        idle_expires_at=now
                        + timedelta(seconds=self.settings.auth_session_idle_seconds),
                        expires_at=now
                        + timedelta(seconds=self.settings.auth_session_absolute_seconds),
                    )
                )
                audit(db, "login_success", credential.user_id)
        if not session_token:
            raise AuthenticationRequired("Неверный или уже использованный код")
        return session_token, codes

    async def authenticate(self, db: AsyncSession, token: str) -> AuthenticatedUser:
        async with db.begin():
            row = await db.scalar(
                select(AppSession).where(
                    AppSession.token_hash == self.digest(token), AppSession.source == SOURCE
                )
            )
            if row is None:
                raise AuthenticationRequired(INVALID)
            credential = await db.scalar(
                select(EmployeeCredential)
                .where(EmployeeCredential.user_id == row.user_id)
                .with_for_update()
            )
            await db.refresh(row, with_for_update=True)
            now = datetime.now(UTC)
            if (
                credential is None
                or credential.revoked_at
                or not credential.mfa_enabled
                or credential.password_change_required
                or row.revoked_at
                or row.expires_at <= now
                or row.idle_expires_at is None
                or row.idle_expires_at <= now
            ):
                raise AuthenticationRequired(INVALID)
            user = await db.get(User, row.user_id)
            if user is None:
                raise AuthenticationRequired(INVALID)
            row.last_seen_at = now
            row.idle_expires_at = min(
                row.expires_at, now + timedelta(seconds=self.settings.auth_session_idle_seconds)
            )
            return AuthenticatedUser(id=user.id, display_name=user.display_name)

    async def revoke_sessions(self, db: AsyncSession, credential: EmployeeCredential) -> None:
        now = datetime.now(UTC)
        await db.execute(
            update(AppSession)
            .where(
                AppSession.user_id == credential.user_id,
                AppSession.source == SOURCE,
                AppSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await db.execute(
            update(AuthChallenge)
            .where(
                AuthChallenge.credential_id == credential.id, AuthChallenge.consumed_at.is_(None)
            )
            .values(consumed_at=now, encrypted_totp_secret=None)
        )
        audit(db, "sessions_revoked", credential.user_id)

    async def provision(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        action: str,
        login: str | None = None,
    ) -> str | None:
        """Caller owns transaction. Returns temporary password only for operator output."""
        user = await db.get(User, user_id, with_for_update=True)
        membership = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id, OrganizationMembership.status == "active"
            )
        )
        if user is None or (action in {"create", "reset-password", "reset-mfa"} and not membership):
            raise ValueError("Existing user and active employee membership required")
        credential = await db.scalar(
            select(EmployeeCredential)
            .where(EmployeeCredential.user_id == user_id)
            .with_for_update()
        )
        if action == "create":
            if credential or login is None:
                raise ValueError("Credential already exists or login missing")
            self.cipher()  # Refuse to issue an unusable credential.
            credential = EmployeeCredential(user_id=user_id, login_name=normalize_login(login))
            db.add(credential)
        elif credential is None:
            raise ValueError("Credential does not exist")
        assert credential is not None
        temporary = None
        now = datetime.now(UTC)
        if action != "create":
            await self.revoke_sessions(db, credential)
        if action in {"create", "reset-password"}:
            temporary = secrets.token_urlsafe(24)
            credential.password_hash = await run_in_threadpool(HASHER.hash, temporary)
            credential.password_changed_at = now
            credential.password_change_required = True
            credential.temporary_used_at = None
            credential.temporary_expires_at = now + timedelta(
                seconds=self.settings.auth_temporary_password_seconds
            )
            credential.revoked_at = None
        elif action == "reset-mfa":
            credential.mfa_enabled = False
            credential.encrypted_totp_secret = None
            credential.last_totp_step = None
            await db.execute(
                update(RecoveryCode)
                .where(RecoveryCode.credential_id == credential.id, RecoveryCode.used_at.is_(None))
                .values(used_at=now)
            )
        elif action == "revoke":
            credential.revoked_at = now
        else:
            raise ValueError("Unsupported operator action")
        audit(
            db,
            {
                "create": "credential_provisioned",
                "reset-password": "password_reset",
                "reset-mfa": "mfa_reset",
                "revoke": "credential_revoked",
            }[action],
            user_id,
        )
        return temporary

    async def cleanup(self, db: AsyncSession) -> None:
        # Challenge secrets have a short lifetime; audit is retained separately.
        await db.execute(
            delete(AuthChallenge).where(
                AuthChallenge.expires_at < datetime.now(UTC) - timedelta(days=1)
            )
        )
