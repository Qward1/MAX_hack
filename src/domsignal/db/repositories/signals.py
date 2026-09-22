"""Чтения очереди сигналов оператора: только Inbox и только текущая УК дома.

Область — пары «дом + период управления», которые разрешила существующая
политика доступа. Сигнал относится к периоду управления через привязку чата:
новая УК дома не видит сигналов из чата прежней. Audit Pool (`audit_pool`)
этими запросами не читается никогда.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import (
    ChatBinding,
    House,
    Incident,
    RouteOutcome,
    Signal,
    SignalEvent,
    SignalQuote,
    Ticket,
    User,
)
from domsignal.db.models.passive import OPEN_SIGNAL_STATUSES
from domsignal.db.repositories.incidents import OPEN_STATUSES as OPEN_INCIDENT_STATUSES

#: Порядок очереди: критические сверху, внутри силы — свежие первыми.
STRENGTH_ORDER = case(
    (Signal.strength == "critical", 0),
    (Signal.strength == "strong", 1),
    (Signal.strength == "medium", 2),
    else_=3,
)


@dataclass(frozen=True)
class SignalScope:
    """Дом и его текущий период управления, разрешённые сотруднику."""

    house_id: uuid.UUID
    management_id: uuid.UUID


class SignalInboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -------------------------------------------------------------- область

    @staticmethod
    def _scoped(statement: Select[Any], scopes: Sequence[SignalScope]) -> Select[Any]:
        return (
            statement.join(ChatBinding, ChatBinding.id == Signal.chat_binding_id)
            .where(Signal.disposition == "inbox", Signal.strength != "filtered")
            .where(
                or_(
                    *(
                        and_(
                            Signal.house_id == scope.house_id,
                            ChatBinding.management_id == scope.management_id,
                        )
                        for scope in scopes
                    )
                )
            )
        )

    async def signal_house(self, signal_id: uuid.UUID) -> uuid.UUID | None:
        """Только маршрутная метаинформация до проверки доступа."""
        return cast(
            uuid.UUID | None,
            await self.session.scalar(select(Signal.house_id).where(Signal.id == signal_id)),
        )

    async def in_scope(
        self, signal_id: uuid.UUID, scope: SignalScope, *, lock: bool = False
    ) -> Signal | None:
        statement = self._scoped(select(Signal), [scope]).where(Signal.id == signal_id)
        if lock:
            statement = statement.with_for_update(of=Signal).execution_options(
                populate_existing=True
            )
        return cast(Signal | None, await self.session.scalar(statement))

    # --------------------------------------------------------------- список

    async def page(
        self,
        scopes: Sequence[SignalScope],
        *,
        statuses: Sequence[str],
        strengths: Sequence[str],
        limit: int,
        offset: int,
    ) -> tuple[list[Signal], int]:
        if not scopes:
            return [], 0
        statement = self._scoped(select(Signal), scopes)
        if statuses:
            statement = statement.where(Signal.status.in_(statuses))
        if strengths:
            statement = statement.where(Signal.strength.in_(strengths))
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        items = list(
            await self.session.scalars(
                statement.order_by(STRENGTH_ORDER, Signal.last_seen_at.desc(), Signal.id)
                .limit(limit)
                .offset(offset)
            )
        )
        return items, int(total or 0)

    async def strength_counts(
        self, scopes: Sequence[SignalScope], *, statuses: Sequence[str]
    ) -> dict[str, int]:
        if not scopes:
            return {}
        statement = self._scoped(select(Signal.strength, func.count()), scopes)
        if statuses:
            statement = statement.where(Signal.status.in_(statuses))
        rows = await self.session.execute(statement.group_by(Signal.strength))
        return {strength: int(count) for strength, count in rows.tuples()}

    async def attention(
        self, scopes: Sequence[SignalScope]
    ) -> tuple[int, uuid.UUID | None, datetime | None]:
        """Открытые критические сигналы области: число, самый свежий и его время."""
        if not scopes:
            return 0, None, None
        statement = self._scoped(select(Signal.id, Signal.last_seen_at), scopes).where(
            Signal.strength == "critical", Signal.status.in_(OPEN_SIGNAL_STATUSES)
        )
        rows = list(
            (
                await self.session.execute(
                    statement.order_by(Signal.last_seen_at.desc(), Signal.id)
                )
            ).tuples()
        )
        if not rows:
            return 0, None, None
        return len(rows), rows[0][0], rows[0][1]

    # ------------------------------------------------------ связанные данные

    async def houses(self, house_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, House]:
        if not house_ids:
            return {}
        rows = await self.session.scalars(select(House).where(House.id.in_(set(house_ids))))
        return {house.id: house for house in rows}

    async def quotes(self, signal_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[SignalQuote]]:
        result: dict[uuid.UUID, list[SignalQuote]] = {}
        if not signal_ids:
            return result
        rows = await self.session.scalars(
            select(SignalQuote)
            .where(SignalQuote.signal_id.in_(set(signal_ids)))
            .order_by(SignalQuote.sent_at, SignalQuote.id)
        )
        for quote in rows:
            result.setdefault(quote.signal_id, []).append(quote)
        return result

    async def outcomes(self, outcome_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, RouteOutcome]:
        ids = {item for item in outcome_ids if item is not None}
        if not ids:
            return {}
        rows = await self.session.scalars(select(RouteOutcome).where(RouteOutcome.id.in_(ids)))
        return {outcome.id: outcome for outcome in rows}

    async def events(self, signal_id: uuid.UUID, kinds: Sequence[str]) -> list[SignalEvent]:
        return list(
            await self.session.scalars(
                select(SignalEvent)
                .where(SignalEvent.signal_id == signal_id, SignalEvent.kind.in_(kinds))
                .order_by(SignalEvent.created_at, SignalEvent.id)
                .limit(100)
            )
        )

    async def user_names(self, user_ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        ids = {item for item in user_ids if item is not None}
        if not ids:
            return {}
        rows = await self.session.execute(
            select(User.id, User.display_name).where(User.id.in_(ids))
        )
        return {user_id: name for user_id, name in rows.tuples()}

    async def related_incidents(
        self, signal: Signal, scope: SignalScope, *, created_after: datetime
    ) -> list[Incident]:
        """Открытые проблемы, в которые уже превращён такой же сигнал дома.

        Сигнал о той же ветке после решения «создать заявку» рождается заново
        (склейка работает только с открытыми), и первой ему предлагается та
        проблема, которую оператор уже завёл.
        """
        rows = await self.session.scalars(
            select(Incident)
            .join(Signal, Signal.incident_id == Incident.id)
            .where(
                Signal.house_id == signal.house_id,
                Signal.dedupe_key == signal.dedupe_key,
                Signal.id != signal.id,
                Signal.status == "converted",
                Incident.house_id == scope.house_id,
                Incident.management_id == scope.management_id,
                Incident.status.in_(OPEN_INCIDENT_STATUSES),
                Incident.created_at >= created_after,
            )
            .order_by(Signal.decided_at.desc(), Incident.id)
            .limit(3)
        )
        return list(dict.fromkeys(rows))

    async def latest_ticket(self, incident_id: uuid.UUID) -> Ticket | None:
        return cast(
            Ticket | None,
            await self.session.scalar(
                select(Ticket)
                .where(Ticket.incident_id == incident_id)
                .order_by(Ticket.created_at.desc())
                .limit(1)
            ),
        )


__all__ = ["STRENGTH_ORDER", "SignalInboxRepository", "SignalScope"]
