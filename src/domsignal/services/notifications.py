"""A-05 delivery consumer of A-16 intents, not a second Ticket workflow/outbox."""

import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.messaging import MaxMessagingProvider, MessagingError, PersonalMessage
from domsignal.contracts.notifications import NotificationLaunch, TicketCallback
from domsignal.contracts.tickets import (
    ObservationCreate,
    ResidentWorkStatus,
    TicketNotificationIntent,
)
from domsignal.core.display_time import DEFAULT_DISPLAY_TIMEZONE
from domsignal.core.incidents import CATEGORY_TITLES
from domsignal.core.signals import quote_text
from domsignal.db.models import (
    Broadcast,
    BroadcastHouse,
    ChatBinding,
    House,
    HouseManagement,
    Incident,
    MAXChat,
    NotificationDelivery,
    OrganizationMembership,
    OutboxMessage,
    Poll,
    Report,
    RouteOutcome,
    Signal,
    SignalEvent,
    Ticket,
    TicketEvent,
    User,
)
from domsignal.db.models.notifications import (
    BOT_REPLY_PURPOSE,
    BROADCAST_CHAT_PURPOSE,
    BROADCAST_DM_PURPOSE,
    BROADCAST_STAFF_PURPOSE,
    CHAT_PURPOSES,
    KEYED_PURPOSES,
    SIGNAL_ALERT_PURPOSE,
    TICKET_CHAT_PURPOSE,
)
from domsignal.db.repositories.notifications import NotificationRepository
from domsignal.db.repositories.passive import PassiveRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.db.repositories.tickets import TicketRepository
from domsignal.services.bot_replies import (
    BOT_REF_PREFIX,
    BOT_REPLY_INTENT_KIND,
    BotReplyIntent,
    render_bot_reply,
)
from domsignal.services.chat_voice import (
    ALERT_REF_PREFIX,
    CHAT_MESSAGE_INTENT_KIND,
    CHAT_REF_PREFIX,
    READING_PURPOSES,
    ChatMessageIntent,
    SignalAlertIntent,
    chat_message,
    operator_alert_message,
    signal_cabinet_url,
)
from domsignal.services.community_delivery import (
    BULK_GATE,
    BULK_PURPOSES,
    BULK_SPACING_MS,
    STOP_CODES,
    broadcast_chat_message,
    broadcast_dm_message,
    broadcast_staff_message,
    defer_until,
    max_destination,
)
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.house_zone import HouseZones
from domsignal.services.notification_render import actionable, render
from domsignal.services.route_card_render import (
    ROUTE_CARD_INTENT_KIND,
    ROUTE_CARD_REF_PREFIX,
    RouteCardIntent,
    render_route_card,
)
from domsignal.services.signals import evidence_mid
from domsignal.services.ticket_chat import (
    TICKET_CHAT_INTENT_KIND,
    TicketChatIntent,
    new_delivery,
    ticket_chat_message,
    touch_ticket_chat,
)
from domsignal.services.tickets import TicketService

logger = logging.getLogger(__name__)

#: Назначение доставки для карточки маршрута.
ROUTE_CARD_PURPOSE = "route_action_card"

#: Автор сообщения проблемы — сотрудник, создавший его из сигнала чата.
NO_RESIDENT_RECIPIENT = "NO_RESIDENT_RECIPIENT"

#: Коды, при которых доставка пропускается, а не считается несостоявшейся.
SKIPPED_CODES = frozenset(
    {"NO_MAX_IDENTITY", NO_RESIDENT_RECIPIENT, "UNSUBSCRIBED", "CHAT_SETTING_OFF", "NO_DIALOG"}
)

#: Снимок личного сообщения D3 по ключу (`reply_event_id`): получатель, текст.
KeyedSnapshot = Callable[
    [AsyncSession, NotificationDelivery], Awaitable[tuple[str, PersonalMessage, int]]
]

#: Карточка не ушла, потому что диалога с ботом ещё не было: после
#: `bot_started` её можно дослать (D1).
REARMABLE_CODES = ("NO_MAX_IDENTITY", "MAX_FORBIDDEN", "MAX_NOT_FOUND", "MAX_REJECTED")
REARM_DELAY = timedelta(seconds=3)

#: Отправка отложена тихими часами (статистика рассылки).
QUIET_HOURS = "QUIET_HOURS"

#: Назначения D3: их причины остановки видны в статистике как есть.
COMMUNITY_PURPOSES = frozenset(
    {
        BROADCAST_CHAT_PURPOSE,
        BROADCAST_DM_PURPOSE,
        BROADCAST_STAFF_PURPOSE,
        TICKET_CHAT_PURPOSE,
        *KEYED_PURPOSES,
    }
)


@dataclass(frozen=True)
class DeliverySnapshot:
    destination: str
    message: PersonalMessage
    # У карточки маршрута нет состояния работы: она не относится к заявке.
    view: ResidentWorkStatus | None = None
    #: Версия текста для правки того же сообщения (D3: рассылки, пост о заявке).
    version: int | None = None


def _versioned(
    built: tuple[str, PersonalMessage, int],
) -> tuple[str, PersonalMessage, None, int]:
    """Снимок D3 без состояния работы: адрес, текст и версия текста."""
    destination, message, version = built
    return destination, message, None, version


class DeferredNotification(Exception):
    def __init__(self, until: datetime) -> None:
        self.until = until


