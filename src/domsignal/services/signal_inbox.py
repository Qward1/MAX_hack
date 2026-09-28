"""Очередь сигналов оператора (P5): что требует решения и одно решение на сигнал.

Сигнал никогда не становится заявкой сам: заявку создаёт оператор. Каждое
решение — создать заявку, присоединить к проблеме, отметить внешний маршрут,
выбрать маршрут вручную или закрыть с причиной — записывается с автором,
временем и причиной, проходит `Idempotency-Key` и `expected_version`.

Права — существующей политики доступа: чтение как у очереди заявок
(`ticket.read`), решения как у создания и приёма заявки (`ticket.work`).
Чужой дом скрывается тем же `404`, что и у заявок; Audit Pool оператору не
отдаётся ни списком, ни по идентификатору.

Порядок блокировок решения: A-15 (authority → дом) → `signals:<дом>` →
строка сигнала → (Incident и Ticket внутри создания заявки). Движок сигналов
берёт `signals:<дом>` без блокировок полномочий, поэтому цикла нет.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast, get_args
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.ai import load_taxonomy
from domsignal.contracts.common import PageMeta
from domsignal.contracts.incidents import DuplicateCandidate, ReportCreate
from domsignal.contracts.routing import (
    DANGER_KINDS,
    LOCATION_SCOPES,
    ActionCard,
    DangerKind,
    LocationScope,
    ResponsibilityRoute,
    RouteType,
)
from domsignal.contracts.signals import (
    DangerEvidenceView,
    DangerSource,
    DismissReason,
    SignalActionCode,
    SignalActionDescriptor,
    SignalAttention,
    SignalChooseRoute,
    SignalCommand,
    SignalCreateTicket,
    SignalDanger,
    SignalDecisionView,
    SignalDismiss,
    SignalEventView,
    SignalEvidenceValue,
    SignalJoin,
    SignalLinked,
    SignalList,
    SignalMutation,
    SignalPlace,
    SignalQuoteView,
    SignalRouteExternal,
    SignalRouteSnapshot,
    SignalStatus,
    SignalStrength,
    SignalStrengthCounts,
    SignalSummary,
    SignalTerritory,
    SignalTicketDraft,
    SignalView,
)
from domsignal.core.incidents import (
    CATEGORY_TITLES,
    ClassificationMode,
    IncidentStatus,
    ReportCategory,
)
from domsignal.core.routing import UNSPECIFIED_SUBTYPE, HouseRoutingContext
from domsignal.core.signals import DANGER_LABELS, author_label
from domsignal.db.models import (
    ChatBinding,
    HouseManagement,
    Incident,
    RouteOutcome,
    Signal,
    SignalEvent,
    Ticket,
)
from domsignal.db.models.passive import OPEN_SIGNAL_STATUSES
from domsignal.db.repositories.incidents import OPEN_STATUSES as OPEN_INCIDENT_STATUSES
from domsignal.db.repositories.incidents import IncidentRepository
from domsignal.db.repositories.passive import PassiveRepository
from domsignal.db.repositories.reliability import ReliabilityRepository, stable_hash
from domsignal.db.repositories.signals import SignalInboxRepository, SignalScope
from domsignal.services.action_cards import ActionCardBuilder
from domsignal.services.context import OperationContext
from domsignal.services.errors import (
    FieldValidationError,
    IdempotencyConflict,
    ResourceNotFound,
    ServiceError,
)
from domsignal.services.membership import MembershipService
from domsignal.services.reports import IncidentClosed, ReportService
from domsignal.services.routing import RoutingService
from domsignal.services.signal_texts import (
    DANGER_TITLE,
    DISMISS_REASON_LABELS,
    EVENT_LABELS,
    RELATED_CONVERSION_REASON,
    TERRITORY_LABELS,
    quoted_value,
    strength_reason_text,
    subtype_title,
    ticket_description,
)
from domsignal.services.ticket_chat import enqueue_ticket_post

#: Право чтения очереди — то же, что у очереди заявок.
READ_PERMISSION = "ticket.read"
#: Право решения — то же, что у создания и приёма заявки.
DECIDE_PERMISSION = "ticket.work"

#: Маршруты вне УК: по ним оператор может отметить внешний маршрут.
EXTERNAL_ROUTES = frozenset(
    {
        "municipality",
        "resource_supplier",
        "regional_operator",
        "other_authority",
        "emergency_service",
    }
)
#: Все типы маршрута, кроме «не определён»: выбор при `unknown`.
CHOOSABLE_ROUTES: tuple[RouteType, ...] = tuple(
    item for item in get_args(RouteType) if item != "unknown"
)

#: Кандидаты в присоединение — то же детерминированное правило, что у жителя.
MAX_JOIN_CANDIDATES = 3
JOIN_WINDOW_DAYS = 14
SAME_CATEGORY_REASON = "Та же категория, проблема открыта"
SAME_ENTRANCE_REASON = "Тот же подъезд, проблема открыта"

#: Действия карточки маршрута → команды оператора. Порядок кнопок — карточки.
_CARD_TO_COMMAND: dict[str, SignalActionCode] = {
    "create_ticket": "create-ticket",
    "join_existing": "join",
    "route_external": "route-external",
    "operator_review": "choose-route",
    "not_a_problem": "dismiss",
}
_COMMAND_ORDER: tuple[SignalActionCode, ...] = (
    "choose-route",
    "create-ticket",
    "join",
    "route-external",
    "dismiss",
)

_NO_INTAKE_REASON = "Приём заявок для этого дома выключен у управляющей компании."
_NO_CANDIDATES_REASON = "Открытых проблем той же категории за 14 суток в доме нет."
_CHOOSE_FIRST_REASON = "Сначала выберите маршрут: роутер не определил его по справочнику."
_NO_PERMISSION_REASON = "Решения по сигналам недоступны в вашей роли."


class StaleSignalVersion(ServiceError):
    status = 409
    code = "stale_version"
    title = "Данные изменились"


class SignalAlreadyDecided(ServiceError):
    status = 409
    code = "signal_decided"
    title = "Решение по сигналу уже принято"


class SignalActionUnavailable(ServiceError):
    status = 409
    code = "signal_action_unavailable"
    title = "Действие сейчас недоступно"


@dataclass(frozen=True)
class _Resolved:
    """Всё, что нужно карточке сигнала, собранное в одной транзакции."""

    route: ResponsibilityRoute
    router_route: ResponsibilityRoute
    outcome: RouteOutcome | None
    house: HouseRoutingContext
    danger: tuple[DangerKind, ...]


def _scope_value(value: str) -> LocationScope:
    for scope in LOCATION_SCOPES:
        if scope == value:
            return scope
    return "unknown"


def _danger(signal: Signal) -> tuple[DangerKind, ...]:
    """Виды опасности для маршрута и памятки — только у критического сигнала."""
    emergency = signal.emergency or {}
    if signal.strength != "critical" or not emergency.get("is_emergency"):
        return ()
    kinds = emergency.get("kinds") or []
    return tuple(kind for kind in DANGER_KINDS if kind in kinds)


def _category(value: str) -> ReportCategory:
    try:
        return ReportCategory(value)
    except ValueError:
        return ReportCategory.OTHER


def _strength(value: str) -> SignalStrength:
    return cast(SignalStrength, value if value in ("critical", "strong", "medium") else "weak")


def own_value(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Место или время сигнала — только с цитатой из его собственной реплики.

    Цитата из реплики контекста (предыдущий разговор чата) у значения есть, но
    строки окна у неё нет: такое значение оператору и в заявку не отдаётся.
    """
    if not raw or not raw.get("line_mid"):
        return None
    return raw


