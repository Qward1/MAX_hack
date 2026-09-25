"""Ежедневная сводка сотрудникам (D3).

В 09:00 МСК — личное сообщение в MAX сотрудникам, которые включили сводку в
кабинете и которым бот может написать: новые сигналы за сутки по силе,
заявки без исполнителя, ожидающие проверки жителями, возвращённые в работу и
ссылка в кабинет. Пустой день — без сообщения. Только числа по домам, к
которым у сотрудника есть доступ; Audit Pool не считается (инвариант №7).

Текст снимается в момент сводки; перед отправкой проверяется, что сотрудник
по-прежнему в УК и не выключил сводку.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.messaging import PersonalMessage
from domsignal.contracts.community import StaffSettings, StaffSettingsUpdate
from domsignal.core.quiet_hours import MSK
from domsignal.db.models import (
    ManagementCompany,
    NotificationDelivery,
    OrganizationMembership,
    OutboxMessage,
    Signal,
    Ticket,
    User,
    WorkAttempt,
)
from domsignal.db.models.notifications import STAFF_DIGEST_PURPOSE
from domsignal.services.broadcasts import dialog_ready
from domsignal.services.community_delivery import max_destination
from domsignal.services.community_texts import (
    DIGEST_LEAD,
    DIGEST_LINK,
    DIGEST_RETURNED,
    DIGEST_SIGNALS,
    DIGEST_UNASSIGNED,
    DIGEST_VERIFICATION,
)
from domsignal.services.errors import RescheduleJob, ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.services.onboarding import require_company

logger = logging.getLogger(__name__)

TICK_JOB = "staff.digest.tick"
OUTBOX_KIND = "staff.digest.v1"
REF_PREFIX = "d_"
ACTIVE_TICKETS = (
    "new",
    "accepted",
    "in_progress",
    "verification_pending",
    "needs_clarification",
    "waiting_external",
)


def next_run(now: datetime, hour: int) -> datetime:
    """Ближайшие `hour`:00 по Москве строго после `now`."""
    local = now.astimezone(MSK)
    candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate.astimezone(UTC)


class DigestService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        public_base_url: str | None,
        hour_msk: int = 9,
    ) -> None:
        self.sessions = session_factory
        self.public_base_url = public_base_url
        self.hour = hour_msk
        self.memberships = MembershipService()

    # ------------------------------------------------------------ настройка

    async def settings(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID
    ) -> StaffSettings:
        membership = await require_company(session, actor_id, company_id, admin=False)
        user = await session.get(User, actor_id)
        return StaffSettings(
            daily_digest_enabled=membership.daily_digest_enabled,
            max_linked=bool(user and dialog_ready(user)),
        )

    async def update_settings(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        payload: StaffSettingsUpdate,
    ) -> StaffSettings:
        membership = await require_company(session, actor_id, company_id, admin=False)
        membership.daily_digest_enabled = payload.daily_digest_enabled
        await session.flush()
        return await self.settings(session, actor_id=actor_id, company_id=company_id)

    # ----------------------------------------------------------------- сводка

    async def tick(self, payload: dict[str, Any], *, now: datetime | None = None) -> None:
        del payload
        at = now or datetime.now(UTC)
        await self.run(now=at)
        raise RescheduleJob(next_run(at, self.hour))

    async def run(self, *, now: datetime | None = None, company_id: UUID | None = None) -> int:
        """Поставить сводки дня. Возвращает число поставленных сообщений."""
        at = now or datetime.now(UTC)
        day = at.astimezone(MSK).strftime("%d.%m.%Y")
        queued = 0
        async with self.sessions() as session, session.begin():
            query = (
                select(OrganizationMembership, User, ManagementCompany)
                .join(User, User.id == OrganizationMembership.user_id)
                .join(ManagementCompany, ManagementCompany.id == OrganizationMembership.tenant_id)
                .where(
                    OrganizationMembership.status == "active",
                    OrganizationMembership.daily_digest_enabled.is_(True),
                    ManagementCompany.status == "active",
                )
                .order_by(ManagementCompany.id, User.id)
            )
            if company_id is not None:
                query = query.where(OrganizationMembership.tenant_id == company_id)
            for membership, user, company in (await session.execute(query)).tuples():
                if not dialog_ready(user):
                    continue
                text = await self._text(session, user.id, company, day, at)
                if text is None:
                    continue  # Пустой день — без сообщения.
                key = f"digest:{at.astimezone(MSK).date().isoformat()}:{company.id}:{user.id}"
                outbox_id = uuid4()
                inserted = await session.scalar(
                    insert(OutboxMessage)
                    .values(
                        id=outbox_id,
                        kind=OUTBOX_KIND,
                        aggregate_id=membership.id,
                        payload={"text": text, "company_id": str(company.id)},
                        status="processed",
                        dedupe_key=key[:100],
                    )
                    .on_conflict_do_nothing(index_elements=[OutboxMessage.dedupe_key])
                    .returning(OutboxMessage.id)
                )
                if inserted is None:
                    continue  # Сводка этого дня уже поставлена.
                session.add(
                    NotificationDelivery(
                        id=uuid4(),
                        outbox_message_id=outbox_id,
                        recipient_user_id=user.id,
                        channel="max",
                        purpose=STAFF_DIGEST_PURPOSE,
                        reply_event_id=key,
                        launch_ref=REF_PREFIX + secrets.token_urlsafe(24),
                        status="pending",
                        desired_version=0,
                    )
                )
                queued += 1
        logger.info("staff_digest_queued", extra={"count": queued})
        return queued

    async def _text(
        self,
        session: AsyncSession,
        user_id: UUID,
        company: ManagementCompany,
        day: str,
        at: datetime,
    ) -> str | None:
        houses = [
            house.id
            for house, context in await self.memberships.contexts_with(
                session, user_id=user_id, permission="ticket.read"
            )
            if context.tenant_id.value == company.id
        ]
        if not houses:
            return None
        signals = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Signal.strength, func.count())
                    .where(
                        Signal.house_id.in_(houses),
                        Signal.disposition == "inbox",
                        Signal.strength != "filtered",
                        Signal.created_at >= at - timedelta(days=1),
                        Signal.created_at < at,
                    )
                    .group_by(Signal.strength)
                )
            )
        }
        managed = and_(Ticket.house_id.in_(houses))
        unassigned = await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(managed, Ticket.status.in_(ACTIVE_TICKETS), Ticket.assignee_id.is_(None))
        )
        verification = await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(managed, Ticket.status == "verification_pending")
        )
        returned = await session.scalar(
            select(func.count())
            .select_from(Ticket)
            .join(WorkAttempt, WorkAttempt.id == Ticket.latest_attempt_id)
            .where(managed, Ticket.status == "in_progress", WorkAttempt.rework_required.is_(True))
        )
        total = sum(signals.values())
        if not (total or unassigned or verification or returned):
            return None
        lines = [
            DIGEST_LEAD.format(day=day, company=company.name),
            DIGEST_SIGNALS.format(
                total=total,
                critical=signals.get("critical", 0),
                strong=signals.get("strong", 0),
                medium=signals.get("medium", 0),
                weak=signals.get("weak", 0),
            ),
            DIGEST_UNASSIGNED.format(count=unassigned or 0),
            DIGEST_VERIFICATION.format(count=verification or 0),
            DIGEST_RETURNED.format(count=returned or 0),
        ]
        base = (self.public_base_url or "").strip().rstrip("/")
        if base:
            lines.append(DIGEST_LINK.format(url=f"{base}/admin/"))
        return "\n".join(lines)

    async def snapshot(
        self, session: AsyncSession, delivery: NotificationDelivery
    ) -> tuple[str, PersonalMessage, int]:
        outbox = await session.get(OutboxMessage, delivery.outbox_message_id)
        if outbox is None:
            raise ResourceNotFound("INVALID_INTENT")
        company_id = UUID(str(outbox.payload.get("company_id")))
        membership = await session.scalar(
            select(OrganizationMembership)
            .join(ManagementCompany, ManagementCompany.id == OrganizationMembership.tenant_id)
            .where(
                OrganizationMembership.user_id == delivery.recipient_user_id,
                OrganizationMembership.tenant_id == company_id,
                OrganizationMembership.status == "active",
                ManagementCompany.status == "active",
            )
            .execution_options(populate_existing=True)
        )
        if membership is None or not membership.daily_digest_enabled:
            raise ResourceNotFound("ACCESS_REVOKED")
        user = await session.get(User, delivery.recipient_user_id, populate_existing=True)
        if user is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        return max_destination(user, delivery), PersonalMessage(str(outbox.payload["text"]), ()), 0


__all__ = ["DigestService", "TICK_JOB", "next_run"]
