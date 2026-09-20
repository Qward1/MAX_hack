from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.common import PageMeta
from domsignal.contracts.incidents import (
    IncidentDetail,
    IncidentList,
    IncidentLocation,
    IncidentSummary,
    Provenance,
    ReportCreate,
    ReportCreated,
    ReportSummary,
    RuleProvenance,
)
from domsignal.contracts.routing import ActionCard, DangerKind, LocationScope
from domsignal.core.incidents import CATEGORY_TITLES, IncidentStatus, ReportCategory
from domsignal.core.routing import UNSPECIFIED_SUBTYPE
from domsignal.db.models import Incident, Report
from domsignal.db.repositories.incidents import IncidentRepository
from domsignal.db.repositories.reliability import ReliabilityRepository, stable_hash
from domsignal.services.action_cards import ActionCardBuilder
from domsignal.services.context import OperationContext, OperationSource
from domsignal.services.errors import IdempotencyConflict, ResourceNotFound, ServiceError
from domsignal.services.membership import MembershipService
from domsignal.services.routing import RoutingService
from domsignal.services.tickets import TicketService


@dataclass(frozen=True)
class DemoRule:
    source_url: str
    source_title: str
    verification_status: str
    note: str


def _location_of(incident: Incident) -> IncidentLocation | None:
    """Место инцидента, если оно было заполнено значением с цитатой."""
    location = IncidentLocation(
        entrance=incident.location_entrance,
        floor=incident.location_floor,
        label=incident.location_label,
        observed_since=incident.observed_since,
    )
    return location if location.model_dump(exclude_none=True) else None


class IncidentClosed(ServiceError):
    status = 409
    code = "incident_closed"
    title = "Проблема уже закрыта"