def _place(signal: Signal) -> SignalPlace:
    def value(raw: dict[str, Any] | None) -> SignalEvidenceValue | None:
        found = quoted_value(own_value(raw))
        return SignalEvidenceValue(value=found[0], quote=found[1]) if found else None

    return SignalPlace(
        entrance=value(signal.entrance), floor=value(signal.floor), since=value(signal.since)
    )


def _subtype_label(code: str) -> str:
    taxonomy = load_taxonomy()
    try:
        return subtype_title(taxonomy.get(code).label)
    except KeyError:
        return subtype_title(taxonomy.get("other.unspecified").label)


def _signal_title(signal: Signal) -> str:
    """Подпись сигнала: подтип таксономии, а до разбора — «Признак опасности»."""
    if signal.subtype == UNSPECIFIED_SUBTYPE and (signal.emergency or {}).get("kinds"):
        return DANGER_TITLE
    return _subtype_label(signal.subtype)


def _quote_view(author_ref: str, sent_at: datetime, text: str) -> SignalQuoteView:
    return SignalQuoteView(author=author_label(author_ref), sent_at=sent_at, text=text)


def route_choices(router_route: ResponsibilityRoute) -> list[RouteType]:
    """Что оператор может выбрать, когда роутер не решил сам."""
    if router_route.requires_operator_choice and router_route.alternatives:
        return list(dict.fromkeys(item.route_type for item in router_route.alternatives))
    if router_route.route_type == "unknown":
        return list(CHOOSABLE_ROUTES)
    return []


