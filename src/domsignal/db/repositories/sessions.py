from __future__ import annotations

from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import AppSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, app_session: AppSession) -> None:
        self.session.add(app_session)

    async def active_by_hash(self, token_hash: str, *, now: datetime) -> AppSession | None:
        return cast(
            AppSession | None,
            await self.session.scalar(
                select(AppSession).where(
                    AppSession.token_hash == token_hash,
                    AppSession.expires_at > now,
                    AppSession.revoked_at.is_(None),
                    AppSession.source.in_(["max", "test"]),
                )
            ),
        )
