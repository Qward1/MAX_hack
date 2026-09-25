"""Жилищный навигатор (D3): профиль УК, «Мой дом», «Выполненные работы».

Сведения УК подписываются «по данным УК» с датой обновления: продукт их не
проверяет. Факты справочника — аварийные номера, памятка, официальные каналы
региона — только проверенные (`verified`) с источником и датой; непроверенное
не показывается. Тарифы, нормативы и капремонт здесь не появляются.

«Мой дом» и «Выполненные работы» видит только житель этого дома; сотрудник
без основания жителя получает 403, посторонний — маскированный 404.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.common import PageMeta
from domsignal.contracts.community import (
    CompanyProfileUpdate,
    CompanyProfileView,
    CompletedWork,
    CompletedWorkList,
    HouseFactsUpdate,
    HouseFactsView,
    HouseOverview,
    OverviewChannel,
    OverviewChat,
    OverviewCompany,
    OverviewEmergency,
    OverviewStep,
    VerifiedSource,
)
from domsignal.core.incidents import CATEGORY_TITLES, ReportCategory
from domsignal.core.responsibility import Verification
from domsignal.db.models import (
    ChatBinding,
    CompanyProfile,
    House,
    HouseManagement,
    Incident,
    ManagementCompany,
    ReceptionSlot,
    Ticket,
    TicketEvent,
    WorkAttempt,
)
from domsignal.db.repositories.routing import RoutingRepository
from domsignal.services.context import OperationContext
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.services.onboarding import audit, current_management, require_company
from domsignal.services.routing import RoutingService

#: Канал-телефон экстренных служб показывается в блоке аварийных номеров.
_EMERGENCY_CHANNEL_TYPES = frozenset({"phone"})

STEP_EMERGENCY = "При угрозе жизни и здоровью звоните по единому номеру {phone}."
STEP_DISPATCHER = "Аварийно-диспетчерская служба управляющей компании: {phone} (по данным УК)."
STEP_REPORT = (
    "Сообщите о проблеме в ДомСигнал — кнопка «Сообщить» на доске дома или сообщение боту. "
    "Если это зона УК, у неё появится заявка."
)
STEP_CHAT = "Сообщение в домовом чате не является официальным обращением."


def _source(verification: Verification) -> VerifiedSource:
    return VerifiedSource(
        title=verification.source_title or "Справочник ДомСигнала",
        url=verification.source_url,
        verified_at=verification.verified_at.isoformat() if verification.verified_at else None,
    )


def category_title(code: str) -> str:
    try:
        return CATEGORY_TITLES[ReportCategory(code)]
    except ValueError:
        return "Проблема дома"


class NavigatorService:
    def __init__(self, routing: RoutingService) -> None:
        self.routing = routing
        self.memberships = MembershipService()

    # ------------------------------------------------------------ профиль УК

    async def profile(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID
    ) -> CompanyProfileView:
        membership = await require_company(session, actor_id, company_id, admin=False)
        return await self._profile_view(
            session, company_id, can_edit=membership.role == "company_admin"
        )

    async def update_profile(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        payload: CompanyProfileUpdate,
    ) -> CompanyProfileView:
        """Администратор УК заполняет контакты. Транзакция — у вызывающего."""
        await require_company(session, actor_id, company_id)
        profile = await session.get(CompanyProfile, company_id, with_for_update=True)
        if profile is None:
            profile = CompanyProfile(tenant_id=company_id, updated_at=datetime.now(UTC))
            session.add(profile)
        for field, value in payload.model_dump().items():
            setattr(profile, field, value)
        profile.updated_at = datetime.now(UTC)
        profile.updated_by = actor_id
        audit(session, "company_profile.updated", actor_id, company_id)
        await session.flush()
        return await self._profile_view(session, company_id, can_edit=True)

    async def _profile_view(
        self, session: AsyncSession, company_id: UUID, *, can_edit: bool
    ) -> CompanyProfileView:
        company = await session.get(ManagementCompany, company_id)
        if company is None:
            raise ResourceNotFound("Ресурс не найден")
        profile = await session.get(CompanyProfile, company_id, populate_existing=True)
        fields = (
            {key: getattr(profile, key) for key in CompanyProfileUpdate.model_fields}
            if profile
            else {}
        )
        return CompanyProfileView(
            company_id=company.id,
            name=company.name,
            updated_at=profile.updated_at if profile else None,
            can_edit=can_edit,
            **fields,
        )

    async def update_house_facts(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        house_id: UUID,
        payload: HouseFactsUpdate,
    ) -> HouseFactsView:
        """Число подъездов и этажей «по данным УК» — только текущий управляющий дом."""
        await require_company(session, actor_id, company_id)
        managed = await session.scalar(
            select(HouseManagement.id).where(
                HouseManagement.house_id == house_id,
                HouseManagement.tenant_id == company_id,
                *current_management(),
            )
        )
        if managed is None:
            raise ResourceNotFound("Ресурс не найден")
        house = await session.get(House, house_id, with_for_update=True)
        assert house is not None
        house.entrance_count = payload.entrance_count
        house.floor_count = payload.floor_count
        house.facts_updated_at = datetime.now(UTC)
        house.facts_updated_by = actor_id
        audit(session, "house.facts_updated", actor_id, house_id)
        await session.flush()
        return HouseFactsView(
            house_id=house.id,
            entrance_count=house.entrance_count,
            floor_count=house.floor_count,
            facts_updated_at=house.facts_updated_at,
        )

    # -------------------------------------------------------------- «Мой дом»

    async def resident_context(
        self, session: AsyncSession, *, actor_id: UUID, house_id: UUID
    ) -> OperationContext:
        """Контекст жителя дома: сотрудник без основания жителя — 403."""
        context = await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        if not context.resident_access:
            raise AccessDenied("Раздел доступен жителям этого дома")
        return context

    async def overview(
        self, session: AsyncSession, *, actor_id: UUID, house_id: UUID
    ) -> HouseOverview:
        context = await self.resident_context(session, actor_id=actor_id, house_id=house_id)
        house = await session.get(House, house_id)
        assert house is not None
        management = await session.get(HouseManagement, context.management_id.value)
        company_view: OverviewCompany | None = None
        dispatcher: str | None = None
        reception = False
        if management is not None:
            company = await session.get(ManagementCompany, management.tenant_id)
            profile = await session.get(CompanyProfile, management.tenant_id)
            if company is not None:
                company_view = OverviewCompany(
                    name=company.name,
                    updated_at=profile.updated_at if profile else None,
                    **(
                        {key: getattr(profile, key) for key in CompanyProfileUpdate.model_fields}
                        if profile
                        else {}
                    ),
                )
                dispatcher = profile.dispatcher_phone if profile else None
            reception = bool(
                await session.scalar(
                    select(func.count())
                    .select_from(ReceptionSlot)
                    .where(
                        ReceptionSlot.tenant_id == management.tenant_id,
                        ReceptionSlot.status == "open",
                        ReceptionSlot.starts_at > datetime.now(UTC),
                    )
                )
            )
        bindings = list(
            await session.scalars(
                select(ChatBinding).where(
                    ChatBinding.house_id == house_id,
                    ChatBinding.status == "active",
                    ChatBinding.management_id == context.management_id.value,
                )
            )
        )
        emergency, channels, emergency_phone = await self._directory(session, house_id)
        steps: list[OverviewStep] = []
        if emergency_phone is not None:
            steps.append(
                OverviewStep(
                    text=STEP_EMERGENCY.format(phone=emergency_phone[0]),
                    basis="directory",
                    phone=emergency_phone[0],
                    source=emergency_phone[1],
                )
            )
        if dispatcher:
            steps.append(
                OverviewStep(
                    text=STEP_DISPATCHER.format(phone=dispatcher), basis="company", phone=dispatcher
                )
            )
        steps.append(OverviewStep(text=STEP_REPORT, basis="product"))
        if bindings:
            steps.append(OverviewStep(text=STEP_CHAT, basis="product"))
        return HouseOverview(
            house_id=house.id,
            name=house.name,
            address=house.address,
            entrance_count=house.entrance_count,
            floor_count=house.floor_count,
            facts_updated_at=house.facts_updated_at,
            company=company_view,
            chat=OverviewChat(
                connected=bool(bindings),
                reading_enabled=any(binding.passive_capture_enabled for binding in bindings),
            ),
            emergency=emergency,
            channels=channels,
            accident_steps=steps,
            reception_available=reception,
        )

    async def _directory(
        self, session: AsyncSession, house_id: UUID
    ) -> tuple[list[OverviewEmergency], list[OverviewChannel], tuple[str, VerifiedSource] | None]:
        """Проверенные записи справочника для региона дома."""
        directory = self.routing.directory
        if directory is None:
            return [], [], None
        profile = await RoutingRepository(session).profile(house_id)
        region = profile.region_code if profile else None
        municipality = profile.municipality_code if profile else None
        effective = directory.effective(region, municipality)
        emergency: list[OverviewEmergency] = []
        emergency_phone: tuple[str, VerifiedSource] | None = None
        for block in effective.safety:
            if block.verification.status != "verified":
                continue
            source = _source(block.verification)
            emergency.append(
                OverviewEmergency(
                    title=block.title, phone=block.phone, lines=list(block.lines), source=source
                )
            )
            if block.phone and emergency_phone is None:
                emergency_phone = (block.phone, source)
        channels: list[OverviewChannel] = []
        for channel in effective.channels.values():
            if channel.verification.status != "verified" or not channel.available_in(region):
                continue
            if channel.channel_type in _EMERGENCY_CHANNEL_TYPES and channel.phone:
                if not any(item.phone == channel.phone for item in emergency):
                    emergency.append(
                        OverviewEmergency(
                            title=channel.label,
                            phone=channel.phone,
                            lines=[],
                            source=_source(channel.verification),
                        )
                    )
                continue
            channels.append(
                OverviewChannel(
                    id=channel.id,
                    label=channel.label,
                    channel_type=channel.channel_type,
                    url=channel.url,
                    phone=channel.phone,
                    source=_source(channel.verification),
                )
            )
        return emergency, channels, emergency_phone

    # -------------------------------------------------------- выполненные работы

    async def completed_works(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        days: Literal[30, 90],
        limit: int,
        offset: int,
    ) -> CompletedWorkList:
        """Закрытые и возвращённые в работу заявки дома: только публичная проекция."""
        context = await self.resident_context(session, actor_id=actor_id, house_id=house_id)
        self.memberships.require_permission(context, "work.read")
        since = datetime.now(UTC) - timedelta(days=days)
        confirmed = and_(Ticket.status == "closed", Ticket.latest_attempt_id == WorkAttempt.id)
        query = (
            select(WorkAttempt, Ticket, Incident)
            .join(Ticket, Ticket.id == WorkAttempt.ticket_id)
            .join(Incident, Incident.id == Ticket.incident_id)
            .where(
                Ticket.house_id == house_id,
                Ticket.management_id == context.management_id.value,
                WorkAttempt.created_at >= since,
                or_(WorkAttempt.rework_required.is_(True), confirmed),
            )
        )
        total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = (
            await session.execute(
                query.order_by(WorkAttempt.created_at.desc(), WorkAttempt.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        attempt_ids = [row[0].id for row in rows]
        moments: dict[tuple[UUID, str], datetime] = {}
        if attempt_ids:
            for attempt_id, kind, at in (
                await session.execute(
                    select(
                        TicketEvent.attempt_id, TicketEvent.kind, func.min(TicketEvent.created_at)
                    )
                    .where(
                        TicketEvent.attempt_id.in_(attempt_ids),
                        TicketEvent.kind.in_(["result_confirmed", "result_objected"]),
                    )
                    .group_by(TicketEvent.attempt_id, TicketEvent.kind)
                )
            ).all():
                if attempt_id is not None:
                    moments[(attempt_id, kind)] = at
        items = []
        for attempt, _ticket, incident in rows:
            returned = attempt.rework_required
            items.append(
                CompletedWork(
                    attempt_id=attempt.id,
                    incident_id=incident.id,
                    category=incident.category,
                    category_title=category_title(incident.category),
                    entrance=incident.location_entrance,
                    public_description=attempt.public_description,
                    reported_at=attempt.created_at,
                    outcome="returned" if returned else "confirmed",
                    outcome_at=moments.get(
                        (attempt.id, "result_objected" if returned else "result_confirmed")
                    ),
                )
            )
        return CompletedWorkList(
            days=days,
            items=items,
            page=PageMeta(limit=limit, offset=offset, total=total),
        )


__all__ = ["NavigatorService", "category_title"]