class SignalInboxService:
    """Список, деталь и решения оператора. Бизнес-логика одна для API и бота."""

    def __init__(
        self,
        *,
        routing: RoutingService,
        action_cards: ActionCardBuilder,
        reports: ReportService,
    ) -> None:
        self.routing = routing
        self.action_cards = action_cards
        self.reports = reports
        self.memberships = MembershipService()

    # ------------------------------------------------------------- чтение

    async def queue(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID | None,
        statuses: Sequence[SignalStatus],
        strengths: Sequence[SignalStrength],
        limit: int,
        offset: int,
    ) -> SignalList:
        if house_id is not None:
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=house_id
            )
            self.memberships.require_permission(context, READ_PERMISSION)
            contexts = [context]
        else:
            contexts = [
                context
                for _, context in await self.memberships.contexts_with(
                    session, user_id=actor_id, permission=READ_PERMISSION
                )
            ]
        scopes = [self._scope(context) for context in contexts]
        repo = SignalInboxRepository(session)
        items, total = await repo.page(
            scopes, statuses=statuses, strengths=strengths, limit=limit, offset=offset
        )
        counts = await repo.strength_counts(scopes, statuses=statuses)
        attention = await repo.attention(scopes)
        houses = await repo.houses([item.house_id for item in items])
        quotes = await repo.quotes([item.id for item in items])
        outcomes = await repo.outcomes(
            [item.route_outcome_id for item in items if item.route_outcome_id]
        )
        contexts_by_house: dict[UUID, HouseRoutingContext] = {}
        summaries = []
        for item in items:
            if item.house_id not in contexts_by_house:
                contexts_by_house[item.house_id] = await self.routing.house_context(
                    session, item.house_id
                )
            resolved = self._resolve(
                item,
                contexts_by_house[item.house_id],
                outcomes.get(item.route_outcome_id) if item.route_outcome_id else None,
            )
            house = houses.get(item.house_id)
            summaries.append(
                self._summary(
                    item,
                    resolved,
                    address=house.address if house else "",
                    is_demo=bool(house and house.is_demo),
                    quotes=quotes.get(item.id, []),
                )
            )
        return SignalList(
            items=summaries,
            page=PageMeta(limit=limit, offset=offset, total=total),
            counts=SignalStrengthCounts(
                critical=counts.get("critical", 0),
                strong=counts.get("strong", 0),
                medium=counts.get("medium", 0),
                weak=counts.get("weak", 0),
            ),
            attention=SignalAttention(
                count=attention[0], latest_signal_id=attention[1], latest_at=attention[2]
            ),
        )

    async def detail(self, session: AsyncSession, *, actor_id: UUID, signal_id: UUID) -> SignalView:
        signal, context = await self._context(session, actor_id, signal_id)
        return await self._view(session, signal, context)

    # -------------------------------------------------------------- решения

    async def create_ticket(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        signal_id: UUID,
        payload: SignalCreateTicket,
        idempotency_key: str,
    ) -> SignalMutation:
        async def apply(
            signal: Signal, context: OperationContext, resolved: _Resolved
        ) -> tuple[str, str]:
            if not await self._intake_enabled(session, context):
                raise SignalActionUnavailable(_NO_INTAKE_REASON)
            draft = await self._ticket_draft(session, signal)
            category = payload.category or draft.category
            created = await self.reports.create_in_context(
                session,
                context=context,
                payload=ReportCreate(
                    house_id=signal.house_id,
                    category=category,
                    description=payload.description or draft.description,
                    classification_mode=ClassificationMode.MANUAL,
                ),
                idempotency_key=f"signal:{signal.id}:{idempotency_key}"[:200],
                # D-05: оператор создаёт заявку по маршруту «зона УК» — кто
                # отвечает, уже известно, даже если категория «Другое».
                responsibility_known=resolved.route.route_type == "uk_internal",
            )
            located = {
                "location_entrance": (quoted_value(own_value(signal.entrance)) or (None,))[0],
                "location_floor": (quoted_value(own_value(signal.floor)) or (None,))[0],
                "observed_since": (quoted_value(own_value(signal.since)) or (None,))[0],
            }
            if any(located.values()):
                await session.execute(
                    update(Incident).where(Incident.id == created.incident.id).values(**located)
                )
            signal.report_id = created.report_id
            signal.incident_id = created.incident.id
            self._close(signal, context, status="converted")
            await self._outcome(
                session,
                signal,
                context,
                resolved.route,
                decision="ticket",
                report_id=created.report_id,
            )
            # Оператор создал заявку из сигнала чата: одно сообщение бота о ней
            # в тот же чат (B-06, BOT-VOICE-HUMAN-2026-09-27).
            ticket_id = await session.scalar(
                select(Ticket.id).where(Ticket.incident_id == created.incident.id)
            )
            binding = await session.get(ChatBinding, signal.chat_binding_id)
            if ticket_id is not None and binding is not None and binding.status == "active":
                await enqueue_ticket_post(
                    session,
                    ticket_id=ticket_id,
                    chat_binding_id=binding.id,
                    binding_version=binding.binding_version,
                )
            return "signal_converted", category.value

        return await self._decide(
            session,
            actor_id=actor_id,
            signal_id=signal_id,
            action="create-ticket",
            payload=payload,
            idempotency_key=idempotency_key,
            apply=apply,
        )

    async def join(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        signal_id: UUID,
        payload: SignalJoin,
        idempotency_key: str,
    ) -> SignalMutation:
        async def apply(
            signal: Signal, context: OperationContext, resolved: _Resolved
        ) -> tuple[str, str]:
            repo = IncidentRepository(session)
            incident = await repo.incident(payload.incident_id, context=context)
            if incident is None:
                raise FieldValidationError(
                    "Проблема не найдена среди проблем этого дома", field="incident_id"
                )
            if incident.status not in OPEN_INCIDENT_STATUSES:
                raise IncidentClosed("Эта проблема уже закрыта, присоединиться нельзя")
            draft = await self._ticket_draft(session, signal)
            report = await repo.create_report(
                incident_id=incident.id,
                house_id=context.house_id,
                author_id=context.actor_user_id,
                category=incident.category,
                # Сигнал добавляет к проблеме слова жителей из чата, а не
                # повторяет её описание. Второго Ticket не появляется.
                description=draft.description,
                classification_mode=ClassificationMode.MANUAL.value,
                provenance=context.source,
            )
            signal.report_id = report.id
            signal.incident_id = incident.id
            self._close(signal, context, status="converted")
            await self._outcome(
                session,
                signal,
                context,
                resolved.route,
                decision="ticket",
                report_id=report.id,
            )
            return "signal_joined", str(incident.id)

        return await self._decide(
            session,
            actor_id=actor_id,
            signal_id=signal_id,
            action="join",
            payload=payload,
            idempotency_key=idempotency_key,
            apply=apply,
        )

    async def route_external(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        signal_id: UUID,
        payload: SignalRouteExternal,
        idempotency_key: str,
    ) -> SignalMutation:
        async def apply(
            signal: Signal, context: OperationContext, resolved: _Resolved
        ) -> tuple[str, str]:
            if resolved.route.route_type not in EXTERNAL_ROUTES:
                raise SignalActionUnavailable(
                    "Маршрут сигнала не внешний: отметить внешний маршрут нельзя"
                )
            self._close(signal, context, status="routed_external")
            await self._outcome(session, signal, context, resolved.route, decision="external")
            return "signal_routed_external", resolved.route.route_type

        return await self._decide(
            session,
            actor_id=actor_id,
            signal_id=signal_id,
            action="route-external",
            payload=payload,
            idempotency_key=idempotency_key,
            apply=apply,
        )

    async def choose_route(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        signal_id: UUID,
        payload: SignalChooseRoute,
        idempotency_key: str,
    ) -> SignalMutation:
        async def apply(
            signal: Signal, context: OperationContext, resolved: _Resolved
        ) -> tuple[str, str]:
            choices = route_choices(resolved.router_route)
            if not choices:
                raise SignalActionUnavailable(
                    "Маршрут определён справочником: выбирать его вручную не нужно"
                )
            if payload.route_type not in choices:
                raise FieldValidationError(
                    "Этот тип маршрута нельзя выбрать для сигнала", field="route_type"
                )
            route = self.routing.route_of_type(
                payload.route_type,
                subtype=signal.subtype,
                location_scope=_scope_value(signal.location_scope),
                house=resolved.house,
                danger_kinds=resolved.danger,
            )
            await self._outcome(
                session,
                signal,
                context,
                route,
                decision=(
                    "external" if route.route_type in EXTERNAL_ROUTES else "needs_clarification"
                ),
            )
            signal.status = "in_review"
            return "signal_route_chosen", route.route_type

        return await self._decide(
            session,
            actor_id=actor_id,
            signal_id=signal_id,
            action="choose-route",
            payload=payload,
            idempotency_key=idempotency_key,
            apply=apply,
        )

    async def dismiss(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        signal_id: UUID,
        payload: SignalDismiss,
        idempotency_key: str,
    ) -> SignalMutation:
        async def apply(
            signal: Signal, context: OperationContext, resolved: _Resolved
        ) -> tuple[str, str]:
            del resolved
            self._close(signal, context, status="dismissed")
            signal.decision_reason = payload.reason
            signal.decision_note = payload.note
            return "signal_dismissed", payload.reason

        return await self._decide(
            session,
            actor_id=actor_id,
            signal_id=signal_id,
            action="dismiss",
            payload=payload,
            idempotency_key=idempotency_key,
            apply=apply,
        )

    # --------------------------------------------------------- общий каркас

    async def _decide(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        signal_id: UUID,
        action: SignalActionCode,
        payload: SignalCommand,
        idempotency_key: str,
        apply: Callable[[Signal, OperationContext, _Resolved], Awaitable[tuple[str, str]]],
    ) -> SignalMutation:
        async with session.begin():
            signal, context = await self._context(
                session, actor_id, signal_id, write=True, permission=DECIDE_PERMISSION
            )
            operation = f"signal:{signal_id}:{action}"
            digest = stable_hash(
                {
                    "body": payload.model_dump(mode="json"),
                    "house_id": str(context.house_id),
                    "management_id": str(context.management_id.value),
                }
            )
            reliability = ReliabilityRepository(session)
            await reliability.lock_idempotency(
                actor_id=actor_id, action=operation, key=idempotency_key
            )
            record = await reliability.idempotency_record(
                actor_id=actor_id, action=operation, key=idempotency_key
            )
            if record is not None:
                if record.request_hash != digest:
                    raise IdempotencyConflict(
                        "This Idempotency-Key was already used with a different request body"
                    )
                return SignalMutation(
                    signal=await self._view(session, signal, context),
                    replayed=True,
                    effect_version=int(record.response_body["effect_version"]),
                )
            if signal.version != payload.expected_version:
                raise StaleSignalVersion("Сигнал изменился; перечитайте его и повторите решение")
            if signal.status not in OPEN_SIGNAL_STATUSES:
                raise SignalAlreadyDecided("Решение по этому сигналу уже принято")
            resolved = await self._resolved(session, signal)
            kind, details = await apply(signal, context, resolved)
            signal.version += 1
            session.add(
                SignalEvent(
                    house_id=signal.house_id,
                    signal_id=signal.id,
                    kind=kind,
                    details=details,
                    actor_id=actor_id,
                )
            )
            reliability.add_idempotency(
                actor_id=actor_id,
                action=operation,
                key=idempotency_key,
                request_hash=digest,
                response_status=200,
                response_body={"effect_version": signal.version},
            )
            await session.flush()
            return SignalMutation(
                signal=await self._view(session, signal, context),
                effect_version=signal.version,
            )

    @staticmethod
    def _scope(context: OperationContext) -> SignalScope:
        assert context.management_id.value is not None
        return SignalScope(house_id=context.house_id, management_id=context.management_id.value)

    async def _context(
        self,
        session: AsyncSession,
        actor_id: UUID,
        signal_id: UUID,
        *,
        write: bool = False,
        permission: str = READ_PERMISSION,
    ) -> tuple[Signal, OperationContext]:
        repo = SignalInboxRepository(session)
        # До проверки доступа читается только дом сигнала, не содержимое.
        house_id = await repo.signal_house(signal_id)
        if house_id is None:
            raise ResourceNotFound("Resource was not found")
        context = await self.memberships.require_house(
            session, user_id=actor_id, house_id=house_id, for_write=write
        )
        self.memberships.require_permission(context, READ_PERMISSION)
        if write:
            await PassiveRepository(session).lock(f"signals:{house_id}")
            # Запрос мог ждать чужую транзакцию: права разрешаются заново.
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=house_id
            )
        signal = await repo.in_scope(signal_id, self._scope(context), lock=write)
        if signal is None:
            raise ResourceNotFound("Resource was not found")
        self.memberships.require_permission(context, permission)
        return signal, context

    async def _resolved(self, session: AsyncSession, signal: Signal) -> _Resolved:
        house = await self.routing.house_context(session, signal.house_id)
        outcome = (
            await session.get(RouteOutcome, signal.route_outcome_id)
            if signal.route_outcome_id
            else None
        )
        return self._resolve(signal, house, outcome)

    def _resolve(
        self, signal: Signal, house: HouseRoutingContext, outcome: RouteOutcome | None
    ) -> _Resolved:
        """Текущий маршрут: роутер по справочнику или тип, выбранный оператором."""
        danger = _danger(signal)
        scope = _scope_value(signal.location_scope)
        router_route = self.routing.route(
            subtype=signal.subtype, location_scope=scope, house=house, danger_kinds=danger
        )
        route = router_route
        if outcome is not None and outcome.author_id is not None:
            route = self.routing.route_of_type(
                cast(RouteType, outcome.route_type),
                subtype=signal.subtype,
                location_scope=scope,
                house=house,
                danger_kinds=danger,
            )
        return _Resolved(
            route=route, router_route=router_route, outcome=outcome, house=house, danger=danger
        )

    @staticmethod
    def _close(signal: Signal, context: OperationContext, *, status: str) -> None:
        signal.status = status
        signal.decided_by = context.actor_user_id
        signal.decided_at = datetime.now(UTC)

    @staticmethod
    async def _outcome(
        session: AsyncSession,
        signal: Signal,
        context: OperationContext,
        route: ResponsibilityRoute,
        *,
        decision: str,
        report_id: UUID | None = None,
    ) -> RouteOutcome:
        """Исход решения оператора со снимком маршрута и автором.

        Сигнал указывает на последний исход: после решения карточка и снимок
        читаются из него, а не пересчитываются молча по новому справочнику.
        """
        outcome = RouteOutcome(
            house_id=signal.house_id,
            source="passive",
            subtype=signal.subtype,
            location_scope=signal.location_scope,
            route_type=route.route_type,
            organization_id=route.organization_id,
            channel_id=route.channels[0].id if route.channels else None,
            decision=decision,
            report_id=report_id,
            author_id=context.actor_user_id,
            signal_id=signal.id,
            basis=route.basis.model_dump(mode="json") if route.basis else None,
            directory_version=route.directory_version,
        )
        session.add(outcome)
        await session.flush()
        signal.route_outcome_id = outcome.id
        return outcome

    async def _intake_enabled(self, session: AsyncSession, context: OperationContext) -> bool:
        if context.management_id.value is None:
            return False
        enabled = await session.scalar(
            select(HouseManagement.ticket_intake_enabled).where(
                HouseManagement.id == context.management_id.value
            )
        )
        return bool(enabled)

    # ---------------------------------------------------------------- вид

    def _summary(
        self,
        signal: Signal,
        resolved: _Resolved,
        *,
        address: str,
        is_demo: bool,
        quotes: Sequence[Any],
    ) -> SignalSummary:
        first = quotes[0] if quotes else None
        return SignalSummary(
            id=signal.id,
            house_id=signal.house_id,
            house_address=address,
            subtype=signal.subtype,
            subtype_label=_signal_title(signal),
            object_label=signal.object_label,
            category=_category(signal.product_category),
            strength=_strength(signal.strength),
            strength_reason=strength_reason_text(signal.strength_reason),
            status=cast(SignalStatus, signal.status),
            report_count=signal.report_count,
            author_count=signal.author_count,
            first_seen_at=signal.first_seen_at,
            last_seen_at=signal.last_seen_at,
            first_quote=_quote_view(first.author_ref, first.sent_at, first.text) if first else None,
            place=_place(signal),
            route_type=resolved.route.route_type,
            route_source=(
                "operator"
                if resolved.outcome is not None and resolved.outcome.author_id is not None
                else "router"
            ),
            requires_operator_choice=resolved.route.requires_operator_choice,
            danger_kinds=list((signal.emergency or {}).get("kinds") or [])
            if (signal.emergency or {}).get("is_emergency")
            else [],
            is_demo=is_demo,
            version=signal.version,
        )

    async def _view(
        self, session: AsyncSession, signal: Signal, context: OperationContext
    ) -> SignalView:
        repo = SignalInboxRepository(session)
        resolved = await self._resolved(session, signal)
        houses = await repo.houses([signal.house_id])
        house = houses.get(signal.house_id)
        quotes = (await repo.quotes([signal.id])).get(signal.id, [])
        summary = self._summary(
            signal,
            resolved,
            address=house.address if house else "",
            is_demo=bool(house and house.is_demo),
            quotes=quotes,
        )
        open_signal = signal.status in OPEN_SIGNAL_STATUSES
        candidates = await self._join_candidates(session, signal, context) if open_signal else []
        card: ActionCard = self.action_cards.build(
            resolved.route,
            resolved.house,
            audience="operator",
            source="chat",
            danger_kinds=resolved.danger,
            existing_ticket_ref=candidates[0].title if candidates else None,
        )
        choices = route_choices(resolved.router_route) if open_signal else []
        outcome = resolved.outcome
        chosen = (
            outcome is not None and outcome.author_id is not None and signal.status == "in_review"
        )
        events = await repo.events(signal.id, list(EVENT_LABELS))
        names = await repo.user_names(
            [signal.decided_by, *(event.actor_id for event in events)]
            + ([outcome.author_id] if outcome is not None else [])
        )
        linked = await self._linked(session, signal)
        return SignalView(
            **summary.model_dump(),
            territory=SignalTerritory(
                scope=_scope_value(signal.location_scope),
                label=TERRITORY_LABELS.get(signal.location_scope, TERRITORY_LABELS["unknown"]),
                quote=(signal.location or {}).get("quote") or None,
            ),
            quotes=[_quote_view(item.author_ref, item.sent_at, item.text) for item in quotes],
            danger=self._danger_view(signal, quotes),
            action_card=card,
            route_choices=choices,
            route_chosen_by=(
                names.get(outcome.author_id) if chosen and outcome and outcome.author_id else None
            ),
            route_chosen_at=outcome.created_at if chosen and outcome else None,
            join_candidates=candidates,
            ticket_draft=await self._ticket_draft(session, signal, quotes=quotes),
            linked=linked,
            decision=self._decision(signal, outcome, names, resolved.house),
            allowed_actions=(
                await self._allowed(session, signal, context, resolved, card, candidates, choices)
                if open_signal
                else []
            ),
            events=[
                SignalEventView(
                    kind=event.kind,
                    label=EVENT_LABELS[event.kind],
                    at=event.created_at,
                    actor=names.get(event.actor_id) if event.actor_id else None,
                )
                for event in events
            ],
        )

    async def _allowed(
        self,
        session: AsyncSession,
        signal: Signal,
        context: OperationContext,
        resolved: _Resolved,
        card: ActionCard,
        candidates: Sequence[DuplicateCandidate],
        choices: Sequence[RouteType],
    ) -> list[SignalActionDescriptor]:
        """Команды оператора в порядке карточки маршрута, затем остальные."""
        permitted = DECIDE_PERMISSION in context.permissions
        available: dict[SignalActionCode, SignalActionDescriptor] = {}

        def put(code: SignalActionCode, enabled: bool, reason: str | None) -> None:
            if not permitted:
                enabled, reason = False, _NO_PERMISSION_REASON
            available[code] = SignalActionDescriptor(
                code=code, enabled=enabled, reason=None if enabled else reason
            )

        intake = await self._intake_enabled(session, context)
        put("create-ticket", intake, _NO_INTAKE_REASON)
        put("join", bool(candidates), _NO_CANDIDATES_REASON)
        if choices:
            put("choose-route", True, None)
        if resolved.route.route_type in EXTERNAL_ROUTES:
            put("route-external", True, None)
        elif resolved.route.route_type == "unknown":
            put("route-external", False, _CHOOSE_FIRST_REASON)
        put("dismiss", True, None)
        ordered: list[SignalActionCode] = []
        for action in card.actions:
            code = _CARD_TO_COMMAND.get(action.type)
            if code is not None and code in available and code not in ordered:
                ordered.append(code)
        ordered.extend(code for code in _COMMAND_ORDER if code in available and code not in ordered)
        return [available[code] for code in ordered]

    async def _join_candidates(
        self, session: AsyncSession, signal: Signal, context: OperationContext
    ) -> list[DuplicateCandidate]:
        """Связанная проблема прежнего решения — первой, затем правило P3c."""
        repo = SignalInboxRepository(session)
        incidents = IncidentRepository(session)
        after = datetime.now(UTC) - timedelta(days=JOIN_WINDOW_DAYS)
        related = await repo.related_incidents(signal, self._scope(context), created_after=after)
        by_category = await incidents.open_candidates(
            context,
            category=_category(signal.product_category).value,
            created_after=after,
            limit=MAX_JOIN_CANDIDATES,
        )
        entrance = (quoted_value(own_value(signal.entrance)) or (None,))[0]
        ordered = list(dict.fromkeys([*related, *by_category]))[:MAX_JOIN_CANDIDATES]
        counts = await incidents.counts([item.id for item in ordered])
        related_ids = {item.id for item in related}
        return [
            DuplicateCandidate(
                incident_id=incident.id,
                title=incident.title,
                category=_category(incident.category),
                status=IncidentStatus(incident.status),
                created_at=incident.created_at,
                report_count=counts.get(incident.id, (0, 0))[0],
                participant_count=counts.get(incident.id, (0, 0))[1],
                match_reason=(
                    RELATED_CONVERSION_REASON
                    if incident.id in related_ids
                    else SAME_ENTRANCE_REASON
                    if entrance is not None and incident.location_entrance == entrance
                    else SAME_CATEGORY_REASON
                ),
            )
            for incident in ordered
        ]

    async def _ticket_draft(
        self, session: AsyncSession, signal: Signal, *, quotes: Sequence[Any] | None = None
    ) -> SignalTicketDraft:
        if quotes is None:
            quotes = (await SignalInboxRepository(session).quotes([signal.id])).get(signal.id, [])
        category = _category(signal.product_category)
        return SignalTicketDraft(
            category=category,
            description=ticket_description(
                subject=_subtype_label(signal.subtype)
                if signal.subtype != "other.unspecified"
                else CATEGORY_TITLES[category],
                report_count=signal.report_count,
                author_count=signal.author_count,
                place={
                    "entrance": own_value(signal.entrance),
                    "floor": own_value(signal.floor),
                    "since": own_value(signal.since),
                },
                quotes=[(item.author_ref, item.text) for item in quotes],
            ),
        )

    def _danger_view(self, signal: Signal, quotes: Sequence[Any]) -> SignalDanger | None:
        emergency = signal.emergency or {}
        kinds_raw = emergency.get("kinds") or []
        if not kinds_raw or not (emergency.get("is_emergency") or emergency.get("downgraded")):
            return None
        kinds = [kind for kind in DANGER_KINDS if kind in kinds_raw]
        by_mid = {quote.line_mid: quote for quote in quotes}
        unverified = bool(emergency.get("evidence_unverified"))
        evidence: list[DangerEvidenceView] = []
        seen: set[tuple[str, str]] = set()

        def add(kind: str, source: DangerSource, text: str, mid: str | None) -> None:
            if kind not in DANGER_KINDS or not text or (kind, text) in seen:
                return
            seen.add((kind, text))
            quote = by_mid.get(mid) if mid else None
            evidence.append(
                DangerEvidenceView(
                    kind=kind,
                    label=DANGER_LABELS.get(kind, DANGER_LABELS["other_hazard"]),
                    source=source,
                    text=text,
                    author=author_label(quote.author_ref) if quote else None,
                    sent_at=quote.sent_at if quote else None,
                )
            )

        for item in emergency.get("evidence") or []:
            kind = str(item.get("kind") or "")
            mid = item.get("line_mid")
            if item.get("source") == "semantic":
                if unverified or not item.get("quote_valid", True):
                    # Цитата разбора не прошла проверку: оператор видит саму
                    # реплику жителя, а не слова модели.
                    quote = by_mid.get(mid) if mid else None
                    if quote is not None:
                        add(kind, "semantic", quote.text, mid)
                    continue
                add(kind, "semantic", str(item.get("quote") or ""), mid)
            else:
                add(kind, "rules", str(item.get("quote") or ""), mid)
        if unverified and not any(item.source == "semantic" for item in evidence):
            for quote in quotes:
                for kind in kinds:
                    add(kind, "semantic", quote.text, quote.line_mid)
        sources = [
            cast(DangerSource, source)
            for source in ("rules", "semantic")
            if source in (emergency.get("sources") or [])
        ]
        return SignalDanger(
            kinds=kinds,
            labels=[DANGER_LABELS.get(kind, DANGER_LABELS["other_hazard"]) for kind in kinds],
            sources=sources,
            evidence=evidence,
            evidence_unverified=unverified,
            preliminary=bool(emergency.get("preliminary")),
            displaced="displaced" in (signal.flags or []),
            downgraded=bool(emergency.get("downgraded")),
        )

    async def _linked(self, session: AsyncSession, signal: Signal) -> SignalLinked | None:
        if signal.incident_id is None:
            return None
        incident = await session.get(Incident, signal.incident_id)
        if incident is None:
            return None
        ticket = await SignalInboxRepository(session).latest_ticket(incident.id)
        return SignalLinked(
            incident_id=incident.id,
            report_id=signal.report_id,
            title=incident.title,
            ticket_id=ticket.id if ticket else None,
            ticket_number=f"T-{ticket.number}" if ticket else None,
        )

    def _decision(
        self,
        signal: Signal,
        outcome: RouteOutcome | None,
        names: dict[UUID, str],
        house: HouseRoutingContext,
    ) -> SignalDecisionView | None:
        if signal.decided_at is None:
            return None
        route = None
        if outcome is not None and outcome.author_id is not None and signal.status != "dismissed":
            basis = outcome.basis or {}
            organization, channel = self.routing.directory_entry(
                house, organization_id=outcome.organization_id, channel_id=outcome.channel_id
            )
            route = SignalRouteSnapshot(
                route_type=cast(RouteType, outcome.route_type),
                organization_name=organization,
                channel_label=channel.label if channel else None,
                basis_text=basis.get("text"),
                basis_source_title=basis.get("source_title"),
                basis_verified_at=basis.get("verified_at"),
                basis_verification_status=basis.get("verification_status"),
                directory_version=outcome.directory_version,
            )
        reason = cast(DismissReason | None, signal.decision_reason)
        return SignalDecisionView(
            status=cast(SignalStatus, signal.status),
            decided_by=names.get(signal.decided_by) if signal.decided_by else None,
            decided_at=signal.decided_at,
            reason=reason,
            reason_label=DISMISS_REASON_LABELS.get(reason) if reason else None,
            note=signal.decision_note,
            route=route,
        )


__all__ = [
    "CHOOSABLE_ROUTES",
    "EXTERNAL_ROUTES",
    "SignalActionUnavailable",
    "SignalAlreadyDecided",
    "SignalInboxService",
    "StaleSignalVersion",
    "route_choices",
]