class ReportService:
    def __init__(
        self,
        *,
        demo_rule: DemoRule,
        routing: RoutingService | None = None,
        action_cards: ActionCardBuilder | None = None,
    ) -> None:
        self.demo_rule = demo_rule
        self.routing = routing
        self.action_cards = action_cards
        self.memberships = MembershipService()

    async def action_card_for(
        self,
        session: AsyncSession,
        *,
        house_id: UUID,
        subtype: str = UNSPECIFIED_SUBTYPE,
        location_scope: LocationScope = "house_common",
        danger_kinds: Sequence[DangerKind] = (),
        existing_ticket_ref: str | None = None,
    ) -> ActionCard | None:
        """Карточка следующего шага для ответа на создание заявки.

        Ручной путь не знает подтипа, но житель уже выбрал категорию проблемы
        дома, поэтому территория по умолчанию — общее имущество: маршрут ведёт
        в УК, а не в честное «не определено».
        """
        if self.routing is None or self.action_cards is None:
            return None
        route, house = await self.routing.route_for_house(
            session,
            house_id=house_id,
            subtype=subtype,
            location_scope=location_scope,
            danger_kinds=danger_kinds,
        )
        return self.action_cards.build(
            route,
            house,
            audience="resident",
            source="explicit",
            danger_kinds=danger_kinds,
            existing_ticket_ref=existing_ticket_ref,
        )

    async def create(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        payload: ReportCreate,
        idempotency_key: str,
        provenance: OperationSource = "api",
    ) -> ReportCreated:
        async with session.begin():
            context = await self.memberships.require_house(
                session,
                user_id=actor_id,
                house_id=payload.house_id,
                source=provenance,
                for_write=True,
            )
            return await self.create_in_context(
                session,
                context=context,
                payload=payload,
                idempotency_key=idempotency_key,
            )

    async def create_in_context(
        self,
        session: AsyncSession,
        *,
        context: OperationContext,
        payload: ReportCreate,
        idempotency_key: str,
        subtype: str = UNSPECIFIED_SUBTYPE,
        location_scope: LocationScope = "house_common",
        danger_kinds: Sequence[DangerKind] = (),
    ) -> ReportCreated:
        """Internal entry point; caller resolves/locks context in this transaction."""
        if payload.house_id != context.house_id:
            raise ResourceNotFound("Resource was not found")
        actor_id = context.actor_user_id
        request_hash = stable_hash(payload.model_dump(mode="json"))
        action = "report.create"
        reliability = ReliabilityRepository(session)
        self.memberships.require_permission(context, "report.create")
        await reliability.lock_idempotency(actor_id=actor_id, action=action, key=idempotency_key)
        existing = await reliability.idempotency_record(
            actor_id=actor_id, action=action, key=idempotency_key
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                raise IdempotencyConflict(
                    "This Idempotency-Key was already used with a different request body"
                )
            # Stored C0 receipts contain the old read DTO. Preserve the effect/IDs,
            # but publish the current authorized representation on every replay.
            return ReportCreated(
                report_id=UUID(existing.response_body["report_id"]),
                incident=await self.detail(
                    session,
                    actor_id=context.actor_user_id,
                    incident_id=UUID(existing.response_body["incident"]["id"]),
                    house_id=context.house_id,
                ),
                action_card=await self.action_card_for(
                    session,
                    house_id=context.house_id,
                    subtype=subtype,
                    location_scope=location_scope,
                    danger_kinds=danger_kinds,
                ),
            )

        repo = IncidentRepository(session)
        incident = await repo.create_incident(
            context=context,
            category=payload.category.value,
            title=CATEGORY_TITLES[payload.category],
            description=payload.description,
        )
        report = await repo.create_report(
            incident_id=incident.id,
            house_id=context.house_id,
            author_id=context.actor_user_id,
            category=payload.category.value,
            description=payload.description,
            classification_mode=payload.classification_mode.value,
            provenance=context.source,
        )
        await TicketService().ensure(session, context=context, incident_id=incident.id)
        response = ReportCreated(
            report_id=report.id,
            incident=self._detail(
                incident, [report], is_demo=await repo.house_is_demo(context.house_id)
            ),
            action_card=await self.action_card_for(
                session,
                house_id=context.house_id,
                subtype=subtype,
                location_scope=location_scope,
                danger_kinds=danger_kinds,
            ),
        )
        # Карточка собирается заново при каждом чтении, поэтому в квитанции
        # идемпотентности она не сохраняется: справочник мог обновиться.
        response_body = response.model_dump(mode="json", exclude={"action_card"})
        reliability.add_idempotency(
            actor_id=actor_id,
            action=action,
            key=idempotency_key,
            request_hash=request_hash,
            response_status=201,
            response_body=response_body,
        )
        reliability.add_outbox(
            kind="incident.created",
            aggregate_id=incident.id,
            payload={
                "incident_id": str(incident.id),
                "house_id": str(incident.house_id),
                "chat_binding_id": str(context.chat_binding_id.value)
                if context.chat_binding_id.value
                else None,
                "binding_version": context.binding_version.value,
                "entrance": context.entrance,
            },
        )
        return response

    async def join(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        incident_id: UUID,
        idempotency_key: str,
    ) -> IncidentDetail:
        """Присоединиться к уже созданной проблеме того же дома.

        Появляется ещё один `Report` под тем же `Incident`: у проблемы растёт
        число участников. Новый Ticket не создаётся — заявка уже есть, и второй
        не нужен. Закрытая проблема не принимает присоединение.
        """
        repo = IncidentRepository(session)
        async with session.begin():
            # До разрешения доступа читается только маршрутная метаинформация.
            house_id = await repo.incident_house_id(incident_id)
            if house_id is None:
                raise ResourceNotFound("Resource was not found")
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=house_id, for_write=True
            )
            self.memberships.require_permission(context, "report.create")
            action = "incident.join"
            reliability = ReliabilityRepository(session)
            await reliability.lock_idempotency(
                actor_id=actor_id, action=action, key=idempotency_key
            )
            existing = await reliability.idempotency_record(
                actor_id=actor_id, action=action, key=idempotency_key
            )
            incident = await repo.incident(incident_id, context=context)
            if incident is None:
                raise ResourceNotFound("Resource was not found")
            if existing is not None:
                if existing.request_hash != stable_hash({"incident_id": str(incident_id)}):
                    raise IdempotencyConflict(
                        "This Idempotency-Key was already used with a different request body"
                    )
                return self._detail(
                    incident,
                    await repo.reports(incident_id),
                    is_demo=await repo.house_is_demo(context.house_id),
                )
            if incident.status != IncidentStatus.OPEN.value:
                raise IncidentClosed("Эта проблема уже закрыта, присоединиться нельзя")
            await repo.create_report(
                incident_id=incident.id,
                house_id=context.house_id,
                author_id=context.actor_user_id,
                category=incident.category,
                # Житель подтверждает уже описанную проблему, а не описывает свою.
                description=incident.description,
                classification_mode="manual",
                provenance=context.source,
            )
            detail = self._detail(
                incident,
                await repo.reports(incident_id),
                is_demo=await repo.house_is_demo(context.house_id),
            )
            reliability.add_idempotency(
                actor_id=actor_id,
                action=action,
                key=idempotency_key,
                request_hash=stable_hash({"incident_id": str(incident_id)}),
                response_status=200,
                response_body=detail.model_dump(mode="json"),
            )
            return detail

    async def list_for_house(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        limit: int,
        offset: int,
    ) -> IncidentList:
        context = await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        repo = IncidentRepository(session)
        self.memberships.require_permission(context, "incident.read")
        incidents, total = await repo.list_for_house(context, limit=limit, offset=offset)
        counts = await repo.counts([item.id for item in incidents])
        is_demo = await repo.house_is_demo(context.house_id)
        return IncidentList(
            items=[
                self._summary(incident, counts=counts.get(incident.id, (0, 0)), is_demo=is_demo)
                for incident in incidents
            ],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    async def detail(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        incident_id: UUID,
        house_id: UUID | None = None,
    ) -> IncidentDetail:
        repo = IncidentRepository(session)
        resolved_house = house_id or await repo.incident_house_id(incident_id)
        if resolved_house is None:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(
            session,
            user_id=actor_id,
            house_id=resolved_house,
        )
        self.memberships.require_permission(context, "incident.read")
        incident = await repo.incident(incident_id, context=context)
        if incident is None:
            raise ResourceNotFound("Resource was not found")
        reports = await repo.reports(incident_id)
        return self._detail(incident, reports, is_demo=await repo.house_is_demo(context.house_id))

    def _summary(
        self, incident: Incident, *, counts: tuple[int, int], is_demo: bool
    ) -> IncidentSummary:
        return IncidentSummary(
            id=incident.id,
            house_id=incident.house_id,
            category=ReportCategory(incident.category),
            title=incident.title,
            description=incident.description,
            status=IncidentStatus(incident.status),
            created_at=incident.created_at,
            updated_at=None,  # C0 stores no update event/time; do not substitute created_at.
            due_at=None,
            # Место отдаётся только из сохранённых полей: при чтении текст
            # по-прежнему не разбирается.
            location=_location_of(incident),
            report_count=counts[0],
            participant_count=counts[1],
            is_demo=is_demo,
            provenance=Provenance(
                origin="demo" if is_demo else "user_reported",
                recorded_at=incident.created_at,
            ),
        )

    def _detail(
        self, incident: Incident, reports: list[Report], *, is_demo: bool
    ) -> IncidentDetail:
        summary = self._summary(
            incident,
            counts=(len(reports), len({item.author_id for item in reports})),
            is_demo=is_demo,
        )
        detail = IncidentDetail(
            **summary.model_dump(),
            reports=[
                ReportSummary(id=item.id, description=item.description, created_at=item.created_at)
                for item in reports
            ],
            rule=RuleProvenance(
                origin="demo",  # This is explicitly DemoRule, not a routing engine result.
                verification_status=cast(
                    Literal["verified", "needs_verification", "demo"],
                    self.demo_rule.verification_status,
                ),
                source_url=self.demo_rule.source_url,
                source_title=self.demo_rule.source_title,
                due_at=None,
                note=self.demo_rule.note,
            ),
        )
        return detail
