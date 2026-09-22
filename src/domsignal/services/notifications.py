"""A-05 delivery consumer of A-16 intents, not a second Ticket workflow/outbox."""

import logging
import re
import secrets
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
from domsignal.core.incidents import CATEGORY_TITLES
from domsignal.db.models import (
    ChatBinding,
    House,
    HouseManagement,
    Incident,
    MAXChat,
    NotificationDelivery,
    OrganizationMembership,
    OutboxMessage,
    Report,
    RouteOutcome,
    Signal,
    SignalEvent,
    Ticket,
    TicketEvent,
    User,
)
from domsignal.db.models.notifications import CHAT_PURPOSES, SIGNAL_ALERT_PURPOSE
from domsignal.db.repositories.notifications import NotificationRepository
from domsignal.db.repositories.passive import PassiveRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.db.repositories.tickets import TicketRepository
from domsignal.services.chat_voice import (
    ALERT_REF_PREFIX,
    CHAT_MESSAGE_INTENT_KIND,
    CHAT_REF_PREFIX,
    ChatMessageIntent,
    SignalAlertIntent,
    chat_message,
    operator_alert_message,
)
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.notification_render import actionable, render
from domsignal.services.route_card_render import (
    ROUTE_CARD_INTENT_KIND,
    ROUTE_CARD_REF_PREFIX,
    RouteCardIntent,
    render_route_card,
)
from domsignal.services.tickets import TicketService

logger = logging.getLogger(__name__)

#: Назначение доставки для карточки маршрута.
ROUTE_CARD_PURPOSE = "route_action_card"


@dataclass(frozen=True)
class DeliverySnapshot:
    destination: str
    message: PersonalMessage
    # У карточки маршрута нет состояния работы: она не относится к заявке.
    view: ResidentWorkStatus | None = None


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
    ) -> None:
        self.sessions = session_factory
        self.tickets = tickets
        self.provider = provider
        self.enabled = enabled

    async def _snapshot(
        self,
        session: AsyncSession,
        delivery: NotificationDelivery,
    ) -> DeliverySnapshot:
        if delivery.purpose == ROUTE_CARD_PURPOSE:
            return await self._route_card_snapshot(session, delivery)
        if delivery.purpose == SIGNAL_ALERT_PURPOSE:
            return await self._signal_alert_snapshot(session, delivery)
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
        quote = await PassiveRepository(session).first_quote(signal.id)
        emergency = signal.emergency or {}
        return DeliverySnapshot(
            destination,
            operator_alert_message(
                house_address=house.address if house is not None else "",
                danger_kinds=list(emergency.get("kinds", [])),
                from_rules="rules" in emergency.get("sources", []),
                quote=quote.text if quote else None,
                quote_author=quote.author_ref if quote else None,
                quote_sent_at=quote.sent_at if quote else None,
            ),
        )

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
            or not binding.passive_capture_enabled
        ):
            raise ResourceNotFound("CHAT_BINDING_INACTIVE")
        chat = await session.scalar(
            select(MAXChat)
            .where(MAXChat.max_chat_id == binding.max_chat_id)
            .execution_options(populate_existing=True)
        )
        if chat is None or not chat.bot_present:
            raise ResourceNotFound("CHAT_BINDING_INACTIVE")
        return DeliverySnapshot(binding.max_chat_id, chat_message(intent))

    async def _identity(self, user: User, delivery: NotificationDelivery) -> str:
        """Личная доставка возможна только в подтверждённую личность MAX."""
        if (
            not user.max_identity_verified_at
            or not user.max_user_id
            or not re.fullmatch(r"[1-9]\d{0,18}", user.max_user_id)
            or int(user.max_user_id) > 2**63 - 1
        ):
            raise ResourceNotFound("NO_MAX_IDENTITY")
        if delivery.destination and user.max_user_id != delivery.destination:
            raise ResourceNotFound("MAX_IDENTITY_CHANGED")
        return user.max_user_id

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
        delivery.status = "skipped" if code == "NO_MAX_IDENTITY" else "superseded"
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
            purposes = {"accepted": "ticket_accepted", "work_reported": "work_verification"}
            purpose = purposes.get(event.kind)
            if purpose:
                for user_id in await repo.recipients(ticket.incident_id):
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
            except (AccessDenied, ResourceNotFound):
                self._stop(delivery, "ACCESS_REVOKED", at)
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
                    snapshot.view.version or 0 if snapshot.view is not None else 0
                )
                delivery.desired_version = max(delivery.desired_version, delivery.applied_version)
                delivery.retry_count = 0
                delivery.next_attempt_at = None
                delivery.last_error_code = None
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
        if not re.fullmatch(r"[wr]_[A-Za-z0-9_-]{32}", ref):
            raise ResourceNotFound("Resource was not found")
        delivery = await NotificationRepository(session).by_ref(ref)
        if delivery is None or delivery.recipient_user_id != actor_id:
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
