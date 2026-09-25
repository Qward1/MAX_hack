"""Статус заявки в домовом чате и «Меня тоже касается» (B-06, D3).

Одно сообщение бота на заявку и только когда она возникла по решению
человека: оператор создал её из сигнала чата или житель отправил `/report` в
группе (BOT-VOICE-HUMAN-2026-09-27). Настройка чата «Статусы заявок» должна
быть включена. Текст — категория, подъезд, номер и состояние; текстов и имён
жителей нет. При смене статуса и при новом участнике сообщение правится, а не
отправляется заново.

Кнопка «Меня тоже касается» — callback в группе. Кто нажал, известно из
подписанного события MAX; участие в чате проверяется точечно (D1), затем
житель присоединяется к проблеме тем же `join`, что и в mini app: он
становится участником и получает личные уведомления о ходе работы.
Устаревшая кнопка ничего не меняет, ошибка MAX заявку не откатывает.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.messaging import MessageButton, MessagingError, PersonalMessage
from domsignal.contracts.common import ContractModel
from domsignal.db.models import (
    ChatBinding,
    Incident,
    MAXChat,
    NotificationDelivery,
    OutboxMessage,
    Report,
    Signal,
    Ticket,
    WorkAttempt,
)
from domsignal.db.models.notifications import TICKET_CHAT_PURPOSE
from domsignal.services.chat_settings import allows
from domsignal.services.community_texts import (
    ME_TOO_ALREADY,
    ME_TOO_CLOSED,
    ME_TOO_ERROR,
    ME_TOO_JOINED,
    ME_TOO_JOINED_NO_DIALOG,
    ME_TOO_LABEL,
    ME_TOO_NOT_RESIDENT,
    ME_TOO_STALE,
    OPEN_LABEL,
    ticket_chat_text,
)
from domsignal.services.errors import AccessDenied, ResourceNotFound

if TYPE_CHECKING:
    from domsignal.services.notifications import TicketNotificationHandler
    from domsignal.services.reports import ReportService
    from domsignal.services.resident_access import ResidentAccessService

logger = logging.getLogger(__name__)

#: Вид записи outbox: пост о заявке в домовой чат.
TICKET_CHAT_INTENT_KIND = "chat.ticket_status.v1"
#: Префикс `launch_ref` поста: «Открыть» в mini app и ключ кнопки.
TICKET_CHAT_REF_PREFIX = "t_"
#: Задача нажатия кнопки в группе (операционный пул).
GROUP_CALLBACK_JOB = "chat.callback"
#: Нажатие кнопки поста в группе: `g:<действие>:<ссылка поста>`.
GROUP_CALLBACK = re.compile(r"g:([a-z]{1,10}):(t_[A-Za-z0-9_-]{32})")

CLOSED_STATUSES = frozenset({"closed", "cancelled"})


class TicketChatIntent(ContractModel):
    ticket_id: UUID
    chat_binding_id: UUID
    binding_version: int = Field(ge=1)


async def enqueue_ticket_post(
    session: AsyncSession, *, ticket_id: UUID, chat_binding_id: UUID, binding_version: int
) -> None:
    """Поставить пост о заявке в outbox один раз на заявку. Транзакция — у вызывающего."""
    intent = TicketChatIntent(
        ticket_id=ticket_id, chat_binding_id=chat_binding_id, binding_version=binding_version
    )
    await session.execute(
        insert(OutboxMessage)
        .values(
            id=uuid4(),
            kind=TICKET_CHAT_INTENT_KIND,
            aggregate_id=ticket_id,
            payload=intent.model_dump(mode="json"),
            status="pending",
            dedupe_key=f"ticket-chat:{ticket_id}",
        )
        .on_conflict_do_nothing(index_elements=[OutboxMessage.dedupe_key])
    )


async def participants(session: AsyncSession, incident_id: UUID) -> int:
    """Жители-участники проблемы: авторы своих сообщений, не решений оператора."""
    from_signal = select(Signal.id).where(Signal.report_id == Report.id).exists().correlate(Report)
    rows = await session.execute(
        select(Report.author_id, func.bool_and(from_signal))
        .where(Report.incident_id == incident_id)
        .group_by(Report.author_id)
    )
    return sum(1 for _, signal_only in rows if not signal_only)


def render_version(ticket: Ticket, count: int) -> int:
    """Версия текста поста: растёт и со статусом, и с числом участников."""
    return ticket.version + count


async def touch_ticket_chat(session: AsyncSession, incident_id: UUID) -> None:
    """Пост о заявке догоняет текущее состояние правкой (статус, участники)."""
    rows = (
        await session.execute(
            select(NotificationDelivery, Ticket)
            .join(Ticket, Ticket.id == NotificationDelivery.ticket_id)
            .where(
                Ticket.incident_id == incident_id,
                NotificationDelivery.purpose == TICKET_CHAT_PURPOSE,
            )
            .with_for_update(of=NotificationDelivery)
        )
    ).all()
    if not rows:
        return
    count = await participants(session, incident_id)
    for delivery, ticket in rows:
        version = render_version(ticket, count)
        if delivery.desired_version < version:
            delivery.desired_version = version


async def ticket_chat_message(
    session: AsyncSession, delivery: NotificationDelivery
) -> tuple[str, PersonalMessage, int, Ticket]:
    """Текущий текст поста о заявке. Неактивный чат или выключенная настройка — отказ."""
    binding = await session.scalar(
        select(ChatBinding)
        .where(ChatBinding.id == delivery.chat_binding_id)
        .execution_options(populate_existing=True)
    )
    ticket = await session.get(Ticket, delivery.ticket_id, populate_existing=True)
    if binding is None or ticket is None or binding.status != "active":
        raise ResourceNotFound("CHAT_BINDING_INACTIVE")
    if binding.house_id != ticket.house_id or binding.management_id != ticket.management_id:
        raise ResourceNotFound("CHAT_BINDING_INACTIVE")
    chat = await session.scalar(
        select(MAXChat)
        .where(MAXChat.max_chat_id == binding.max_chat_id)
        .execution_options(populate_existing=True)
    )
    if chat is None or not chat.bot_present:
        raise ResourceNotFound("CHAT_BINDING_INACTIVE")
    if not allows(binding, "ticket_status"):
        raise ResourceNotFound("CHAT_SETTING_OFF")
    incident = await session.get(Incident, ticket.incident_id)
    assert incident is not None
    attempt = (
        await session.get(WorkAttempt, ticket.latest_attempt_id)
        if ticket.latest_attempt_id
        else None
    )
    count = await participants(session, ticket.incident_id)
    from domsignal.services.navigator import category_title

    text = ticket_chat_text(
        number=ticket.number,
        category_title=category_title(incident.category),
        entrance=incident.location_entrance,
        status=ticket.status,
        returned=bool(attempt and attempt.rework_required),
        participants=count,
    )
    rows: list[tuple[MessageButton, ...]] = []
    if ticket.status not in CLOSED_STATUSES:
        rows.append((MessageButton("callback", ME_TOO_LABEL, f"g:me:{delivery.launch_ref}"),))
    rows.append((MessageButton("open_app", OPEN_LABEL, delivery.launch_ref),))
    return (
        binding.max_chat_id,
        PersonalMessage(text, tuple(rows)),
        render_version(ticket, count),
        ticket,
    )


def new_delivery(
    outbox_id: UUID, intent: TicketChatIntent, *, desired_version: int
) -> NotificationDelivery:
    return NotificationDelivery(
        id=uuid4(),
        outbox_message_id=outbox_id,
        recipient_user_id=None,
        channel="max",
        purpose=TICKET_CHAT_PURPOSE,
        ticket_id=intent.ticket_id,
        chat_binding_id=intent.chat_binding_id,
        launch_ref=TICKET_CHAT_REF_PREFIX + secrets.token_urlsafe(24),
        status="pending",
        desired_version=desired_version,
    )


@dataclass(frozen=True)
class GroupCallbackPayload:
    event_id: str
    callback_id: str
    actor: str
    chat_id: str
    message_id: str
    action: str
    ref: str

    @classmethod
    def parse(cls, payload: dict[str, Any]) -> GroupCallbackPayload:
        return cls(**{key: str(payload[key]) for key in cls.__dataclass_fields__})


class TicketChatService:
    """Нажатие «Меня тоже касается» в посте о заявке."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        reports: ReportService,
        resident_access: ResidentAccessService,
        notifications: TicketNotificationHandler,
        answer_enabled: bool,
    ) -> None:
        self.sessions = session_factory
        self.reports = reports
        self.resident_access = resident_access
        # Ответ на нажатие — тем же провайдером сообщений, что и доставка.
        self.notifications = notifications
        self.answer_enabled = answer_enabled

    async def handle_callback(self, payload: dict[str, Any]) -> None:
        callback = GroupCallbackPayload.parse(payload)
        text = await self._me_too(callback) if callback.action == "me" else ME_TOO_STALE
        logger.info("group_callback_handled", extra={"action": callback.action})
        if not self.answer_enabled:
            return
        try:
            await self.notifications.provider.notify_callback(callback.callback_id, text)
        except MessagingError as exc:
            # Отметка уже сохранена; всплывающий ответ не обязателен.
            logger.warning("group_callback_answer_failed", extra={"code": exc.code})

    async def _me_too(self, callback: GroupCallbackPayload) -> str:
        from domsignal.services.reports import IncidentClosed
        from domsignal.services.resident_access import ensure_max_user

        async with self.sessions() as session, session.begin():
            delivery = await session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.launch_ref == callback.ref,
                    NotificationDelivery.purpose == TICKET_CHAT_PURPOSE,
                )
            )
            if delivery is None or delivery.provider_message_id != callback.message_id:
                return ME_TOO_STALE
            binding = await session.get(ChatBinding, delivery.chat_binding_id)
            ticket = await session.get(Ticket, delivery.ticket_id)
            if binding is None or ticket is None or binding.max_chat_id != callback.chat_id:
                return ME_TOO_STALE
            if ticket.status in CLOSED_STATUSES:
                return ME_TOO_CLOSED
            user = await ensure_max_user(session, callback.actor, None)
            user_id, incident_id, house_id = user.id, ticket.incident_id, ticket.house_id
        # Участие в чате проверяется точечно, как у `/report` (D1).
        await self.resident_access.refresh(user_id, chat_ids=(callback.chat_id,))
        async with self.sessions() as session:
            try:
                context = await self.reports.memberships.require_house(
                    session, user_id=user_id, house_id=house_id
                )
            except (AccessDenied, ResourceNotFound):
                return ME_TOO_NOT_RESIDENT
            if not context.resident_access:
                return ME_TOO_NOT_RESIDENT
            own = await session.scalar(
                select(Report.id)
                .where(
                    Report.incident_id == incident_id,
                    Report.author_id == user_id,
                    ~select(Signal.id).where(Signal.report_id == Report.id).exists(),
                )
                .limit(1)
            )
            if own is not None:
                return ME_TOO_ALREADY
        async with self.sessions() as session:
            try:
                await self.reports.join(
                    session,
                    actor_id=user_id,
                    incident_id=incident_id,
                    idempotency_key=f"chat-join:{incident_id}:{user_id}"[:200],
                )
            except IncidentClosed:
                return ME_TOO_CLOSED
            except (AccessDenied, ResourceNotFound):
                return ME_TOO_NOT_RESIDENT
            except Exception as exc:  # noqa: BLE001 - кнопка отвечает и при сбое
                logger.error("me_too_failed", extra={"error_type": type(exc).__name__})
                return ME_TOO_ERROR
        async with self.sessions() as session:
            from domsignal.db.models import User

            user_row = await session.get(User, user_id)
            ready = bool(user_row and (user_row.dialog_open or user_row.max_identity_verified_at))
        return ME_TOO_JOINED if ready else ME_TOO_JOINED_NO_DIALOG


__all__ = [
    "GROUP_CALLBACK",
    "GROUP_CALLBACK_JOB",
    "TICKET_CHAT_INTENT_KIND",
    "TICKET_CHAT_REF_PREFIX",
    "TicketChatIntent",
    "TicketChatService",
    "enqueue_ticket_post",
    "new_delivery",
    "participants",
    "render_version",
    "ticket_chat_message",
    "touch_ticket_chat",
]
