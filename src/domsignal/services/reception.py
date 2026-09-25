"""Запись на приём в УК (D3, §9). Без оплаты и внешних календарей.

Администратор УК задаёт слоты: дата и время, длительность, вместимость,
место. Житель дома этой УК выбирает слот и тему, может отменить запись.
Сотрудники УК видят список записей. Накануне бот напоминает в личке — только
если запись в силе и бот может написать жителю.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.contracts.community import (
    ReceptionBookingCreate,
    ReceptionBookingStaffView,
    ReceptionOverview,
    ReceptionSlotCreate,
    ReceptionSlotView,
    ResidentBookingView,
    ResidentSlotView,
)
from domsignal.db.models import (
    CompanyProfile,
    House,
    HouseManagement,
    ManagementCompany,
    NotificationDelivery,
    OutboxMessage,
    ReceptionBooking,
    ReceptionSlot,
    User,
)
from domsignal.db.models.notifications import RECEPTION_REMINDER_PURPOSE
from domsignal.services.community_delivery import max_destination
from domsignal.services.community_texts import (
    OPEN_APP_LABEL,
    RECEPTION_PLACE,
    RECEPTION_REMINDER,
    moment,
)
from domsignal.services.errors import (
    AccessDenied,
    FieldValidationError,
    RescheduleJob,
    ResourceNotFound,
    ServiceError,
)
from domsignal.services.navigator import NavigatorService
from domsignal.services.onboarding import audit, require_company

logger = logging.getLogger(__name__)

TICK_JOB = "reception.reminder.tick"
TICK_INTERVAL = timedelta(minutes=15)
REMIND_BEFORE = timedelta(hours=24)
KEY_PREFIX = "reception:"
REF_PREFIX = "v_"
OPEN_APP_PAYLOAD = "home"


class SlotFull(ServiceError):
    status = 409
    code = "slot_full"
    title = "Мест нет"


class ReceptionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        navigator: NavigatorService,
    ) -> None:
        self.sessions = session_factory
        self.navigator = navigator

    # ------------------------------------------------------------ сотрудники

    async def create_slot(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        payload: ReceptionSlotCreate,
    ) -> ReceptionSlotView:
        await require_company(session, actor_id, company_id)
        if payload.starts_at <= datetime.now(UTC):
            raise FieldValidationError("Время приёма уже прошло", field="starts_at")
        slot = ReceptionSlot(
            id=uuid4(),
            tenant_id=company_id,
            starts_at=payload.starts_at,
            duration_minutes=payload.duration_minutes,
            capacity=payload.capacity,
            place=(payload.place or "").strip() or None,
            status="open",
            created_by=actor_id,
        )
        session.add(slot)
        audit(session, "reception.slot_created", actor_id, slot.id)
        await session.flush()
        return (await self._slots(session, company_id, [slot.id]))[0]

    async def cancel_slot(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID, slot_id: UUID
    ) -> ReceptionSlotView:
        await require_company(session, actor_id, company_id)
        slot = await session.get(ReceptionSlot, slot_id, with_for_update=True)
        if slot is None or slot.tenant_id != company_id:
            raise ResourceNotFound("Ресурс не найден")
        slot.status = "cancelled"
        audit(session, "reception.slot_cancelled", actor_id, slot.id)
        await session.flush()
        return (await self._slots(session, company_id, [slot.id]))[0]

    async def list_slots(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID
    ) -> list[ReceptionSlotView]:
        await require_company(session, actor_id, company_id, admin=False)
        return await self._slots(session, company_id, None)

    async def _slots(
        self, session: AsyncSession, company_id: UUID, ids: list[UUID] | None
    ) -> list[ReceptionSlotView]:
        query = select(ReceptionSlot).where(ReceptionSlot.tenant_id == company_id)
        if ids is not None:
            query = query.where(ReceptionSlot.id.in_(ids))
        else:
            query = query.where(ReceptionSlot.starts_at > datetime.now(UTC) - timedelta(days=7))
        slots = list(await session.scalars(query.order_by(ReceptionSlot.starts_at)))
        result = []
        for slot in slots:
            rows = (
                await session.execute(
                    select(ReceptionBooking, House.address, User.display_name)
                    .join(House, House.id == ReceptionBooking.house_id)
                    .join(User, User.id == ReceptionBooking.user_id)
                    .where(ReceptionBooking.slot_id == slot.id)
                    .order_by(ReceptionBooking.created_at)
                )
            ).tuples()
            bookings = [
                ReceptionBookingStaffView(
                    id=booking.id,
                    topic=booking.topic,
                    house_address=address,
                    resident_name=name,
                    status=booking.status,
                    created_at=booking.created_at,
                )
                for booking, address, name in rows
            ]
            result.append(
                ReceptionSlotView(
                    id=slot.id,
                    starts_at=slot.starts_at,
                    duration_minutes=slot.duration_minutes,
                    capacity=slot.capacity,
                    booked=sum(1 for item in bookings if item.status == "booked"),
                    place=slot.place,
                    status=slot.status,
                    bookings=bookings,
                )
            )
        return result

    # ------------------------------------------------------------------ жители

    async def _company_of(self, session: AsyncSession, house_id: UUID, actor_id: UUID) -> UUID:
        context = await self.navigator.resident_context(
            session, actor_id=actor_id, house_id=house_id
        )
        management = await session.get(HouseManagement, context.management_id.value)
        if management is None:
            raise ResourceNotFound("Resource was not found")
        return management.tenant_id

    async def overview(
        self, session: AsyncSession, *, actor_id: UUID, house_id: UUID
    ) -> ReceptionOverview:
        company_id = await self._company_of(session, house_id, actor_id)
        company = await session.get(ManagementCompany, company_id)
        profile = await session.get(CompanyProfile, company_id)
        now = datetime.now(UTC)
        slots = list(
            await session.scalars(
                select(ReceptionSlot)
                .where(
                    ReceptionSlot.tenant_id == company_id,
                    ReceptionSlot.status == "open",
                    ReceptionSlot.starts_at > now,
                )
                .order_by(ReceptionSlot.starts_at)
                .limit(50)
            )
        )
        counts = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(ReceptionBooking.slot_id, func.count())
                    .where(
                        ReceptionBooking.slot_id.in_([slot.id for slot in slots]),
                        ReceptionBooking.status == "booked",
                    )
                    .group_by(ReceptionBooking.slot_id)
                )
            )
        }
        mine = list(
            await session.scalars(
                select(ReceptionBooking)
                .join(ReceptionSlot, ReceptionSlot.id == ReceptionBooking.slot_id)
                .where(
                    ReceptionBooking.user_id == actor_id,
                    ReceptionSlot.tenant_id == company_id,
                    ReceptionSlot.starts_at > now - timedelta(days=1),
                )
                .order_by(ReceptionSlot.starts_at)
            )
        )
        by_slot = {booking.slot_id: booking.id for booking in mine if booking.status == "booked"}
        slot_rows = {
            slot.id: slot
            for slot in await session.scalars(
                select(ReceptionSlot).where(ReceptionSlot.id.in_([b.slot_id for b in mine]))
            )
        }
        default_place = profile.office_address if profile else None
        return ReceptionOverview(
            company_name=company.name if company else "",
            slots=[
                ResidentSlotView(
                    id=slot.id,
                    starts_at=slot.starts_at,
                    duration_minutes=slot.duration_minutes,
                    place=slot.place or default_place,
                    free=max(slot.capacity - counts.get(slot.id, 0), 0),
                    my_booking_id=by_slot.get(slot.id),
                )
                for slot in slots
            ],
            bookings=[
                ResidentBookingView(
                    id=booking.id,
                    slot_id=booking.slot_id,
                    starts_at=slot_rows[booking.slot_id].starts_at,
                    duration_minutes=slot_rows[booking.slot_id].duration_minutes,
                    place=slot_rows[booking.slot_id].place or default_place,
                    topic=booking.topic,
                    status=booking.status,
                )
                for booking in mine
            ],
        )

    async def book(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        payload: ReceptionBookingCreate,
    ) -> ReceptionOverview:
        company_id = await self._company_of(session, house_id, actor_id)
        slot = await session.get(ReceptionSlot, payload.slot_id, with_for_update=True)
        if slot is None or slot.tenant_id != company_id:
            raise ResourceNotFound("Resource was not found")
        if slot.status != "open" or slot.starts_at <= datetime.now(UTC):
            raise SlotFull("Это время уже недоступно. Выберите другое.")
        existing = await session.scalar(
            select(ReceptionBooking.id).where(
                ReceptionBooking.slot_id == slot.id,
                ReceptionBooking.user_id == actor_id,
                ReceptionBooking.status == "booked",
            )
        )
        if existing is None:
            booked = await session.scalar(
                select(func.count())
                .select_from(ReceptionBooking)
                .where(ReceptionBooking.slot_id == slot.id, ReceptionBooking.status == "booked")
            )
            if (booked or 0) >= slot.capacity:
                raise SlotFull("На это время мест нет. Выберите другое.")
            session.add(
                ReceptionBooking(
                    id=uuid4(),
                    slot_id=slot.id,
                    user_id=actor_id,
                    house_id=house_id,
                    topic=payload.topic.strip(),
                    status="booked",
                )
            )
            await session.flush()
        return await self.overview(session, actor_id=actor_id, house_id=house_id)

    async def cancel_booking(
        self, session: AsyncSession, *, actor_id: UUID, house_id: UUID, booking_id: UUID
    ) -> ReceptionOverview:
        await self._company_of(session, house_id, actor_id)
        booking = await session.get(ReceptionBooking, booking_id, with_for_update=True)
        if booking is None or booking.user_id != actor_id:
            raise ResourceNotFound("Resource was not found")
        if booking.status == "booked":
            booking.status = "cancelled"
            booking.cancelled_at = datetime.now(UTC)
            await session.flush()
        return await self.overview(session, actor_id=actor_id, house_id=house_id)

    # --------------------------------------------------------------- напоминание

    async def tick(self, payload: dict[str, Any], *, now: datetime | None = None) -> None:
        del payload
        at = now or datetime.now(UTC)
        await self.enqueue_reminders(now=at)
        raise RescheduleJob(at + TICK_INTERVAL)

    async def enqueue_reminders(self, *, now: datetime | None = None) -> int:
        """Напоминания накануне: запись в силе, приём в ближайшие 24 часа."""
        at = now or datetime.now(UTC)
        queued = 0
        async with self.sessions() as session, session.begin():
            bookings = list(
                await session.scalars(
                    select(ReceptionBooking)
                    .join(ReceptionSlot, ReceptionSlot.id == ReceptionBooking.slot_id)
                    .where(
                        ReceptionBooking.status == "booked",
                        ReceptionSlot.status == "open",
                        ReceptionSlot.starts_at > at,
                        ReceptionSlot.starts_at <= at + REMIND_BEFORE,
                    )
                )
            )
            for booking in bookings:
                key = f"{KEY_PREFIX}{booking.id}"
                outbox_id = uuid4()
                inserted = await session.scalar(
                    insert(OutboxMessage)
                    .values(
                        id=outbox_id,
                        kind="reception.reminder.v1",
                        aggregate_id=booking.id,
                        payload={"booking_id": str(booking.id)},
                        status="processed",
                        dedupe_key=key,
                    )
                    .on_conflict_do_nothing(index_elements=[OutboxMessage.dedupe_key])
                    .returning(OutboxMessage.id)
                )
                if inserted is None:
                    continue
                session.add(
                    NotificationDelivery(
                        id=uuid4(),
                        outbox_message_id=outbox_id,
                        recipient_user_id=booking.user_id,
                        channel="max",
                        purpose=RECEPTION_REMINDER_PURPOSE,
                        reply_event_id=key,
                        launch_ref=REF_PREFIX + secrets.token_urlsafe(24),
                        status="pending",
                        desired_version=0,
                    )
                )
                queued += 1
        return queued

    async def snapshot(
        self, session: AsyncSession, delivery: NotificationDelivery
    ) -> tuple[str, PersonalMessage, int]:
        try:
            booking_id = UUID((delivery.reply_event_id or "").removeprefix(KEY_PREFIX))
        except ValueError:
            raise ResourceNotFound("INVALID_INTENT") from None
        booking = await session.get(ReceptionBooking, booking_id, populate_existing=True)
        if booking is None or booking.status != "booked":
            raise ResourceNotFound("RETRACTED")
        slot = await session.get(ReceptionSlot, booking.slot_id, populate_existing=True)
        if slot is None or slot.status != "open" or slot.starts_at <= datetime.now(UTC):
            raise ResourceNotFound("RETRACTED")
        try:
            await self.navigator.resident_context(
                session, actor_id=booking.user_id, house_id=booking.house_id
            )
        except (AccessDenied, ResourceNotFound):
            raise ResourceNotFound("ACCESS_REVOKED") from None
        user = await session.get(User, booking.user_id, populate_existing=True)
        company = await session.get(ManagementCompany, slot.tenant_id)
        profile = await session.get(CompanyProfile, slot.tenant_id)
        if user is None or company is None:
            raise ResourceNotFound("ACCESS_REVOKED")
        lines = [
            RECEPTION_REMINDER.format(
                when=moment(slot.starts_at), company=company.name, topic=booking.topic
            )
        ]
        place = slot.place or (profile.office_address if profile else None)
        if place:
            lines.append(RECEPTION_PLACE.format(place=place))
        return (
            max_destination(user, delivery),
            PersonalMessage(
                "\n".join(lines),
                ((MessageButton("open_app", OPEN_APP_LABEL, OPEN_APP_PAYLOAD),),),
            ),
            0,
        )


__all__ = ["ReceptionService", "SlotFull", "TICK_JOB"]