class TicketNotificationHandler:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        tickets: TicketService,
        provider: MaxMessagingProvider,
        enabled: bool,
        public_base_url: str | None = None,
        display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
    ) -> None:
        self.sessions = session_factory
        self.tickets = tickets
        self.provider = provider
        self.enabled = enabled
        # Адрес кабинета для ссылки в оповещении оператора. Пусто — без ссылки.
        self.public_base_url = public_base_url
        # Пояс времени в сообщениях сотрудникам, если пояс дома не подключён.
        self.display_timezone = display_timezone
        #: Личные сообщения D3 по ключу: сопровождение, сводка, напоминание.
        self.keyed: dict[str, KeyedSnapshot] = {}
        #: Ночное окно личных рассылок (`BROADCAST_DM_QUIET_HOURS`), минуты суток
        #: местного времени дома.
        self.dm_quiet_window: tuple[int, int] | None = (22 * 60, 8 * 60)
        #: Пояс дома из пакета региона (D4): тихие часы и время в оповещении.
        self.zones: HouseZones | None = None

    async def _snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        if delivery.purpose == ROUTE_CARD_PURPOSE:
            return await self._route_card_snapshot(session, delivery)
        if delivery.purpose == SIGNAL_ALERT_PURPOSE:
            return await self._signal_alert_snapshot(session, delivery)
        if delivery.purpose == BOT_REPLY_PURPOSE:
            return await self._bot_reply_snapshot(session, delivery)
        if delivery.purpose == BROADCAST_CHAT_PURPOSE:
            return DeliverySnapshot(*_versioned(await broadcast_chat_message(session, delivery)))
        if delivery.purpose == BROADCAST_DM_PURPOSE:
            return DeliverySnapshot(*_versioned(await broadcast_dm_message(session, delivery)))
        if delivery.purpose == BROADCAST_STAFF_PURPOSE:
            return DeliverySnapshot(
                *_versioned(await broadcast_staff_message(session, delivery, self.public_base_url))
            )
        if delivery.purpose == TICKET_CHAT_PURPOSE:
            chat_id, message, version, _ = await ticket_chat_message(session, delivery)
            return DeliverySnapshot(chat_id, message, None, version)
        if delivery.purpose in KEYED_PURPOSES:
            build = self.keyed.get(delivery.purpose)
            if build is None:
                raise ResourceNotFound("INVALID_INTENT")
            return DeliverySnapshot(*_versioned(await build(session, delivery)))
        if delivery.purpose in CHAT_PURPOSES:
            return await self._chat_snapshot(session, delivery)
        return await self._ticket_snapshot(session, delivery)

    async def _recipient(self, session: AsyncSession, delivery: NotificationDelivery) -> User:
        """Получатель личной доставки. У сообщения в чат его нет."""
        if delivery.recipient_user_id is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        user = await session.get(User, delivery.recipient_user_id)
        if user is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        return user

    async def _staff_context(self, session: AsyncSession, user: User, house_id: UUID) -> None:
        """Сотрудник с доступом к дому по существующей политике доступа."""
        context = await self.tickets.memberships.require_house(
            session, user_id=user.id, house_id=house_id, source="worker"
        )
        if context.organization_role is None or "ticket.read" not in context.permissions:
            raise ResourceNotFound("ACCESS_REVOKED")

    async def _signal_alert_snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        """Оповещение оператора: доступ к дому перепроверяется перед отправкой."""
        user = await self._recipient(session, delivery)
        signal = await session.get(Signal, delivery.signal_id)
        if signal is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        await self._staff_context(session, user, signal.house_id)
        destination = await self._identity(user, delivery)
        house = await session.get(House, signal.house_id)
        intent = await self._alert_intent(session, delivery)
        emergency = signal.emergency or {}
        new_kinds = intent.new_kinds if intent else []
        quote, from_rules = await self._alert_evidence(
            session, signal, intent.evidence_mid if intent else None, new_kinds
        )
        return DeliverySnapshot(
            destination,
            operator_alert_message(
                house_address=house.address if house is not None else "",
                danger_kinds=list(emergency.get("kinds", [])),
                from_rules=from_rules,
                quote=quote[0] if quote else None,
                quote_author=quote[1] if quote else None,
                quote_sent_at=quote[2] if quote else None,
                cabinet_url=signal_cabinet_url(self.public_base_url, signal.id),
                new_kinds=new_kinds,
                display_timezone=(
                    await self.zones.of_house(session, signal.house_id)
                    if self.zones is not None
                    else self.display_timezone
                ),
            ),
        )

    @staticmethod
    async def _alert_intent(
        session: AsyncSession, delivery: NotificationDelivery
    ) -> SignalAlertIntent | None:
        outbox = await session.get(OutboxMessage, delivery.outbox_message_id)
        if outbox is None:
            return None
        try:
            return SignalAlertIntent.model_validate(outbox.payload)
        except ValidationError:
            return None

    @staticmethod
    async def _alert_evidence(
        session: AsyncSession,
        signal: Signal,
        mid: str | None,
        new_kinds: list[str],
    ) -> tuple[tuple[str, str, datetime] | None, bool]:
        """Цитата оповещения — реплика, в которой найдена опасность.

        Источник признака («правила» или «разбор») берётся у того же
        доказательства. Старое намерение без реплики получает доказательство
        из сигнала; первая реплика окна — только если доказательства нет вовсе.
        """
        repo = PassiveRepository(session)
        emergency = signal.emergency or {}
        evidence = [item for item in emergency.get("evidence", []) if isinstance(item, dict)]
        chosen = mid or evidence_mid(evidence, new_kinds)
        sources = {
            item.get("source")
            for item in evidence
            if chosen
            and item.get("line_mid") == chosen
            and (not new_kinds or item.get("kind") in new_kinds)
        }
        source = "rules" if "rules" in sources else next(iter(sources), None)
        from_rules = source == "rules" if source else "rules" in emergency.get("sources", [])
        if chosen:
            found = await repo.evidence_line(signal, chosen)
            if found is not None:
                return (quote_text(found[0]), found[1], found[2]), from_rules
        first = await repo.first_quote(signal.id)
        if first is None:
            return None, from_rules
        return (first.text, first.author_ref, first.sent_at), from_rules

    async def _chat_snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        """Сообщение в групповой чат: привязка должна по-прежнему читать чат."""
        outbox = await session.get(OutboxMessage, delivery.outbox_message_id)
        if outbox is None:
            raise ResourceNotFound("INVALID_INTENT")
        try:
            intent = ChatMessageIntent.model_validate(outbox.payload)
        except ValidationError as exc:
            raise ResourceNotFound("INVALID_INTENT") from exc
        binding = await session.scalar(
            select(ChatBinding)
            .where(ChatBinding.id == delivery.chat_binding_id)
            .execution_options(populate_existing=True)
        )
        if (
            binding is None
            or binding.id != intent.chat_binding_id
            or binding.status != "active"
            or binding.binding_version != intent.binding_version
            # Сообщение о чтении и памятка — только пока чат читается; ответ на
            # `/report` и сообщение о подключении — пока привязка активна.
            or (intent.purpose in READING_PURPOSES and not binding.passive_capture_enabled)
        ):
            raise ResourceNotFound("CHAT_BINDING_INACTIVE")
        chat = await session.scalar(
            select(MAXChat)
            .where(MAXChat.max_chat_id == binding.max_chat_id)
            .execution_options(populate_existing=True)
        )
        if chat is None or not chat.bot_present:
            raise ResourceNotFound("CHAT_BINDING_INACTIVE")
        return DeliverySnapshot(binding.max_chat_id, chat_message(intent, delivery.launch_ref))

    async def _identity(self, user: User, delivery: NotificationDelivery) -> str:
        """Личная доставка — только в подтверждённую личность MAX (D1)."""
        return max_destination(user, delivery)

    async def _bot_reply_snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        """Ответ личного бота: текст шаблона из outbox, получатель — автор события."""
        user = await self._recipient(session, delivery)
        outbox = await session.get(OutboxMessage, delivery.outbox_message_id)
        if outbox is None:
            raise ResourceNotFound("INVALID_INTENT")
        try:
            intent = BotReplyIntent.model_validate(outbox.payload)
        except ValidationError as exc:
            raise ResourceNotFound("INVALID_INTENT") from exc
        destination = await self._identity(user, delivery)
        return DeliverySnapshot(destination, render_bot_reply(intent))

    async def _route_card_snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        """Снимок карточки маршрута: доступ перепроверяется, текст — из outbox.

        Формулировка фиксируется в момент разбора, поэтому повторная доставка
        не меняет текст и не зависит от обновления справочника.
        """
        user = await self._recipient(session, delivery)
        outbox = await session.get(OutboxMessage, delivery.outbox_message_id)
        if outbox is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        try:
            intent = RouteCardIntent.model_validate(outbox.payload)
        except ValidationError as exc:
            raise ResourceNotFound("INVALID_INTENT") from exc
        context = await self.tickets.memberships.require_house(
            session,
            user_id=user.id,
            house_id=intent.house_id,
            source="worker",
        )
        if not context.resident_access:
            raise ResourceNotFound("ACCESS_REVOKED")
        destination = await self._identity(user, delivery)
        return DeliverySnapshot(
            destination,
            render_route_card(intent, ref=delivery.launch_ref),
        )

    async def _ticket_snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        user = await self._recipient(session, delivery)
        ticket = await session.get(Ticket, delivery.ticket_id)
        if ticket is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        context = await self.tickets.memberships.require_house(
            session,
            user_id=user.id,
            house_id=ticket.house_id,
            source="worker",
        )
        if not context.resident_access or context.management_id.value != ticket.management_id:
            raise ResourceNotFound("ACCESS_REVOKED")
        if not await TicketRepository(session).participant(ticket, user.id):
            raise ResourceNotFound("ACCESS_REVOKED")
        view = await self.tickets.work_status(
            session, actor_id=user.id, incident_id=ticket.incident_id
        )
        if view.ticket_id != ticket.id:
            raise ResourceNotFound("TICKET_SUPERSEDED")
        destination = await self._identity(user, delivery)
        incident = await session.get(Incident, ticket.incident_id)
        assert incident is not None
        # Category is a controlled public summary; never forward private Report prose/location.
        title = next(
            (title for category, title in CATEGORY_TITLES.items() if category == incident.category),
            "Проблема дома",
        )
        return DeliverySnapshot(
            destination,
            render(
                purpose=delivery.purpose,
                title=title,
                view=view,
                attempt_id=delivery.work_attempt_id,
                ref=delivery.launch_ref,
            ),
            view,
        )

    @staticmethod
    def _stop(delivery: NotificationDelivery, code: str, now: datetime) -> None:
        # «Некому доставить» — не ошибка и не отзыв доступа: доставка пропущена.
        delivery.status = "skipped" if code in SKIPPED_CODES else "superseded"
        delivery.superseded_at = now if delivery.status == "superseded" else None
        delivery.last_error_code = code
        delivery.last_error_at = now
        delivery.next_attempt_at = None
        delivery.lease_until = None
        delivery.lease_token = None

    async def consume_once(self) -> bool:
        async with self.sessions() as session, session.begin():
            repo = NotificationRepository(session)
            outbox = await repo.intent()
            if outbox is None:
                return False
            try:
                intent = TicketNotificationIntent.model_validate(outbox.payload)
            except ValidationError:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            ticket = await session.get(Ticket, intent.ticket_id)
            event = await session.get(TicketEvent, intent.event_id)
            if (
                ticket is None
                or event is None
                or event.ticket_id != ticket.id
                or outbox.aggregate_id != ticket.id
                or event.version != intent.ticket_version
                or event.kind != intent.event_kind
                or event.attempt_id != intent.attempt_id
                or ticket.management_id != intent.management_id
                or ticket.house_id != intent.house_id
                or ticket.incident_id != intent.incident_id
            ):
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            existing = await repo.affected(ticket.id)
            for delivery in existing:
                if (
                    delivery.provider_message_id
                    and delivery.purpose == "work_verification"
                    and delivery.desired_version < ticket.version
                ):
                    delivery.desired_version = ticket.version
                    if delivery.status == "failed":
                        delivery.status = "retry_wait"
                        delivery.retry_count = 0
                        delivery.next_attempt_at = None
            # Сообщение бота о заявке в чате догоняет новый статус правкой (B-06).
            await touch_ticket_chat(session, ticket.incident_id)
            purposes = {"accepted": "ticket_accepted", "work_reported": "work_verification"}
            purpose = purposes.get(event.kind)
            if purpose:
                for user_id, signal_only in await repo.recipients(ticket.incident_id):
                    if any(
                        d.outbox_message_id == outbox.id and d.recipient_user_id == user_id
                        for d in existing
                    ):
                        continue
                    delivery = NotificationDelivery(
                        id=uuid4(),
                        outbox_message_id=outbox.id,
                        recipient_user_id=user_id,
                        channel="max",
                        purpose=purpose,
                        ticket_id=ticket.id,
                        work_attempt_id=event.attempt_id,
                        launch_ref="w_" + secrets.token_urlsafe(24),
                        status="pending",
                        desired_version=ticket.version,
                    )
                    session.add(delivery)
                    if signal_only:
                        # Автор — сотрудник, создавший заявку из сигнала чата.
                        # Жителей чата к заявке не привязать, пока они сами не
                        # присоединятся; это не отзыв доступа.
                        self._stop(delivery, NO_RESIDENT_RECIPIENT, datetime.now(UTC))
                        continue
                    try:
                        snapshot = await self._snapshot(session, delivery)
                        delivery.destination = snapshot.destination
                    except (AccessDenied, ResourceNotFound) as exc:
                        code = (
                            str(exc)
                            if str(exc)
                            in {
                                "NO_MAX_IDENTITY",
                                "MAX_IDENTITY_CHANGED",
                                "TICKET_SUPERSEDED",
                            }
                            else "ACCESS_REVOKED"
                        )
                        self._stop(delivery, code, datetime.now(UTC))
            # Lock, fan-out uniqueness, reconcile marks and consumer ack commit atomically.
            outbox.status = "processed"
            await session.flush()
        return True

    async def consume_route_cards_once(self) -> bool:
        """Превратить карточку маршрута из outbox в адресную доставку.

        Тот же механизм, что у уведомлений по заявке: второго транспорта не
        появляется, `launch_ref` и доставка общие. Отличается только предмет —
        исход маршрутизации вместо заявки, потому что внешний маршрут заявку
        не создаёт.
        """
        async with self.sessions() as session, session.begin():
            repo = NotificationRepository(session)
            outbox = await repo.intent(ROUTE_CARD_INTENT_KIND)
            if outbox is None:
                return False
            try:
                intent = RouteCardIntent.model_validate(outbox.payload)
            except ValidationError:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            if outbox.aggregate_id != intent.route_outcome_id:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            if not await repo.by_outbox(outbox.id):
                delivery = NotificationDelivery(
                    id=uuid4(),
                    outbox_message_id=outbox.id,
                    recipient_user_id=intent.recipient_user_id,
                    channel="max",
                    purpose=ROUTE_CARD_PURPOSE,
                    ticket_id=None,
                    route_outcome_id=intent.route_outcome_id,
                    launch_ref=ROUTE_CARD_REF_PREFIX + secrets.token_urlsafe(24),
                    status="pending",
                    desired_version=0,
                )
                session.add(delivery)
                try:
                    snapshot = await self._snapshot(session, delivery)
                    delivery.destination = snapshot.destination
                except (AccessDenied, ResourceNotFound) as exc:
                    code = (
                        str(exc)
                        if str(exc) in {"NO_MAX_IDENTITY", "MAX_IDENTITY_CHANGED", "INVALID_INTENT"}
                        else "ACCESS_REVOKED"
                    )
                    self._stop(delivery, code, datetime.now(UTC))
            outbox.status = "processed"
            await session.flush()
        return True

    async def consume_bot_replies_once(self) -> bool:
        """Ответ личного бота из outbox → одна адресная доставка."""
        async with self.sessions() as session, session.begin():
            repo = NotificationRepository(session)
            outbox = await repo.intent(BOT_REPLY_INTENT_KIND)
            if outbox is None:
                return False
            try:
                intent = BotReplyIntent.model_validate(outbox.payload)
            except ValidationError:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            if not await repo.by_outbox(outbox.id):
                delivery = NotificationDelivery(
                    id=uuid4(),
                    outbox_message_id=outbox.id,
                    recipient_user_id=intent.recipient_user_id,
                    channel="max",
                    purpose=BOT_REPLY_PURPOSE,
                    reply_event_id=intent.reply_event_id,
                    launch_ref=BOT_REF_PREFIX + secrets.token_urlsafe(24),
                    status="pending",
                    desired_version=0,
                )
                session.add(delivery)
                try:
                    snapshot = await self._snapshot(session, delivery)
                    delivery.destination = snapshot.destination
                except (AccessDenied, ResourceNotFound) as exc:
                    self._stop(delivery, str(exc) or "NO_MAX_IDENTITY", datetime.now(UTC))
            outbox.status = "processed"
            await session.flush()
        return True

    @staticmethod
    async def rearm_route_card(session: AsyncSession, *, user_id: UUID, now: datetime) -> bool:
        """После `bot_started` дослать последнюю недоставленную карточку ≤ 24 ч.

        Карточка по `/report` из группы не уходила, пока человек не начал
        диалог с ботом (`NO_MAX_IDENTITY` или отказ MAX). Доставка та же: доступ
        к дому перепроверяется при отправке.
        """
        delivery = await session.scalar(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.recipient_user_id == user_id,
                NotificationDelivery.purpose == ROUTE_CARD_PURPOSE,
                NotificationDelivery.status.in_(["skipped", "failed"]),
                NotificationDelivery.last_error_code.in_(REARMABLE_CODES),
                NotificationDelivery.provider_message_id.is_(None),
                NotificationDelivery.created_at > now - timedelta(hours=24),
            )
            .order_by(NotificationDelivery.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if delivery is None:
            return False
        delivery.status = "pending"
        delivery.destination = None
        # Сначала приветствие, потом досланная карточка.
        delivery.next_attempt_at = now + REARM_DELAY
        delivery.retry_count = 0
        delivery.last_error_code = None
        delivery.last_error_at = None
        return True

    async def consume_chat_messages_once(self) -> bool:
        """Сообщение в групповой чат из outbox → одна адресная доставка.

        Тот же механизм, что у карточки маршрута: получатель — чат привязки,
        а не человек. При `MAX_TRANSPORT=off` доставка остаётся в очереди и
        никуда не уходит.
        """
        async with self.sessions() as session, session.begin():
            repo = NotificationRepository(session)
            outbox = await repo.intent(CHAT_MESSAGE_INTENT_KIND)
            if outbox is None:
                return False
            try:
                intent = ChatMessageIntent.model_validate(outbox.payload)
            except ValidationError:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            if outbox.aggregate_id != intent.chat_binding_id:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            if not await repo.by_outbox(outbox.id):
                delivery = NotificationDelivery(
                    id=uuid4(),
                    outbox_message_id=outbox.id,
                    recipient_user_id=None,
                    channel="max",
                    purpose=intent.purpose,
                    chat_binding_id=intent.chat_binding_id,
                    launch_ref=CHAT_REF_PREFIX + secrets.token_urlsafe(24),
                    status="pending",
                    desired_version=0,
                )
                session.add(delivery)
                try:
                    snapshot = await self._snapshot(session, delivery)
                    delivery.destination = snapshot.destination
                except (AccessDenied, ResourceNotFound) as exc:
                    self._stop(delivery, str(exc) or "CHAT_BINDING_INACTIVE", datetime.now(UTC))
            outbox.status = "processed"
            await session.flush()
        return True

    async def consume_ticket_chat_once(self) -> bool:
        """Пост о заявке из outbox → одна доставка в чат (одна на заявку).

        Выключенная настройка «Статусы заявок» или неактивная привязка дают
        пропуск с причиной: запись о том, что сообщение не публиковалось.
        """
        async with self.sessions() as session, session.begin():
            repo = NotificationRepository(session)
            outbox = await repo.intent(TICKET_CHAT_INTENT_KIND)
            if outbox is None:
                return False
            try:
                intent = TicketChatIntent.model_validate(outbox.payload)
            except ValidationError:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return True
            ticket = await session.get(Ticket, intent.ticket_id)
            binding = await session.get(ChatBinding, intent.chat_binding_id)
            existing = await session.scalar(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.ticket_id == intent.ticket_id,
                    NotificationDelivery.purpose == TICKET_CHAT_PURPOSE,
                )
            )
            if (
                ticket is None
                or binding is None
                or outbox.aggregate_id != intent.ticket_id
                or existing is not None
            ):
                outbox.status = "processed"
                outbox.last_error = None if existing is not None else "INVALID_INTENT"
                return True
            delivery = new_delivery(outbox.id, intent, desired_version=0)
            session.add(delivery)
            now = datetime.now(UTC)
            if binding.binding_version != intent.binding_version:
                self._stop(delivery, "CHAT_BINDING_INACTIVE", now)
            else:
                try:
                    snapshot = await self._snapshot(session, delivery)
                    delivery.destination = snapshot.destination
                    delivery.desired_version = snapshot.version or 0
                except (AccessDenied, ResourceNotFound) as exc:
                    self._stop(delivery, str(exc) or "CHAT_BINDING_INACTIVE", now)
            outbox.status = "processed"
            await session.flush()
        return True

    async def _staff_recipients(self, session: AsyncSession, house_id: UUID) -> list[User]:
        """Сотрудники текущей УК дома с отображением в MAX и доступом к дому.

        Новой модели доступа нет: кандидаты — активные участники компании,
        управляющей домом сейчас, а доступ каждого проверяет та же политика,
        что и HTTP-запросы сотрудников.
        """
        now = datetime.now(UTC)
        management = await session.scalar(
            select(HouseManagement).where(
                HouseManagement.house_id == house_id,
                HouseManagement.status == "active",
                HouseManagement.valid_from <= now,
                (HouseManagement.valid_to.is_(None)) | (HouseManagement.valid_to > now),
            )
        )
        if management is None:
            return []
        candidates = list(
            await session.scalars(
                select(User)
                .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                .where(
                    OrganizationMembership.tenant_id == management.tenant_id,
                    OrganizationMembership.status == "active",
                    User.max_user_id.is_not(None),
                    User.max_identity_verified_at.is_not(None),
                )
                .order_by(User.id)
                .distinct()
            )
        )
        recipients: list[User] = []
        for user in candidates:
            try:
                await self._staff_context(session, user, house_id)
            except (AccessDenied, ResourceNotFound):
                continue
            recipients.append(user)
        return recipients

    async def fan_out_signal_alert(self, payload: dict[str, Any]) -> None:
        """Операционная задача `signal.alert`: оповещение операторов дома.

        Не зависит от AI-пула. Получателей нет — одна доставка `skipped` с
        причиной `NO_RECIPIENTS`; сигнал всё равно остаётся в очереди.
        """
        outbox_id = UUID(str(payload["outbox_message_id"]))
        recipients: list[User] = []
        async with self.sessions() as session, session.begin():
            outbox = await session.scalar(
                select(OutboxMessage).where(OutboxMessage.id == outbox_id).with_for_update()
            )
            if outbox is None or outbox.status != "pending":
                return
            try:
                intent = SignalAlertIntent.model_validate(outbox.payload)
            except ValidationError:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return
            signal = await session.get(Signal, intent.signal_id)
            if signal is None or signal.house_id != intent.house_id:
                outbox.status, outbox.last_error = "processed", "INVALID_INTENT"
                return
            now = datetime.now(UTC)
            recipients = await self._staff_recipients(session, signal.house_id)
            for user in recipients:
                delivery = NotificationDelivery(
                    id=uuid4(),
                    outbox_message_id=outbox.id,
                    recipient_user_id=user.id,
                    channel="max",
                    purpose=SIGNAL_ALERT_PURPOSE,
                    signal_id=signal.id,
                    launch_ref=ALERT_REF_PREFIX + secrets.token_urlsafe(24),
                    status="pending",
                    desired_version=0,
                )
                session.add(delivery)
                try:
                    snapshot = await self._snapshot(session, delivery)
                    delivery.destination = snapshot.destination
                except (AccessDenied, ResourceNotFound) as exc:
                    self._stop(delivery, str(exc) or "ACCESS_REVOKED", now)
            if not recipients:
                session.add(
                    NotificationDelivery(
                        id=uuid4(),
                        outbox_message_id=outbox.id,
                        recipient_user_id=None,
                        channel="max",
                        purpose=SIGNAL_ALERT_PURPOSE,
                        signal_id=signal.id,
                        launch_ref=ALERT_REF_PREFIX + secrets.token_urlsafe(24),
                        status="skipped",
                        last_error_code="NO_RECIPIENTS",
                        last_error_at=now,
                        desired_version=0,
                    )
                )
            session.add(
                SignalEvent(
                    house_id=signal.house_id,
                    signal_id=signal.id,
                    kind="operator_alert_queued" if recipients else "operator_alert_skipped",
                    details=f"recipients={len(recipients)}" if recipients else "NO_RECIPIENTS",
                )
            )
            outbox.status = "processed"
            await session.flush()
        logger.info(
            "signal_alert_fanned_out",
            extra={"signal_id": str(intent.signal_id), "recipients": len(recipients)},
        )

    async def deliver_once(self, *, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        at = now or datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            repo = NotificationRepository(session)
            delivery = await repo.due(at)
            if delivery is None:
                return False
            if delivery.status == "processing" and delivery.provider_message_id is None:
                delivery.status = "unknown"
                delivery.last_error_code = "SEND_LEASE_EXPIRED"
                delivery.last_error_at = at
                delivery.lease_token = None
                delivery.lease_until = None
                return True  # The previous POST may have committed; never blindly resend.
            try:
                snapshot = await self._snapshot(session, delivery)
            except (AccessDenied, ResourceNotFound) as exc:
                # Причина остановки D3 попадает в статистику рассылки; прежние
                # назначения по-прежнему останавливаются как «доступ отозван».
                code = (
                    str(exc)
                    if delivery.purpose in COMMUNITY_PURPOSES and str(exc) in STOP_CODES
                    else "ACCESS_REVOKED"
                )
                self._stop(delivery, code, at)
                return True
            until = await defer_until(
                session, delivery, at, dm_window=self.dm_quiet_window, zones=self.zones
            )
            if until is not None:
                # Тихие часы: отправка или необязательная правка ждут утра.
                delivery.next_attempt_at = until
                if delivery.provider_message_id is None:
                    delivery.last_error_code = QUIET_HOURS
                return True
            if delivery.purpose in BULK_PURPOSES:
                paced = await repo.pace(BULK_GATE, at, spacing_ms=BULK_SPACING_MS)
                if paced is not None:
                    delivery.next_attempt_at = paced
                    return True
            if (
                delivery.provider_message_id is None
                and snapshot.view is not None
                and (
                    (
                        delivery.purpose == "work_verification"
                        and not actionable(snapshot.view, delivery.work_attempt_id)
                    )
                    or (
                        delivery.purpose == "ticket_accepted"
                        and snapshot.view.status not in {"accepted", "in_progress"}
                    )
                )
            ):
                self._stop(delivery, "STALE_INTENT", at)
                return True
            token = uuid4()
            until = await repo.reserve_destination(snapshot.destination, token, at)
            if until:
                delivery.next_attempt_at = until
                return True
            delivery.destination = snapshot.destination
            delivery.status = "processing"
            delivery.lease_token = token
            delivery.lease_until = at + timedelta(seconds=90)
            delivery.attempt_count += 1
            delivery_id = delivery.id
        # Fresh authorization and render immediately before the side effect. No domain locks
        # or DB transactions are kept across the HTTP call.
        async with self.sessions() as session:
            delivery = await session.get(NotificationDelivery, delivery_id)
            assert delivery is not None
            try:
                snapshot = await self._snapshot(session, delivery)
                denied = (
                    delivery.provider_message_id is None
                    and snapshot.view is not None
                    and (
                        (
                            delivery.purpose == "work_verification"
                            and not actionable(snapshot.view, delivery.work_attempt_id)
                        )
                        or (
                            delivery.purpose == "ticket_accepted"
                            and snapshot.view.status not in {"accepted", "in_progress"}
                        )
                    )
                )
            except (AccessDenied, ResourceNotFound):
                denied = True
            message_id = delivery.provider_message_id
            purpose = delivery.purpose
            operation = "edit" if message_id else "send"
            outbox_id, ticket_id, attempt_id = (
                delivery.outbox_message_id,
                delivery.ticket_id,
                delivery.work_attempt_id,
            )
        error: MessagingError | None = None
        if not denied:
            try:
                if message_id:
                    await self.provider.edit_message(message_id, snapshot.message)
                elif purpose in CHAT_PURPOSES:
                    # Тот же документированный POST /messages, но в чат.
                    result = await self.provider.send_chat_message(
                        snapshot.destination,
                        snapshot.message,
                    )
                    message_id = result.message_id
                else:
                    result = await self.provider.send_personal_message(
                        snapshot.destination,
                        snapshot.message,
                    )
                    message_id = result.message_id
            except MessagingError as exc:
                error = exc
        finished = now or datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            delivery = await session.scalar(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.id == delivery_id,
                )
                .with_for_update()
            )
            assert delivery is not None
            if delivery.lease_token != token:
                return True
            await NotificationRepository(session).release_destination(
                snapshot.destination,
                token,
                finished,
            )
            if denied:
                self._stop(delivery, "ACCESS_OR_STATE_CHANGED", finished)
            elif error:
                delivery.last_error_code = error.code
                delivery.last_error_at = finished
                delivery.retry_count += 1
                delivery.status = (
                    "unknown"
                    if error.kind == "unknown"
                    else "failed"
                    if error.kind == "permanent" or delivery.retry_count >= 5
                    else "retry_wait"
                )
                delivery.next_attempt_at = (
                    finished
                    + timedelta(
                        seconds=max(
                            min(60, 2**delivery.retry_count),
                            error.retry_after or 0,
                        )
                    )
                    if delivery.status == "retry_wait"
                    else None
                )
            else:
                delivery.status = "accepted"
                delivery.provider_message_id = message_id
                delivery.accepted_at = delivery.accepted_at or finished
                delivery.applied_version = (
                    snapshot.version
                    if snapshot.version is not None
                    else snapshot.view.version or 0
                    if snapshot.view is not None
                    else 0
                )
                delivery.desired_version = max(delivery.desired_version, delivery.applied_version)
                delivery.retry_count = 0
                delivery.next_attempt_at = None
                delivery.last_error_code = None
                delivery.last_error_at = None
            delivery.lease_token = None
            delivery.lease_until = None
            logger.info(
                "max_notification_operation",
                extra={
                    "notification_delivery_id": str(delivery_id),
                    "outbox_message_id": str(outbox_id),
                    "ticket_id": str(ticket_id),
                    "work_attempt_id": str(attempt_id),
                    "provider_operation": operation,
                    "delivery_status": delivery.status,
                    "error_code": delivery.last_error_code,
                },
            )
        return True

    async def launch(
        self, session: AsyncSession, *, actor_id: UUID, ref: str
    ) -> NotificationLaunch:
        """Куда открыть mini app по ссылке из личного сообщения.

        Оба префикса проходят одни и те же проверки: получатель доставки,
        членство в доме и актуальные права. Любое несовпадение даёт 404 без
        различий в тексте, поэтому по ответу нельзя узнать, существует ли
        ссылка вообще.
        """
        if not re.fullmatch(r"[wrtpnc]_[A-Za-z0-9_-]{32}", ref):
            raise ResourceNotFound("Resource was not found")
        delivery = await NotificationRepository(session).by_ref(ref)
        if delivery is None:
            raise ResourceNotFound("Resource was not found")
        if ref.startswith(CHAT_REF_PREFIX):
            return await self._chat_launch(session, delivery, actor_id)
        if delivery.purpose in {TICKET_CHAT_PURPOSE, BROADCAST_CHAT_PURPOSE, BROADCAST_DM_PURPOSE}:
            return await self._community_launch(session, delivery, actor_id)
        if delivery.recipient_user_id != actor_id:
            raise ResourceNotFound("Resource was not found")
        try:
            snapshot = await self._snapshot(session, delivery)
        except (AccessDenied, ResourceNotFound):
            raise ResourceNotFound("Resource was not found") from None
        if delivery.purpose == ROUTE_CARD_PURPOSE:
            return await self._route_card_launch(session, delivery)
        ticket = await session.get(Ticket, delivery.ticket_id)
        assert ticket is not None and snapshot.view is not None
        latest = snapshot.view.latest_attempt
        return NotificationLaunch(
            kind="ticket",
            incident_id=ticket.incident_id,
            house_id=ticket.house_id,
            work_attempt_id=latest.id if latest else None,
            stale=bool(
                delivery.work_attempt_id and (not latest or latest.id != delivery.work_attempt_id)
            ),
        )

    async def _chat_launch(
        self, session: AsyncSession, delivery: NotificationDelivery, actor_id: UUID
    ) -> NotificationLaunch:
        """Кнопка сообщения бота в домовом чате: дом чата, если он доступен жителю.

        Участие в чате проверено при входе по этой же ссылке (D1); здесь —
        только актуальный доступ к дому. Любое несовпадение — 404.
        """
        if delivery.chat_binding_id is None:
            raise ResourceNotFound("Resource was not found")
        binding = await session.get(ChatBinding, delivery.chat_binding_id)
        if binding is None:
            raise ResourceNotFound("Resource was not found")
        try:
            await self._readable_house(session, actor_id, binding.house_id)
        except (AccessDenied, ResourceNotFound):
            raise ResourceNotFound("Resource was not found") from None
        return NotificationLaunch(
            kind="house", house_id=binding.house_id, work_attempt_id=None, stale=False
        )

    async def _community_launch(
        self, session: AsyncSession, delivery: NotificationDelivery, actor_id: UUID
    ) -> NotificationLaunch:
        """Пост в чате и личное сообщение рассылки: доступ к дому проверяется заново.

        Ссылка поста в группе общая для всех участников чата, поэтому
        получателя у неё нет: открывает тот, у кого есть доступ к дому поста
        (участие в чате проверено при входе по этой же ссылке, D1).
        """
        house_id: UUID | None = None
        if delivery.purpose == BROADCAST_DM_PURPOSE and delivery.recipient_user_id != actor_id:
            raise ResourceNotFound("Resource was not found")
        if delivery.chat_binding_id is not None:
            binding = await session.get(ChatBinding, delivery.chat_binding_id)
            house_id = binding.house_id if binding is not None else None
        if delivery.purpose == TICKET_CHAT_PURPOSE:
            ticket = await session.get(Ticket, delivery.ticket_id)
            if ticket is None or house_id is None or ticket.house_id != house_id:
                raise ResourceNotFound("Resource was not found")
            await self._readable_house(session, actor_id, ticket.house_id)
            return NotificationLaunch(
                kind="ticket",
                incident_id=ticket.incident_id,
                house_id=ticket.house_id,
                work_attempt_id=None,
                stale=False,
            )
        broadcast = await session.get(Broadcast, delivery.broadcast_id)
        if broadcast is None or broadcast.status != "sent" or broadcast.retracted_at is not None:
            raise ResourceNotFound("Resource was not found")
        audience = list(
            await session.scalars(
                select(BroadcastHouse.house_id).where(BroadcastHouse.broadcast_id == broadcast.id)
            )
        )
        candidates = [house_id] if house_id is not None else audience
        chosen = None
        for candidate in candidates:
            if candidate not in audience:
                continue
            try:
                await self._readable_house(session, actor_id, candidate)
            except (AccessDenied, ResourceNotFound):
                continue
            chosen = candidate
            break
        if chosen is None:
            raise ResourceNotFound("Resource was not found")
        poll_id = await session.scalar(select(Poll.id).where(Poll.broadcast_id == broadcast.id))
        return NotificationLaunch(
            kind="poll" if poll_id is not None else "announcements",
            house_id=chosen,
            poll_id=poll_id,
            work_attempt_id=None,
            stale=False,
        )

    async def _readable_house(self, session: AsyncSession, actor_id: UUID, house_id: UUID) -> None:
        context = await self.tickets.memberships.require_house(
            session, user_id=actor_id, house_id=house_id
        )
        self.tickets.memberships.require_permission(context, "incident.read")

    async def _route_card_launch(
        self, session: AsyncSession, delivery: NotificationDelivery
    ) -> NotificationLaunch:
        """Ссылка `r_` ведёт на экран карточки маршрута, а не на заявку.

        У внешнего маршрута заявки нет вовсе, поэтому `incident_id` остаётся
        пустым: подставлять вместо него чужую проблему продукт не станет.
        """
        outcome = await session.get(RouteOutcome, delivery.route_outcome_id)
        if outcome is None:
            raise ResourceNotFound("Resource was not found")
        incident_id: UUID | None = None
        if outcome.report_id is not None:
            report = await session.get(Report, outcome.report_id)
            incident_id = report.incident_id if report is not None else None
        return NotificationLaunch(
            kind="route_card",
            incident_id=incident_id,
            house_id=outcome.house_id,
            route_outcome_id=outcome.id,
            work_attempt_id=None,
            stale=False,
        )

    async def _callback_delivery(
        self,
        session: AsyncSession,
        callback: TicketCallback,
    ) -> NotificationDelivery:
        delivery = await NotificationRepository(session).by_ref(callback.launch_ref)
        if (
            delivery is None
            or not delivery.accepted_at
            or not delivery.work_attempt_id
            or delivery.ticket_id is None
            or delivery.provider_message_id != callback.message_id
        ):
            raise ResourceNotFound("Resource was not found")
        snapshot = await self._snapshot(session, delivery)
        if snapshot.destination != callback.actor:
            raise ResourceNotFound("Resource was not found")
        return delivery

    async def callback(self, payload: dict[str, Any]) -> None:
        callback = TicketCallback.model_validate(payload)
        async with self.sessions() as session, session.begin():
            try:
                delivery = await self._callback_delivery(session, callback)
                # Callbacks only reach ticket deliveries; `_callback_delivery`
                # already rejects anything without a ticket and an attempt.
                assert delivery.ticket_id is not None
                assert delivery.recipient_user_id is not None
                # Same lock order and A-16 observer checks as resident HTTP.
                ticket, context = await self.tickets._context(
                    session,
                    delivery.recipient_user_id,
                    delivery.ticket_id,
                    write=True,
                    permission="work.observe",
                )
                delivery = await self._callback_delivery(session, callback)
                assert delivery.work_attempt_id is not None
                repo = TicketRepository(session)
                own = next(
                    (
                        o
                        for o in await repo.current_observations(delivery.work_attempt_id)
                        if o.actor_id == delivery.recipient_user_id
                    ),
                    None,
                )
                if own is None:
                    await self.tickets.observe(
                        session,
                        actor_id=context.actor_user_id,
                        attempt_id=delivery.work_attempt_id,
                        payload=ObservationCreate(outcome=callback.outcome),
                        idempotency_key=f"max:{callback.event_id}",
                    )
                # Replays cannot correct an already recorded answer. Corrections use Mini App.
                # Durable answer is independent of business commit and message reconciliation.
                reliability = ReliabilityRepository(session)
                await reliability.lock_idempotency(
                    actor_id=context.actor_user_id,
                    action="max.answer",
                    key=callback.event_id,
                )
                receipt = await reliability.idempotency_record(
                    actor_id=context.actor_user_id,
                    action="max.answer",
                    key=callback.event_id,
                )
                if receipt is None:
                    await reliability.add_job(
                        kind="max.ticket.answer", payload=payload, priority=40
                    )
                    reliability.add_idempotency(
                        actor_id=context.actor_user_id,
                        action="max.answer",
                        key=callback.event_id,
                        request_hash="",
                        response_status=200,
                        response_body={},
                    )
            except (AccessDenied, ResourceNotFound):
                return

    async def answer(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            raise MessagingError("MAX_DISABLED", kind="permanent")
        callback = TicketCallback.model_validate(payload)
        token = uuid4()
        async with self.sessions() as session, session.begin():
            try:
                delivery = await self._callback_delivery(session, callback)
                snapshot = await self._snapshot(session, delivery)
            except (AccessDenied, ResourceNotFound):
                return
            until = await NotificationRepository(session).reserve_destination(
                snapshot.destination,
                token,
                datetime.now(UTC),
            )
            if until:
                raise DeferredNotification(until)
        try:
            # Re-read after acquiring the destination gate, just like send/edit.
            async with self.sessions() as session:
                try:
                    delivery = await self._callback_delivery(session, callback)
                    snapshot = await self._snapshot(session, delivery)
                except (AccessDenied, ResourceNotFound):
                    return
            await self.provider.answer_callback(callback.callback_id, snapshot.message)
        finally:
            async with self.sessions() as session, session.begin():
                await NotificationRepository(session).release_destination(
                    snapshot.destination,
                    token,
                    datetime.now(UTC),
                )
