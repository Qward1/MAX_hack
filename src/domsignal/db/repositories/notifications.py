from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import (
    MaxDestinationLimit,
    NotificationDelivery,
    OutboxMessage,
    Report,
    Signal,
)
from domsignal.db.models.notifications import BROADCAST_PURPOSES

#: Вид outbox-сообщения A-16, из которого рождается доставка по заявке.
TICKET_INTENT_KIND = "ticket.notification_intent.v1"


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def intent(self, kind: str = TICKET_INTENT_KIND) -> OutboxMessage | None:
        return cast(
            OutboxMessage | None,
            await self.session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.kind == kind,
                    OutboxMessage.status == "pending",
                )
                .order_by(OutboxMessage.created_at, OutboxMessage.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )

    async def recipients(self, incident_id: UUID) -> list[tuple[UUID, bool]]:
        """Авторы сообщений проблемы и признак «только решения по сигналу».

        Сообщение, созданное оператором из сигнала чата (`create-ticket` или
        `join`), пишется от имени сотрудника: жителя-получателя за ним нет.
        Автор, у которого есть хоть одно собственное сообщение, — житель.
        """
        from_signal = (
            select(Signal.id).where(Signal.report_id == Report.id).exists().correlate(Report)
        )
        rows = await self.session.execute(
            select(Report.author_id, func.bool_and(from_signal))
            .where(Report.incident_id == incident_id)
            .group_by(Report.author_id)
            .order_by(Report.author_id)
        )
        return [(row[0], bool(row[1])) for row in rows]

    async def affected(self, ticket_id: UUID) -> list[NotificationDelivery]:
        return list(
            await self.session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.ticket_id == ticket_id)
                .order_by(NotificationDelivery.id)
                .with_for_update()
            )
        )

    async def by_outbox(self, outbox_message_id: UUID) -> list[NotificationDelivery]:
        return list(
            await self.session.scalars(
                select(NotificationDelivery)
                .where(NotificationDelivery.outbox_message_id == outbox_message_id)
                .with_for_update()
            )
        )

    async def by_ref(self, ref: str) -> NotificationDelivery | None:
        return cast(
            NotificationDelivery | None,
            await self.session.scalar(
                select(NotificationDelivery).where(NotificationDelivery.launch_ref == ref)
            ),
        )

    async def due(self, now: datetime) -> NotificationDelivery | None:
        d = NotificationDelivery
        return cast(
            NotificationDelivery | None,
            await self.session.scalar(
                select(d)
                .where(
                    or_(d.next_attempt_at.is_(None), d.next_attempt_at <= now),
                    or_(
                        d.status.in_(["pending", "retry_wait"]),
                        and_(d.status == "accepted", d.desired_version > d.applied_version),
                        and_(d.status == "processing", d.lease_until <= now),
                    ),
                )
                # Личные уведомления о заявках и ответы бота — впереди массовых
                # рассылок (D3): длинная рассылка не задерживает работу по заявке.
                .order_by(
                    case((d.purpose.in_(BROADCAST_PURPOSES), 1), else_=0),
                    d.updated_at,
                    d.id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            ),
        )

    async def pace(self, gate: str, now: datetime, *, spacing_ms: int) -> datetime | None:
        """Общий темп: не чаще раза в `spacing_ms` на весь поток ворот `gate`.

        Возвращает момент, до которого ждать, или `None` — можно сейчас (и
        следующий слот уже занят). Аренды нет: цикл воркера последовательный,
        а ворота только разводят начала отправок во времени.
        """
        await self.session.execute(
            insert(MaxDestinationLimit)
            .values(destination=gate, next_allowed_at=now)
            .on_conflict_do_nothing(index_elements=["destination"])
        )
        row = await self.session.scalar(
            select(MaxDestinationLimit)
            .where(MaxDestinationLimit.destination == gate)
            .with_for_update()
        )
        assert row is not None
        if row.next_allowed_at > now:
            return row.next_allowed_at
        row.next_allowed_at = now + timedelta(milliseconds=spacing_ms)
        return None

    async def reserve_destination(
        self,
        destination: str,
        token: UUID,
        now: datetime,
    ) -> datetime | None:
        await self.session.execute(
            insert(MaxDestinationLimit)
            .values(
                destination=destination,
                next_allowed_at=now,
            )
            .on_conflict_do_nothing(index_elements=["destination"])
        )
        gate = await self.session.scalar(
            select(MaxDestinationLimit)
            .where(
                MaxDestinationLimit.destination == destination,
            )
            .with_for_update()
        )
        assert gate is not None
        if gate.lease_until and gate.lease_until > now:
            return gate.lease_until
        if gate.next_allowed_at > now:
            return gate.next_allowed_at
        gate.lease_token = token
        gate.lease_until = now + timedelta(seconds=90)
        gate.next_allowed_at = now + timedelta(milliseconds=500)
        return None

    async def release_destination(self, destination: str, token: UUID, now: datetime) -> None:
        gate = await self.session.scalar(
            select(MaxDestinationLimit)
            .where(
                MaxDestinationLimit.destination == destination,
            )
            .with_for_update()
        )
        if gate and gate.lease_token == token:
            gate.lease_token = None
            gate.lease_until = None
            gate.next_allowed_at = max(gate.next_allowed_at, now + timedelta(milliseconds=500))
