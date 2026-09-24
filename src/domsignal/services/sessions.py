from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.identity import SessionResponse
from domsignal.db.models import AppSession, User
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.sessions import SessionRepository
from domsignal.services.errors import AuthenticationRequired, ResourceNotFound

#: Имя пользователя, пришедшего из вебхука (см. `resident_access`).
MAX_USER_PLACEHOLDER = "Пользователь MAX"


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    display_name: str


class SessionService:
    def __init__(self, *, secret: str, ttl_seconds: int) -> None:
        self.secret = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    async def issue_test_session(self, session: AsyncSession, *, alias: str) -> SessionResponse:
        async with session.begin():
            user = await AccessRepository(session).user_by_demo_alias(alias)
            if user is None:
                raise ResourceNotFound("Demo seed is missing the requested actor")
            return self._issue(session, user=user, source="test")

    async def issue_max_session(
        self,
        session: AsyncSession,
        *,
        max_user_id: str,
        display_name: str,
    ) -> SessionResponse:
        async with session.begin():
            repo = AccessRepository(session)
            user = await repo.user_by_max_id(max_user_id)
            if user is None:
                user = await repo.create_max_user(max_user_id, display_name)
            elif user.display_name == MAX_USER_PLACEHOLDER and display_name.strip():
                # Пользователь из вебхука получает имя из подписанных initData.
                user.display_name = display_name.strip()[:200]
            # Called only after the existing /auth/max signature/age validation.
            user.max_identity_verified_at = datetime.now(UTC)
            return self._issue(session, user=user, source="max")

    async def authenticate(self, session: AsyncSession, *, token: str) -> AuthenticatedUser:
        token_hash = self._hash(token)
        row = await SessionRepository(session).active_by_hash(token_hash, now=datetime.now(UTC))
        if row is None:
            raise AuthenticationRequired("The bearer session is missing, invalid, or expired")
        user = await AccessRepository(session).user_by_id(row.user_id)
        if user is None:
            raise AuthenticationRequired("The session user no longer exists")
        return AuthenticatedUser(id=user.id, display_name=user.display_name)

    def _issue(self, session: AsyncSession, *, user: User, source: str) -> SessionResponse:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        SessionRepository(session).add(
            AppSession(
                token_hash=self._hash(token),
                user_id=user.id,
                source=source,
                expires_at=expires_at,
            )
        )
        return SessionResponse(access_token=token, expires_at=expires_at)

    def _hash(self, token: str) -> str:
        return hmac.new(self.secret, token.encode("utf-8"), hashlib.sha256).hexdigest()
