"""Сопровождение обращения во внешний канал (A-09, минимально, D3).

Через `APPEAL_FOLLOWUP_DAYS` (по умолчанию 14) после отметки «Я отправил»
бот спрашивает в личке: «Пришёл ли ответ?» — «Решено», «Ответ пришёл, не
решено», «Ответа нет». Два последних ответа ведут к следующему шагу только из
справочника: другие проверенные каналы того же маршрута с источником; если их
нет — «Сообщить в УК» или разбор у диспетчера. Юридических сроков текст не
называет: это напоминание, а не отсчёт нормы.

Вопрос не отправляется, если житель уже ответил или проблема закрыта; доступ и
состояние перепроверяются перед самой отправкой. Время в проверках задаётся
явно (`now`) — тесты не ждут суток.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.contracts.routing import LocationScope
from domsignal.db.models import (
    AppealDraft,
    Incident,
    NotificationDelivery,
    OutboxMessage,
    Report,
    RouteOutcome,
    User,
)
from domsignal.db.models.notifications import APPEAL_FOLLOWUP_PURPOSE
from domsignal.services.bot_replies import OPEN_APP_PAYLOAD, ReplyButton
from domsignal.services.community_delivery import max_destination
from domsignal.services.community_texts import (
    FOLLOWUP_ALREADY,
    FOLLOWUP_ANSWERED_LABEL,
    FOLLOWUP_NEXT_LEAD,
    FOLLOWUP_NO_CHANNELS,
    FOLLOWUP_NONE_LABEL,
    FOLLOWUP_QUESTION,
    FOLLOWUP_REPORT_LABEL,
    FOLLOWUP_RESOLVED,
    FOLLOWUP_RESOLVED_LABEL,
    OPEN_APP_LABEL,
    moment,
)
from domsignal.services.errors import RescheduleJob, ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.services.routing import RoutingService

logger = logging.getLogger(__name__)

TICK_JOB = "appeal.followup.tick"
TICK_INTERVAL = timedelta(minutes=15)
OUTBOX_KIND = "appeal.followup.v1"
REF_PREFIX = "f_"
KEY_PREFIX = "followup:"
#: Кнопка ответа: `b:fu:<черновик>:<ответ>`.
CALLBACK_ACTION = "fu"
ANSWERS = {"resolved": "resolved", "answered": "answered_unresolved", "none": "no_answer"}
BATCH = 100


def followup_key(draft_id: UUID) -> str:
    return f"{KEY_PREFIX}{draft_id}"


class FollowupService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        routing: RoutingService,
    ) -> None:
        self.sessions = session_factory
        self.routing = routing
        self.memberships = MembershipService()

    # ----------------------------------------------------------------- тик

    async def tick(self, payload: dict[str, Any], *, now: datetime | None = None) -> None:
        """Поставить вопросы, срок которых наступил; затем перенести себя."""
        del payload
        at = now or datetime.now(UTC)
        await self.enqueue_due(now=at)
        raise RescheduleJob(at + TICK_INTERVAL)

    async def enqueue_due(self, *, now: datetime | None = None) -> int:
        """Вопросы по черновикам со сроком ≤ `now`. Возвращает число поставленных."""
        at = now or datetime.now(UTC)
        queued = 0
        async with self.sessions() as session, session.begin():
            drafts = list(
                await session.scalars(
                    select(AppealDraft)
                    .where(
                        AppealDraft.followup_due_at.is_not(None),
                        AppealDraft.followup_due_at <= at,
                        AppealDraft.followup_sent_at.is_(None),
                        AppealDraft.followup_answer.is_(None),
                        AppealDraft.filed_at.is_not(None),
                    )
                    .order_by(AppealDraft.followup_due_at, AppealDraft.id)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            for draft in drafts:
                draft.followup_sent_at = at
                if await self._closed(session, draft):
                    # Проблема закрыта — спрашивать не о чем.
                    continue
                outbox = OutboxMessage(
                    id=uuid4(),
                    kind=OUTBOX_KIND,
                    aggregate_id=draft.id,
                    payload={"draft_id": str(draft.id)},
                    status="processed",
                    dedupe_key=followup_key(draft.id),
                )
                session.add(outbox)
                await session.flush()
                session.add(
                    NotificationDelivery(
                        id=uuid4(),
                        outbox_message_id=outbox.id,
                        recipient_user_id=draft.author_id,
                        channel="max",
                        purpose=APPEAL_FOLLOWUP_PURPOSE,
                        reply_event_id=followup_key(draft.id),
                        launch_ref=REF_PREFIX + secrets.token_urlsafe(24),
                        status="pending",
                        desired_version=0,
                    )
                )
                queued += 1
        if queued:
            logger.info("appeal_followups_queued", extra={"count": queued})
        return queued

    @staticmethod
    async def _closed(session: AsyncSession, draft: AppealDraft) -> bool:
        outcome = await session.get(RouteOutcome, draft.route_outcome_id)
        if outcome is None or outcome.report_id is None:
            return False
        status = await session.scalar(
            select(Incident.status)
            .join(Report, Report.incident_id == Incident.id)
            .where(Report.id == outcome.report_id)
        )
        return status == "closed"

    # ------------------------------------------------------------- доставка

    async def snapshot(
        self, session: AsyncSession, delivery: NotificationDelivery
    ) -> tuple[str, PersonalMessage, int]:
        """Вопрос «Пришёл ли ответ?»: житель ещё не ответил и проблема не закрыта."""
        key = delivery.reply_event_id or ""
        try:
            draft_id = UUID(key.removeprefix(KEY_PREFIX))
        except ValueError:
            raise ResourceNotFound("INVALID_INTENT") from None
        draft = await session.get(AppealDraft, draft_id, populate_existing=True)
        if draft is None or draft.author_id != delivery.recipient_user_id:
            raise ResourceNotFound("ACCESS_REVOKED")
        if draft.followup_answer is not None or await self._closed(session, draft):
            raise ResourceNotFound("RETRACTED")
        await self._context(session, draft)
        user = await session.get(User, draft.author_id, populate_existing=True)
        if user is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        destination = max_destination(user, delivery)
        assert draft.filed_at is not None
        text = FOLLOWUP_QUESTION.format(when=moment(draft.filed_at))
        buttons = tuple(
            (MessageButton("callback", label, f"b:{CALLBACK_ACTION}:{draft.id}:{answer}"),)
            for label, answer in (
                (FOLLOWUP_RESOLVED_LABEL, "resolved"),
                (FOLLOWUP_ANSWERED_LABEL, "answered"),
                (FOLLOWUP_NONE_LABEL, "none"),
            )
        )
        return destination, PersonalMessage(text, buttons), 0

    async def _context(self, session: AsyncSession, draft: AppealDraft) -> None:
        """Житель по-прежнему имеет доступ к дому черновика."""
        await self.memberships.require_house(
            session, user_id=draft.author_id, house_id=draft.house_id
        )

    # ---------------------------------------------------------------- ответ

    async def answer(
        self, user_id: UUID, argument: str | None
    ) -> tuple[str, list[list[ReplyButton]]]:
        """Кнопка ответа в личке: запись ответа и следующий шаг из справочника."""
        draft_ref, _, choice = (argument or "").partition(":")
        answer = ANSWERS.get(choice)
        try:
            draft_id = UUID(draft_ref)
        except ValueError:
            answer = None
        if answer is None:
            return FOLLOWUP_ALREADY, []
        async with self.sessions() as session, session.begin():
            draft = await session.get(AppealDraft, draft_id, with_for_update=True)
            if draft is None or draft.author_id != user_id:
                return FOLLOWUP_ALREADY, []
            if draft.followup_answer is not None:
                return FOLLOWUP_ALREADY, [[_open_app()]]
            draft.followup_answer = answer
            draft.followup_answered_at = datetime.now(UTC)
            if answer == "resolved":
                return FOLLOWUP_RESOLVED, [[_open_app()]]
            return await self._next_step(session, draft)

    async def _next_step(
        self, session: AsyncSession, draft: AppealDraft
    ) -> tuple[str, list[list[ReplyButton]]]:
        outcome = await session.get(RouteOutcome, draft.route_outcome_id)
        channels = []
        if outcome is not None:
            route, _ = await self.routing.route_for_house(
                session,
                house_id=draft.house_id,
                subtype=outcome.subtype,
                location_scope=_scope(outcome.location_scope),
            )
            channels = [
                channel
                for channel in route.channels
                if channel.id != outcome.channel_id and channel.verification_status == "verified"
            ]
        if not channels:
            return FOLLOWUP_NO_CHANNELS, [
                [ReplyButton(kind="open_app", text=FOLLOWUP_REPORT_LABEL, payload=OPEN_APP_PAYLOAD)]
            ]
        lines = [FOLLOWUP_NEXT_LEAD]
        for channel in channels[:3]:
            where = channel.url or channel.phone or channel.entry_hint or ""
            source = channel.source_title or "справочник ДомСигнала"
            checked = (
                f", проверено {channel.verified_at.strftime('%d.%m.%Y')}"
                if channel.verified_at
                else ""
            )
            lines.append(
                f"• {channel.label}{': ' + where if where else ''} (источник: {source}{checked})"
            )
        return "\n".join(lines)[:3900], [[_open_app()]]


def _open_app() -> ReplyButton:
    return ReplyButton(kind="open_app", text=OPEN_APP_LABEL, payload=OPEN_APP_PAYLOAD)


def _scope(value: str) -> LocationScope:
    from domsignal.contracts.routing import LOCATION_SCOPES

    return value if value in LOCATION_SCOPES else "unknown"


__all__ = [
    "CALLBACK_ACTION",
    "FollowupService",
    "TICK_JOB",
    "followup_key",
]
