"""Ticket application boundary shared by intake, staff API and resident verification.

Write lock order: A-15 house SHARE -> Incident UPDATE -> Ticket/Attempt.
The Incident lock serializes absence/creation, reopen, attempt and observation decisions.
No network effects occur in these transactions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.common import PageMeta
from domsignal.contracts.tickets import (
    AssignCommand,
    AssigneeList,
    AssigneeView,
    AttemptList,
    AttemptPublic,
    AttemptView,
    DeadlineCreate,
    DeadlineList,
    DeadlinePublic,
    DeadlineView,
    EventList,
    EventView,
    ObservationCreate,
    ObservationList,
    ObservationRecorded,
    ObservationView,
    OwnObservation,
    OwnObservationList,
    ReasonCommand,
    ResidentWorkStatus,
    TicketCommand,
    TicketList,
    TicketMutation,
    TicketNotificationIntent,
    TicketView,
    WorkAttemptCreate,
)
from domsignal.core.tickets import (
    TicketAction,
    TicketEventKind,
    observation_status,
    transition_allowed,
)
from domsignal.db.models import (
    HouseManagement,
    Incident,
    Report,
    ResultObservation,
    Ticket,
    TicketDeadline,
    TicketEvent,
    User,
    WorkAttempt,
)
from domsignal.db.repositories.reliability import ReliabilityRepository, stable_hash
from domsignal.db.repositories.tickets import TicketRepository
from domsignal.services.context import OperationContext
from domsignal.services.errors import (
    AccessDenied,
    IdempotencyConflict,
    ResourceNotFound,
    ServiceError,
)
from domsignal.services.membership import MembershipService


class TicketConflict(ServiceError):
    status = 409
    code = "ticket_conflict"
    title = "Ticket version or transition conflict"


class TicketService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    async def ensure(
        self,
        session: AsyncSession,
        *,
        context: OperationContext,
        incident_id: UUID,
    ) -> Ticket | None:
        """Caller owns transaction. Requires an already accepted Report, never a GET side effect."""
        # Diagnostic replay is not a production intake or an instruction to an organization.
        if context.source == "max_replay":
            return None
        fresh = await self.memberships.require_house(
            session,
            user_id=context.actor_user_id,
            house_id=context.house_id,
            source=context.source,
            for_write=True,
        )
        if fresh.management_id != context.management_id:
            raise ResourceNotFound("Resource was not found")
        self.memberships.require_permission(fresh, "report.create")
        repo = TicketRepository(session)
        await repo.lock_incident(incident_id)
        incident = await session.scalar(
            select(Incident).where(
                Incident.id == incident_id,
                Incident.house_id == context.house_id,
                Incident.management_id == context.management_id.value,
            )
        )
        if incident is None or not await session.scalar(
            select(Report.id)
            .where(
                Report.incident_id == incident_id,
                Report.author_id == context.actor_user_id,
                Report.house_id == context.house_id,
            )
            .limit(1)
        ):
            raise ResourceNotFound("Resource was not found")
        management = await session.get(HouseManagement, context.management_id.value)
        if management is None or not management.ticket_intake_enabled:
            return None
        existing = await repo.latest(incident_id)
        if existing is not None:
            return existing  # Including closed/cancelled: no invented next episode.
        candidates = list(await session.scalars(repo.employees(fresh, responsible_only=True)))
        unknown = incident.category == "other"
        assignee_id = candidates[0].id if len(candidates) == 1 and not unknown else None
        reason = (
            "responsibility_unknown"
            if unknown
            else "single_responsible"
            if assignee_id
            else "multiple_responsibles"
            if candidates
            else "no_responsible"
        )
        ticket = Ticket(
            id=uuid4(),
            incident_id=incident.id,
            management_id=incident.management_id,
            house_id=incident.house_id,
            status="needs_clarification" if unknown else "new",
            assignee_id=assignee_id,
            version=1,
            routing_reason=reason,
            source=context.source,
            created_by=context.actor_user_id,
            resume_status="new",
        )
        session.add(ticket)
        await session.flush()
        await self._event(
            session,
            context,
            ticket,
            TicketEventKind.CREATED,
            from_status=None,
            reason=reason,
            visibility="resident",
        )
        return ticket

    async def _context(
        self,
        session: AsyncSession,
        actor_id: UUID,
        ticket_id: UUID,
        *,
        write: bool = False,
        permission: str = "ticket.read",
    ) -> tuple[Ticket, OperationContext]:
        # Routing metadata only before scope resolution; private content is read below.
        route = (
            await session.execute(
                select(Ticket.house_id, Ticket.incident_id).where(Ticket.id == ticket_id)
            )
        ).first()
        if route is None:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(
            session,
            user_id=actor_id,
            house_id=route.house_id,
            for_write=write,
        )
        repo = TicketRepository(session)
        if write:
            await repo.lock_incident(route.incident_id)
            # A request may have waited behind another transaction; resolve permissions again.
            context = await self.memberships.require_house(
                session,
                user_id=actor_id,
                house_id=route.house_id,
            )
        ticket = await repo.ticket(ticket_id, context)
        if ticket is None:
            raise ResourceNotFound("Resource was not found")
        self.memberships.require_permission(context, permission)
        return ticket, context

    async def _attempt_ticket(self, session: AsyncSession, attempt_id: UUID) -> UUID:
        ticket_id = await session.scalar(
            select(WorkAttempt.ticket_id).where(WorkAttempt.id == attempt_id)
        )
        if ticket_id is None:
            raise ResourceNotFound("Resource was not found")
        return ticket_id

    async def detail(self, session: AsyncSession, *, actor_id: UUID, ticket_id: UUID) -> TicketView:
        ticket, context = await self._context(session, actor_id, ticket_id)
        return await self._view(session, ticket, context)

    async def list_for_house(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        limit: int,
        offset: int,
        status: str | None = None,
        assignee_id: UUID | None = None,
        unassigned: bool = False,
    ) -> TicketList:
        context = await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        self.memberships.require_permission(context, "ticket.read")
        query = select(Ticket).where(
            Ticket.house_id == house_id, Ticket.management_id == context.management_id.value
        )
        if status:
            query = query.where(Ticket.status == status)
        if assignee_id:
            query = query.where(Ticket.assignee_id == assignee_id)
        if unassigned:
            query = query.where(Ticket.assignee_id.is_(None))
        items, total = await TicketRepository(session).page(
            query.order_by(Ticket.number.desc()),
            limit=limit,
            offset=offset,
        )
        return TicketList(
            items=[await self._view(session, t, context) for t in items],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    async def assignees(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        ticket_id: UUID,
        limit: int,
        offset: int,
    ) -> AssigneeList:
        _, context = await self._context(session, actor_id, ticket_id, permission="ticket.manage")
        repo = TicketRepository(session)
        users, total = await repo.page(repo.employees(context), limit=limit, offset=offset)
        return AssigneeList(
            items=[AssigneeView(user_id=u.id, display_name=u.display_name) for u in users],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    def _may_command(
        self,
        ticket: Ticket,
        context: OperationContext,
        action: TicketAction,
        *,
        available: bool,
    ) -> bool:
        manager = "ticket.manage" in context.permissions
        owner = (
            available
            and ticket.assignee_id == context.actor_user_id
            and ticket.accepted_by == context.actor_user_id
        )
        match action:
            case TicketAction.ASSIGN | TicketAction.CANCEL | TicketAction.DEADLINE:
                return manager
            case TicketAction.ACCEPT:
                return "ticket.work" in context.permissions and ticket.assignee_id in {
                    None,
                    context.actor_user_id,
                }
            case TicketAction.START:
                return owner
            case TicketAction.CLARIFY | TicketAction.WAIT_EXTERNAL | TicketAction.RESUME:
                return owner or manager
            case TicketAction.WORK_REPORT:
                return (owner or manager) and available and ticket.accepted_by is not None

    async def command(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        ticket_id: UUID,
        action: TicketAction,
        payload: TicketCommand,
        idempotency_key: str,
    ) -> TicketMutation:
        async with session.begin():
            ticket, context = await self._context(session, actor_id, ticket_id, write=True)
            repo = TicketRepository(session)
            available = await repo.available(context, ticket.assignee_id)
            if not self._may_command(ticket, context, action, available=available):
                raise AccessDenied("This ticket action is not permitted for the current actor")
            operation = f"ticket:{ticket_id}:{action.value}"
            receipt, digest = await self._receipt(
                session,
                context,
                operation,
                idempotency_key,
                payload.model_dump(mode="json"),
            )
            if receipt is not None:
                return TicketMutation(
                    ticket=await self._view(session, ticket, context),
                    replayed=True,
                    event_id=receipt["event_id"],
                    effect_version=receipt["effect_version"],
                    attempt_id=receipt.get("attempt_id"),
                )
            if ticket.version != payload.expected_version:
                raise TicketConflict("Ticket changed; read its current version and retry")
            if not transition_allowed(
                action, ticket.status, accepted=ticket.accepted_by is not None
            ):
                raise TicketConflict("This transition is not allowed in the current state")
            previous = ticket.status
            reason = payload.reason if isinstance(payload, ReasonCommand) else None
            attempt_id = None
            match action:
                case TicketAction.ASSIGN:
                    assert isinstance(payload, AssignCommand)
                    if payload.assignee_id is not None and not await repo.available(
                        context, payload.assignee_id
                    ):
                        raise AccessDenied("Assignee has no current permission on this management")
                    if ticket.assignee_id == payload.assignee_id:
                        raise TicketConflict("This assignee is already selected")
                    ticket.assignee_id = payload.assignee_id
                    ticket.accepted_by = None
                    ticket.accepted_at = None
                    ticket.resume_status = "new"
                    if ticket.status in {"accepted", "in_progress"}:
                        ticket.status = "new"
                    kind = TicketEventKind.ASSIGNED
                case TicketAction.ACCEPT:
                    ticket.assignee_id = actor_id
                    ticket.accepted_by = actor_id
                    ticket.accepted_at = datetime.now(UTC)
                    if ticket.status == "new":
                        ticket.status = "accepted"
                    kind = TicketEventKind.ACCEPTED
                case TicketAction.START:
                    ticket.status = "in_progress"
                    kind = TicketEventKind.STARTED
                case TicketAction.CLARIFY | TicketAction.WAIT_EXTERNAL:
                    ticket.resume_status = ticket.status
                    ticket.status = (
                        "needs_clarification"
                        if action == TicketAction.CLARIFY
                        else "waiting_external"
                    )
                    kind = (
                        TicketEventKind.CLARIFICATION_REQUESTED
                        if action == TicketAction.CLARIFY
                        else TicketEventKind.EXTERNAL_WAIT_RECORDED
                    )
                case TicketAction.RESUME:
                    ticket.status = (
                        ticket.resume_status if available and ticket.accepted_by else "new"
                    )
                    kind = TicketEventKind.RESUMED
                case TicketAction.WORK_REPORT:
                    assert isinstance(payload, WorkAttemptCreate)
                    latest = await repo.latest_attempt(ticket)
                    attempt = WorkAttempt(
                        id=uuid4(),
                        ticket_id=ticket.id,
                        number=latest.number + 1 if latest else 1,
                        reported_by=actor_id,
                        performed_by=ticket.assignee_id,
                        public_description=payload.public_description,
                        rework_required=False,
                    )
                    session.add(attempt)
                    await session.flush()
                    attempt_id = attempt.id
                    ticket.latest_attempt_id = attempt.id
                    ticket.status = "verification_pending"
                    kind = TicketEventKind.WORK_REPORTED
                case TicketAction.CANCEL:
                    ticket.status = "cancelled"
                    kind = TicketEventKind.CANCELLED
                case TicketAction.DEADLINE:
                    kind = TicketEventKind.DEADLINE_RECORDED
            repo.changed(ticket)
            event = await self._event(
                session,
                context,
                ticket,
                kind,
                from_status=previous,
                reason=reason,
                attempt_id=attempt_id,
                visibility="resident" if action == TicketAction.WORK_REPORT else "internal",
            )
            if action == TicketAction.DEADLINE:
                assert isinstance(payload, DeadlineCreate)
                await self._deadline(session, ticket, context, payload, event)
            effect = dict(
                event_id=str(event.id),
                effect_version=ticket.version,
                attempt_id=str(attempt_id) if attempt_id else None,
            )
            self._save_receipt(session, context, operation, idempotency_key, digest, effect)
            await session.flush()
            return TicketMutation(ticket=await self._view(session, ticket, context), **effect)

    async def observe(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        attempt_id: UUID,
        payload: ObservationCreate,
        idempotency_key: str,
    ) -> ObservationRecorded:
        async with session.begin():
            ticket_id = await self._attempt_ticket(session, attempt_id)
            ticket, context = await self._context(
                session,
                actor_id,
                ticket_id,
                write=True,
                permission="work.observe",
            )
            repo = TicketRepository(session)
            attempt = await session.get(WorkAttempt, attempt_id)
            assert attempt is not None
            await self._require_observer(repo, ticket, attempt, context)
            operation = f"observe:{attempt_id}"
            receipt, digest = await self._receipt(
                session,
                context,
                operation,
                idempotency_key,
                payload.model_dump(mode="json"),
            )
            if receipt is not None:
                observation = await session.get(ResultObservation, UUID(receipt["observation_id"]))
                assert observation is not None
                return ObservationRecorded(
                    observation=OwnObservation.model_validate(observation),
                    target_attempt_id=attempt_id,
                    applied_to_current=receipt["applied_to_current"],
                    state_changed=receipt["state_changed"],
                    effect_version=receipt["effect_version"],
                    replayed=True,
                    current=await self._resident_view(
                        session, await repo.latest(ticket.incident_id) or ticket, context
                    ),
                )
            current = await repo.current_observations(attempt_id)
            own = next((o for o in current if o.actor_id == actor_id), None)
            if payload.corrects_id and (own is None or own.id != payload.corrects_id):
                raise TicketConflict("Correction must reference the actor's latest response")
            latest_revision = await session.scalar(
                select(func.max(ResultObservation.revision)).where(
                    ResultObservation.attempt_id == attempt_id
                )
            )
            observation = ResultObservation(
                id=uuid4(),
                attempt_id=attempt_id,
                actor_id=actor_id,
                outcome=payload.outcome,
                comment=payload.comment,
                revision=(latest_revision or 0) + 1,
                corrects_id=own.id if own else None,
            )
            session.add(observation)
            await session.flush()
            newest = await repo.latest(ticket.incident_id)
            applied = (
                ticket.latest_attempt_id == attempt_id
                and ticket.status != "cancelled"
                and newest is not None
                and newest.id == ticket.id
            )
            previous = ticket.status
            kind = TicketEventKind.OBSERVATION_RECORDED
            if applied:
                current = [o for o in current if o.actor_id != actor_id] + [observation]
                negative = any(o.outcome == "unresolved" for o in current)
                positive = any(o.outcome == "resolved" for o in current)
                if negative:
                    attempt.rework_required = True
                ticket.status = observation_status(
                    ticket.status,
                    resolved=positive,
                    unresolved=negative,
                    rework_required=attempt.rework_required,
                )
                if payload.outcome == "unresolved":
                    kind = TicketEventKind.RESULT_OBJECTED
                elif ticket.status == "closed" and previous != "closed":
                    kind = TicketEventKind.RESULT_CONFIRMED
                if ticket.status == "in_progress" and not await repo.available(
                    context, ticket.assignee_id
                ):
                    # Retain assignee as history/queue signal; revoked identity gets no writes.
                    ticket.accepted_by = None
                    ticket.accepted_at = None
            repo.changed(ticket)
            await self._event(
                session,
                context,
                ticket,
                kind,
                from_status=previous,
                attempt_id=attempt_id,
                observation_id=observation.id,
                visibility="resident",
            )
            effect = dict(
                observation_id=str(observation.id),
                applied_to_current=applied,
                state_changed=previous != ticket.status,
                effect_version=ticket.version,
            )
            self._save_receipt(session, context, operation, idempotency_key, digest, effect)
            await session.flush()
            return ObservationRecorded(
                observation=OwnObservation.model_validate(observation),
                target_attempt_id=attempt_id,
                applied_to_current=applied,
                state_changed=previous != ticket.status,
                effect_version=ticket.version,
                current=await self._resident_view(session, newest or ticket, context),
            )

    async def _require_observer(
        self,
        repo: TicketRepository,
        ticket: Ticket,
        attempt: WorkAttempt,
        context: OperationContext,
    ) -> None:
        self.memberships.require_permission(context, "work.observe")
        if not context.resident_access or not await repo.participant(ticket, context.actor_user_id):
            raise AccessDenied("A current resident basis and an own Report are required")
        # Canonical authenticated User identity, never a caller-selected role.
        if context.actor_user_id in {attempt.reported_by, attempt.performed_by}:
            raise AccessDenied("An actor cannot verify their own work attempt")

    async def work_status(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        incident_id: UUID,
    ) -> ResidentWorkStatus:
        house_id = await session.scalar(select(Incident.house_id).where(Incident.id == incident_id))
        if house_id is None:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(session, user_id=actor_id, house_id=house_id)
        if not await session.scalar(
            select(Incident.id).where(
                Incident.id == incident_id,
                Incident.management_id == context.management_id.value,
            )
        ):
            raise ResourceNotFound("Resource was not found")
        self.memberships.require_permission(context, "work.read")
        ticket = await TicketRepository(session).latest(incident_id)
        if ticket is None:
            return ResidentWorkStatus(
                incident_id=incident_id,
                ticket_id=None,
                internal_number=None,
                status=None,
                version=None,
                created_at=None,
                updated_at=None,
                latest_attempt=None,
                observation_conflict=False,
                my_latest_observation=None,
                deadlines=[],
                allowed_actions=[],
            )
        return await self._resident_view(session, ticket, context)

    async def _resident_view(
        self,
        session: AsyncSession,
        ticket: Ticket,
        context: OperationContext,
    ) -> ResidentWorkStatus:
        repo = TicketRepository(session)
        attempt = await repo.latest_attempt(ticket)
        observations = await repo.current_observations(attempt.id) if attempt else []
        own = next((o for o in observations if o.actor_id == context.actor_user_id), None)
        can_observe = False
        if attempt:
            try:
                await self._require_observer(repo, ticket, attempt, context)
                can_observe = True
            except AccessDenied:
                pass
        # Every field is explicitly public. No staff DTO, event reasons or other comments here.
        return ResidentWorkStatus(
            incident_id=ticket.incident_id,
            ticket_id=ticket.id,
            internal_number=f"T-{ticket.number}",
            status=ticket.status,
            version=ticket.version,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            latest_attempt=AttemptPublic.model_validate(attempt) if attempt else None,
            observation_conflict=len({o.outcome for o in observations}) > 1,
            my_latest_observation=OwnObservation.model_validate(own) if own else None,
            deadlines=[self._deadline_public(d) for d in await repo.deadlines(ticket.id)],
            allowed_actions=["observe_result"] if can_observe else [],
        )

    async def _view(
        self,
        session: AsyncSession,
        ticket: Ticket,
        context: OperationContext,
    ) -> TicketView:
        repo = TicketRepository(session)
        available = await repo.available(context, ticket.assignee_id)
        attempt = await repo.latest_attempt(ticket)
        observations = await repo.current_observations(attempt.id) if attempt else []
        return TicketView(
            id=ticket.id,
            internal_number=f"T-{ticket.number}",
            incident_id=ticket.incident_id,
            house_id=ticket.house_id,
            management_id=ticket.management_id,
            status=ticket.status,
            version=ticket.version,
            assignee_id=ticket.assignee_id,
            assignee_name=await session.scalar(
                select(User.display_name).where(User.id == ticket.assignee_id)
            )
            if ticket.assignee_id
            else None,
            accepted_by=ticket.accepted_by,
            accepted_at=ticket.accepted_at,
            requires_reassignment=not available,
            routing_reason=ticket.routing_reason,
            source=ticket.source,
            created_by=ticket.created_by,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            latest_attempt=await self._attempt_view(session, attempt) if attempt else None,
            observation_conflict=len({o.outcome for o in observations}) > 1,
            deadlines=[self._deadline_view(d) for d in await repo.deadlines(ticket.id)],
            allowed_actions=[
                a
                for a in TicketAction
                if transition_allowed(
                    a,
                    ticket.status,
                    accepted=ticket.accepted_by is not None,
                )
                and self._may_command(ticket, context, a, available=available)
            ],
        )

    async def history(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        ticket_id: UUID,
        kind: Literal["events", "attempts", "deadlines"],
        limit: int,
        offset: int,
    ) -> EventList | AttemptList | DeadlineList:
        await self._context(session, actor_id, ticket_id)
        repo = TicketRepository(session)
        if kind == "events":
            events, total = await repo.page(
                select(TicketEvent)
                .where(TicketEvent.ticket_id == ticket_id)
                .order_by(TicketEvent.version.desc()),
                limit=limit,
                offset=offset,
            )
            return EventList(
                items=[EventView.model_validate(e) for e in events],
                page=PageMeta(limit=limit, offset=offset, total=total),
            )
        if kind == "attempts":
            attempts, total = await repo.page(
                select(WorkAttempt)
                .where(WorkAttempt.ticket_id == ticket_id)
                .order_by(WorkAttempt.number.desc()),
                limit=limit,
                offset=offset,
            )
            return AttemptList(
                items=[await self._attempt_view(session, a) for a in attempts],
                page=PageMeta(limit=limit, offset=offset, total=total),
            )
        deadlines, total = await repo.page(
            select(TicketDeadline)
            .where(TicketDeadline.ticket_id == ticket_id)
            .order_by(TicketDeadline.created_at.desc(), TicketDeadline.id),
            limit=limit,
            offset=offset,
        )
        return DeadlineList(
            items=[self._deadline_view(d) for d in deadlines],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    async def _attempt_view(self, session: AsyncSession, attempt: WorkAttempt) -> AttemptView:
        # Internal read projection only; resident AttemptPublic remains an explicit allowlist.
        current = await TicketRepository(session).current_observations(attempt.id)
        return AttemptView(
            **AttemptView.model_validate(attempt).model_dump(
                exclude={"performer_name", "resolved_count", "unresolved_count"}
            ),
            performer_name=await session.scalar(
                select(User.display_name).where(User.id == attempt.performed_by)
            ),
            resolved_count=sum(o.outcome == "resolved" for o in current),
            unresolved_count=sum(o.outcome == "unresolved" for o in current),
        )

    async def observations(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        attempt_id: UUID,
        own: bool,
        limit: int,
        offset: int,
    ) -> ObservationList | OwnObservationList:
        ticket_id = await self._attempt_ticket(session, attempt_id)
        await self._context(
            session, actor_id, ticket_id, permission="work.read" if own else "ticket.read"
        )
        query = select(ResultObservation).where(ResultObservation.attempt_id == attempt_id)
        if own:
            query = query.where(ResultObservation.actor_id == actor_id)
        items, total = await TicketRepository(session).page(
            query.order_by(ResultObservation.revision.desc()),
            limit=limit,
            offset=offset,
        )
        page = PageMeta(limit=limit, offset=offset, total=total)
        if own:
            return OwnObservationList(
                items=[OwnObservation.model_validate(o) for o in items], page=page
            )
        return ObservationList(items=[ObservationView.model_validate(o) for o in items], page=page)

    async def _event(
        self,
        session: AsyncSession,
        context: OperationContext,
        ticket: Ticket,
        kind: TicketEventKind,
        *,
        from_status: str | None,
        reason: str | None = None,
        attempt_id: UUID | None = None,
        observation_id: UUID | None = None,
        visibility: Literal["internal", "resident"] = "internal",
    ) -> TicketEvent:
        event = TicketEvent(
            id=uuid4(),
            ticket_id=ticket.id,
            actor_id=context.actor_user_id,
            kind=kind.value,
            version=ticket.version,
            from_status=from_status,
            to_status=ticket.status,
            reason=reason,
            attempt_id=attempt_id,
            observation_id=observation_id,
            assignee_id=ticket.assignee_id,
            visibility=visibility,
        )
        session.add(event)
        await session.flush()
        assert context.tenant_id.value is not None
        intent = TicketNotificationIntent(
            event_id=event.id,
            event_kind=kind,
            ticket_id=ticket.id,
            incident_id=ticket.incident_id,
            attempt_id=attempt_id,
            house_id=ticket.house_id,
            management_id=ticket.management_id,
            tenant_id=context.tenant_id.value,
            ticket_version=ticket.version,
            audience="participants" if visibility == "resident" else "staff",
            chat_binding_id=context.chat_binding_id.value,
            binding_version=context.binding_version.value,
        )
        ReliabilityRepository(session).add_outbox(
            kind="ticket.notification_intent.v1",
            aggregate_id=ticket.id,
            payload=intent.model_dump(mode="json"),
            dedupe_key=f"ticket-event:{event.id}",
        )
        return event

    async def _receipt(
        self,
        session: AsyncSession,
        context: OperationContext,
        operation: str,
        key: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        digest = stable_hash(
            {
                "body": body,
                "management_id": str(context.management_id.value),
                "house_id": str(context.house_id),
            }
        )
        record = await ReliabilityRepository(session).idempotency_record(
            actor_id=context.actor_user_id,
            action=operation,
            key=key,
        )
        if record and record.request_hash != digest:
            raise IdempotencyConflict("Idempotency-Key was already used with a different body")
        return (record.response_body if record else None), digest

    @staticmethod
    def _save_receipt(
        session: AsyncSession,
        context: OperationContext,
        operation: str,
        key: str,
        digest: str,
        effect: dict[str, Any],
    ) -> None:
        ReliabilityRepository(session).add_idempotency(
            actor_id=context.actor_user_id,
            action=operation,
            key=key,
            request_hash=digest,
            response_status=200,
            response_body=effect,
        )

    async def _deadline(
        self,
        session: AsyncSession,
        ticket: Ticket,
        context: OperationContext,
        payload: DeadlineCreate,
        event: TicketEvent,
    ) -> None:
        anchor = await session.scalar(
            select(TicketEvent).where(
                TicketEvent.id == payload.start_event_id,
                TicketEvent.ticket_id == ticket.id,
            )
        )
        if anchor is None:
            raise ResourceNotFound("Resource was not found")
        if payload.due_at is not None and payload.due_at < anchor.created_at:
            raise TicketConflict("Deadline cannot precede its start event")
        if payload.agreed_at is not None and payload.agreed_at > datetime.now(UTC):
            raise TicketConflict("Agreement cannot be recorded in the future")
        revision = await session.scalar(
            select(func.max(TicketDeadline.revision)).where(
                TicketDeadline.ticket_id == ticket.id,
                TicketDeadline.kind == payload.kind,
                TicketDeadline.basis == payload.basis,
            )
        )
        session.add(
            TicketDeadline(
                ticket_id=ticket.id,
                kind=payload.kind,
                basis=payload.basis,
                revision=(revision or 0) + 1,
                start_event_id=anchor.id,
                started_at=anchor.created_at,
                due_at=payload.due_at,
                agreement_reference=payload.agreement_reference,
                agreed_at=payload.agreed_at,
                recorded_by=context.actor_user_id,
                reason=payload.reason,
                event_id=event.id,
            )
        )

    @staticmethod
    def _deadline_public(deadline: TicketDeadline) -> DeadlinePublic:
        return DeadlinePublic(
            kind=deadline.kind,
            basis=deadline.basis,
            revision=deadline.revision,
            start_event_id=deadline.start_event_id,
            started_at=deadline.started_at,
            due_at=deadline.due_at,
            rule_source=deadline.rule_source,
            rule_version=deadline.rule_version,
            agreement_recorded=deadline.agreement_reference is not None,
        )

    @classmethod
    def _deadline_view(cls, deadline: TicketDeadline) -> DeadlineView:
        return DeadlineView(
            **cls._deadline_public(deadline).model_dump(),
            id=deadline.id,
            event_id=deadline.event_id,
            agreement_reference=deadline.agreement_reference,
            agreed_at=deadline.agreed_at,
            recorded_by=deadline.recorded_by,
            reason=deadline.reason,
            created_at=deadline.created_at,
        )
