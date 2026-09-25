"""Доставка сообщений D3 через существующий механизм A-05.

Здесь — снимки для новых назначений `NotificationDelivery` и правила времени
отправки. Доступ и состояние перепроверяются перед каждой отправкой и
правкой: отписка, выход из дома, выключенная настройка чата, удалённое
сообщение останавливают доставку с причиной для статистики.

Тихие часы: пост рассылки или опроса в чат и его необязательные правки ждут
конца тихих часов чата; удаление поста правится сразу. Пост о заявке
уходит сразу — факт принятия тихие часы не задерживают, — а правки ждут,
кроме правки «УК приняла в работу». Личные рассылки ночью (22:00–08:00 МСК)
тоже ждут утра.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.core.quiet_hours import quiet_until
from domsignal.db.models import (
    Broadcast,
    BroadcastCompany,
    BroadcastHouse,
    ChatBinding,
    ManagementCompany,
    MAXChat,
    NotificationDelivery,
    OrganizationMembership,
    Poll,
    Ticket,
    User,
)
from domsignal.db.models.notifications import (
    BROADCAST_CHAT_PURPOSE,
    BROADCAST_DM_PURPOSE,
    BROADCAST_STAFF_PURPOSE,
    TICKET_CHAT_PURPOSE,
)
from domsignal.db.repositories.access import AccessRepository
from domsignal.services.broadcasts import dm_quiet_until, poll_closed, tally
from domsignal.services.chat_settings import allows, broadcast_kind
from domsignal.services.community_texts import (
    OPEN_APP_LABEL,
    UNSUBSCRIBE_LABEL,
    VOTE_LABEL,
    OptionLine,
    broadcast_text,
    poll_lines,
    sender_label,
    staff_notice_text,
)
from domsignal.services.errors import ResourceNotFound

#: Коды остановки доставки D3, которые попадают в статистику как есть.
STOP_CODES = frozenset(
    {
        "UNSUBSCRIBED",
        "NO_MAX_IDENTITY",
        "CHAT_SETTING_OFF",
        "RETRACTED",
        "CHAT_BINDING_INACTIVE",
        "MAX_IDENTITY_CHANGED",
    }
)

#: Массовые назначения идут после личных уведомлений о заявках.
BULK_PURPOSES = (BROADCAST_CHAT_PURPOSE, BROADCAST_DM_PURPOSE, BROADCAST_STAFF_PURPOSE)
#: Общий темп массовых отправок: не чаще раза в 100 мс на все чаты и диалоги.
BULK_GATE = "*bulk*"
BULK_SPACING_MS = 100

#: Колбэк «Не получать рассылки» в личном сообщении рассылки.
UNSUBSCRIBE_CALLBACK = "b:unsub"


def max_destination(user: User, delivery: NotificationDelivery) -> str:
    """Личная доставка возможна только в подтверждённую личность MAX.

    Подтверждение — вход в mini app по подписанным `initData` или диалог с
    ботом, начатый этим человеком (подписанный вебхук, D1): бот не может
    написать первым тому, кто диалог не начинал.
    """
    if (
        not (user.max_identity_verified_at or user.dialog_open)
        or not user.max_user_id
        or not re.fullmatch(r"[1-9]\d{0,18}", user.max_user_id)
        or int(user.max_user_id) > 2**63 - 1
    ):
        raise ResourceNotFound("NO_MAX_IDENTITY")
    if delivery.destination and user.max_user_id != delivery.destination:
        raise ResourceNotFound("MAX_IDENTITY_CHANGED")
    return user.max_user_id


async def _broadcast(session: AsyncSession, delivery: NotificationDelivery) -> Broadcast:
    broadcast = await session.get(Broadcast, delivery.broadcast_id, populate_existing=True)
    if broadcast is None or broadcast.status != "sent":
        raise ResourceNotFound("RETRACTED")
    if broadcast.retracted_at is not None and delivery.provider_message_id is None:
        raise ResourceNotFound("RETRACTED")
    return broadcast


async def _content(session: AsyncSession, broadcast: Broadcast) -> tuple[str, Poll | None]:
    name = None
    if broadcast.tenant_id is not None:
        company = await session.get(ManagementCompany, broadcast.tenant_id)
        name = company.name if company else None
    sender = sender_label(broadcast.origin, name)
    poll = await session.scalar(
        select(Poll)
        .where(Poll.broadcast_id == broadcast.id)
        .execution_options(populate_existing=True)
    )
    lines = None
    if poll is not None:
        options, voters = await tally(session, poll)
        lines = poll_lines(
            poll.question,
            [OptionLine(option.label, option.votes, option.share) for option in options],
            voters=voters,
            closes_at=poll.closes_at,
            closed=poll_closed(poll),
        )
    text = broadcast_text(
        kind=broadcast.kind,
        topic=broadcast.topic,
        title=broadcast.title,
        body=broadcast.body,
        sender=sender,
        edited_at=broadcast.edited_at,
        retracted=broadcast.retracted_at is not None,
        poll=lines,
    )
    return text, poll


def _open_button(poll: Poll | None, ref: str) -> MessageButton:
    if poll is not None and not poll_closed(poll):
        return MessageButton("open_app", VOTE_LABEL, ref)
    return MessageButton("open_app", OPEN_APP_LABEL, ref)


async def active_chat(session: AsyncSession, binding_id: UUID | None) -> ChatBinding:
    binding = await session.scalar(
        select(ChatBinding)
        .where(ChatBinding.id == binding_id)
        .execution_options(populate_existing=True)
    )
    if binding is None or binding.status != "active":
        raise ResourceNotFound("CHAT_BINDING_INACTIVE")
    chat = await session.scalar(
        select(MAXChat)
        .where(MAXChat.max_chat_id == binding.max_chat_id)
        .execution_options(populate_existing=True)
    )
    if chat is None or not chat.bot_present:
        raise ResourceNotFound("CHAT_BINDING_INACTIVE")
    return binding


async def broadcast_chat_message(
    session: AsyncSession, delivery: NotificationDelivery
) -> tuple[str, PersonalMessage, int]:
    """Пост рассылки или опроса в домовой чат: текущее содержимое сообщения."""
    broadcast = await _broadcast(session, delivery)
    binding = await active_chat(session, delivery.chat_binding_id)
    if not allows(binding, broadcast_kind(broadcast.origin, broadcast.kind)):
        raise ResourceNotFound("CHAT_SETTING_OFF")
    text, poll = await _content(session, broadcast)
    buttons: tuple[tuple[MessageButton, ...], ...] = (
        () if broadcast.retracted_at is not None else ((_open_button(poll, delivery.launch_ref),),)
    )
    return binding.max_chat_id, PersonalMessage(text, buttons), broadcast.content_version


async def broadcast_dm_message(
    session: AsyncSession, delivery: NotificationDelivery
) -> tuple[str, PersonalMessage, int]:
    """Личное сообщение рассылки жителю: отписка и выход из дома останавливают."""
    broadcast = await _broadcast(session, delivery)
    user = await session.get(User, delivery.recipient_user_id, populate_existing=True)
    if user is None:
        raise ResourceNotFound("ACCESS_REVOKED")
    if user.broadcast_opt_out_at is not None:
        raise ResourceNotFound("UNSUBSCRIBED")
    houses = list(
        await session.scalars(
            select(BroadcastHouse.house_id).where(BroadcastHouse.broadcast_id == broadcast.id)
        )
    )
    residents = await AccessRepository(session).resident_ids(houses, now=datetime.now(UTC))
    if not any(user_id == user.id for user_id, _ in residents):
        raise ResourceNotFound("ACCESS_REVOKED")
    destination = max_destination(user, delivery)
    text, poll = await _content(session, broadcast)
    buttons = (
        (_open_button(poll, delivery.launch_ref),),
        (MessageButton("callback", UNSUBSCRIBE_LABEL, UNSUBSCRIBE_CALLBACK),),
    )
    return destination, PersonalMessage(text, buttons), broadcast.content_version


async def broadcast_staff_message(
    session: AsyncSession, delivery: NotificationDelivery, public_base_url: str | None
) -> tuple[str, PersonalMessage, int]:
    """Сообщение платформы сотруднику УК: доступ к УК проверяется заново."""
    broadcast = await _broadcast(session, delivery)
    if broadcast.retracted_at is not None:
        raise ResourceNotFound("RETRACTED")
    user = await session.get(User, delivery.recipient_user_id, populate_existing=True)
    if user is None:
        raise ResourceNotFound("ACCESS_REVOKED")
    member = await session.scalar(
        select(OrganizationMembership.id)
        .join(BroadcastCompany, BroadcastCompany.tenant_id == OrganizationMembership.tenant_id)
        .join(ManagementCompany, ManagementCompany.id == OrganizationMembership.tenant_id)
        .where(
            BroadcastCompany.broadcast_id == broadcast.id,
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.status == "active",
            ManagementCompany.status == "active",
        )
        .limit(1)
    )
    if member is None:
        raise ResourceNotFound("ACCESS_REVOKED")
    destination = max_destination(user, delivery)
    base = (public_base_url or "").strip().rstrip("/")
    url = f"{base}/admin/notices" if base else None
    return (
        destination,
        PersonalMessage(staff_notice_text(broadcast.title, broadcast.body, url), ()),
        broadcast.content_version,
    )


async def defer_until(
    session: AsyncSession, delivery: NotificationDelivery, at: datetime
) -> datetime | None:
    """До какого момента отложить отправку или правку. `None` — сейчас."""
    edit = delivery.provider_message_id is not None
    if delivery.purpose == BROADCAST_DM_PURPOSE:
        return None if edit else dm_quiet_until(at)
    if delivery.purpose not in {BROADCAST_CHAT_PURPOSE, TICKET_CHAT_PURPOSE}:
        return None
    binding = await session.get(ChatBinding, delivery.chat_binding_id)
    if binding is None:
        return None
    window = quiet_until(binding.quiet_start_minute, binding.quiet_end_minute, at)
    if window is None:
        return None
    if delivery.purpose == TICKET_CHAT_PURPOSE:
        if not edit:
            return None  # Сам факт заявки тихие часы не задерживают.
        ticket = await session.get(Ticket, delivery.ticket_id)
        if ticket is not None and ticket.status == "accepted":
            return None  # «УК приняла в работу» — тоже сразу.
        return window
    if edit:
        broadcast = await session.get(Broadcast, delivery.broadcast_id)
        if broadcast is not None and broadcast.retracted_at is not None:
            return None  # Удаление поста правится сразу.
    return window


__all__ = [
    "BULK_GATE",
    "BULK_PURPOSES",
    "BULK_SPACING_MS",
    "STOP_CODES",
    "UNSUBSCRIBE_CALLBACK",
    "active_chat",
    "broadcast_chat_message",
    "broadcast_dm_message",
    "broadcast_staff_message",
    "defer_until",
    "max_destination",
]
