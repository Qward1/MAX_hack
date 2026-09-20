"""Разбор `/report <свободный текст>` до следующего шага жителя.

Одна общая функция обрабатывает и разбор ядром, и сторожевой разбор правилами:
отличается только то, есть ли у анализатора провайдер. Запись приёма
захватывается атомарно, поэтому ровно одна из двух задач доводит дело до
результата, а вторая тихо завершается.

Вызов модели идёт **вне транзакции БД** (целевая архитектура v3 §10): сначала
короткая транзакция захвата, затем проверка привязки и прав, затем разбор, и
только потом короткая транзакция записи, которая заново подтверждает доступ.

Модель здесь не решает, кто отвечает: это делает детерминированный
Responsibility Router по проверенному справочнику. Заявка УК создаётся только
для зоны УК; внешнее обращение житель отправляет сам.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.ai import (
    ExplicitReportDecision,
    WindowAnalysis,
    WindowAnalyzer,
    WindowInput,
    WindowLine,
    check_no_new_facts,
    decide_explicit_report,
)
from domsignal.contracts.incidents import (
    ReportAnalysisView,
    ReportCreate,
    ReportPreview,
)
from domsignal.contracts.routing import (
    ActionCard,
    DangerKind,
    LocationScope,
    ResponsibilityRoute,
)
from domsignal.core.incidents import ReportCategory
from domsignal.core.routing import UNSPECIFIED_SUBTYPE
from domsignal.db.models import ExplicitIntake, Incident, Report, RouteOutcome
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.action_cards import ActionCardBuilder
from domsignal.services.ai_budget import PostgresBudgetGuard
from domsignal.services.chat_connections import ChatConnectionError, ChatConnectionService
from domsignal.services.context import OperationContext
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.services.reports import ReportService
from domsignal.services.route_card_render import (
    ROUTE_CARD_INTENT_KIND,
    RouteCardIntent,
    build_route_card_intent,
)
from domsignal.services.routing import RoutingService

logger = logging.getLogger(__name__)

#: Маршруты, по которым заявка УК не создаётся: обращение отправляет человек.
EXTERNAL_ROUTE_TYPES = frozenset(
    {
        "municipality",
        "resource_supplier",
        "regional_operator",
        "other_authority",
        "emergency_service",
    }
)

#: Предел описания в `ReportCreate`. Более длинная реплика целиком остаётся в
#: записи приёма, а в описание заявки попадает её начало.
DESCRIPTION_LIMIT = 2000

#: Честная формулировка для маршрута, который определить не удалось.
DISPATCHER_REVIEW_NOTE = (
    "Ответственный пока не определён — разберёт диспетчер управляющей компании."
)

#: Опознавательный признак окна явного пути: одна реплика, один автор.
LINE_ID = "m1"
AUTHOR_REF = "a1"

#: Захват записи старше этого возраста считается брошенным упавшим воркером.
CLAIM_STALE_SECONDS = 600

_CLAIM = text(
    """
    UPDATE explicit_intakes
    SET state = 'claimed', claimed_at = now(), claimed_by = :worker, updated_at = now()
    WHERE event_id = :event_id
      AND (
        state = 'pending'
        OR (state = 'claimed' AND claimed_at < now() - make_interval(secs => :stale))
      )
    RETURNING chat_id, chat_binding_id, binding_version, external_user_id, text, occurred_at
    """
)

_RELEASE = text(
    """
    UPDATE explicit_intakes
    SET state = 'pending', claimed_at = NULL, claimed_by = NULL, updated_at = now()
    WHERE event_id = :event_id AND state = 'claimed'
    """
)

_SETTLE = text(
    """
    UPDATE explicit_intakes
    SET state = :state, result_kind = :result_kind, updated_at = now()
    WHERE event_id = :event_id
    """
)


@dataclass(frozen=True)
class ClaimedIntake:
    """Запись приёма, захваченная текущей задачей."""

    event_id: str
    chat_id: str
    chat_binding_id: UUID
    binding_version: int
    external_user_id: str
    text: str
    occurred_at: datetime


@dataclass(frozen=True)
class ExplicitOutcome:
    """Что получилось из одной реплики."""

    result_kind: str
    report_id: UUID | None = None
    route_outcome_id: UUID | None = None


class ExplicitReportService:
    """Приём свободного текста → разбор → маршрут → следующий шаг."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        chat_connections: ChatConnectionService,
        reports: ReportService,
        routing: RoutingService,
        action_cards: ActionCardBuilder,
        analyzer: WindowAnalyzer,
        rules_analyzer: WindowAnalyzer,
        budget: PostgresBudgetGuard | None = None,
    ) -> None:
        self.sessions = session_factory
        self.chat_connections = chat_connections
        self.reports = reports
        self.routing = routing
        self.action_cards = action_cards
        self.analyzer = analyzer
        self.rules_analyzer = rules_analyzer
        self.budget = budget
        self.memberships = MembershipService()

    # ------------------------------------------------------------ точки входа

    async def analyze_with_core(self, payload: dict[str, Any]) -> None:
        """Задача AI-пула: разбор ядром, если провайдер настроен."""
        await self.handle(str(payload["event_id"]), worker="ai.report.analyze", use_model=True)

    async def analyze_with_rules(self, payload: dict[str, Any]) -> None:
        """Сторожевая задача операционного пула: разбор только правилами."""
        await self.handle(str(payload["event_id"]), worker="report.fallback", use_model=False)

    async def preview(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        description: str,
    ) -> ReportPreview:
        """Предпросмотр маршрута для формы mini app: только правила, без записи.

        Модель здесь не вызывается сознательно: ответ нужен человеку
        синхронно, а разбор моделью живёт в AI-пуле. Ничего не создаётся —
        ни заявки, ни исхода маршрутизации, ни квитанции идемпотентности.
        """
        async with session.begin():
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=house_id
            )
            self.memberships.require_permission(context, "report.create")
            window = WindowInput(
                channel="form",
                lines=(
                    WindowLine(
                        line_id=LINE_ID,
                        author_ref=AUTHOR_REF,
                        text=description,
                        sent_at=datetime.now(UTC),
                    ),
                ),
            )
            analysis = await self.rules_analyzer.analyze(window)
            decision = decide_explicit_report(analysis)
            danger: tuple[DangerKind, ...] = tuple(decision.emergency.kinds)
            route, house = await self.routing.route_for_house(
                session,
                house_id=house_id,
                subtype=decision.subtype or UNSPECIFIED_SUBTYPE,
                location_scope=decision.location_scope,
                danger_kinds=danger,
            )
            card = self.action_cards.build(
                route,
                house,
                audience="resident",
                source="explicit",
                danger_kinds=danger,
            )
        return ReportPreview(
            analysis=ReportAnalysisView(
                subtype=decision.subtype,
                category=decision.product_category,
                location_scope=decision.location_scope,
                entrance=decision.entrance.value if decision.entrance else None,
                floor=decision.floor.value if decision.floor else None,
                since=decision.since.value if decision.since else None,
                danger_kinds=list(danger),
                mode=analysis.mode,
                confident=decision.confident,
                reason=decision.reason,
            ),
            action_card=card,
        )

    async def handle(self, event_id: str, *, worker: str, use_model: bool) -> None:
        """Обработать запись приёма, если её удалось захватить."""
        intake = await self._claim(event_id, worker)
        if intake is None:
            return  # Запись уже взял кто-то другой: тихо завершаемся.
        try:
            outcome = await self._process(intake, use_model=use_model)
        except (AccessDenied, ResourceNotFound, ChatConnectionError, ValidationError) as exc:
            # Терминальный отказ: повтор в другом контексте ничего не изменит.
            await self._settle(event_id, "failed", None)
            logger.warning(
                "explicit_report_terminal",
                extra={"worker": worker, "error_type": type(exc).__name__},
            )
            return
        except Exception:
            # Неожиданный отказ: отпускаем запись, чтобы её добрал повтор или
            # вторая задача, и отдаём ошибку механизму повторов.
            await self._release(event_id)
            raise
        await self._settle(event_id, "done", outcome.result_kind)
        logger.info(
            "explicit_report_done",
            extra={
                "worker": worker,
                "result_kind": outcome.result_kind,
                "report_id": str(outcome.report_id) if outcome.report_id else None,
                "route_outcome_id": (
                    str(outcome.route_outcome_id) if outcome.route_outcome_id else None
                ),
            },
        )

    # ------------------------------------------------------------------ шаги

    async def _claim(self, event_id: str, worker: str) -> ClaimedIntake | None:
        async with self.sessions() as session, session.begin():
            row = (
                await session.execute(
                    _CLAIM,
                    {"event_id": event_id, "worker": worker, "stale": CLAIM_STALE_SECONDS},
                )
            ).one_or_none()
        if row is None:
            return None
        return ClaimedIntake(event_id=event_id, **row._mapping)

    async def _release(self, event_id: str) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(_RELEASE, {"event_id": event_id})

    async def _settle(self, event_id: str, state: str, result_kind: str | None) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                _SETTLE, {"event_id": event_id, "state": state, "result_kind": result_kind}
            )

    async def _process(self, intake: ClaimedIntake, *, use_model: bool) -> ExplicitOutcome:
        # Свежесть прав проверяется перед каждым групповым эффектом.
        async with self.sessions() as session, session.begin():
            await self.chat_connections.verify_binding_health(session, intake.chat_binding_id)

        probe = await self._context(intake)
        if probe is None:
            return ExplicitOutcome(result_kind="ignored")
        actor_id, house_id, entrance = probe

        # Вызов модели — вне транзакции БД.
        analysis = await self._analyze(intake, entrance=entrance, use_model=use_model)
        decision = decide_explicit_report(analysis)

        async with self.sessions() as session, session.begin():
            context = await self._resolve(session, actor_id=actor_id, intake=intake)
            if context is None or context.house_id != house_id:
                return ExplicitOutcome(result_kind="ignored")
            return await self._apply(session, intake, context, analysis, decision)

    async def _context(self, intake: ClaimedIntake) -> tuple[UUID, UUID, str | None] | None:
        """Кто автор и к какому дому относится чат. Блокировки здесь не держим."""
        async with self.sessions() as session, session.begin():
            actor = await AccessRepository(session).user_by_max_id(intake.external_user_id)
            if actor is None:
                return None  # Автор не найден среди жителей: выходим без действий.
            context = await self._resolve(session, actor_id=actor.id, intake=intake)
            if context is None:
                return None
            return actor.id, context.house_id, context.entrance

    async def _resolve(
        self, session: AsyncSession, *, actor_id: UUID, intake: ClaimedIntake
    ) -> OperationContext | None:
        try:
            return await self.chat_connections.resolve_context(
                session,
                actor_id=actor_id,
                chat_id=intake.chat_id,
                binding_id=intake.chat_binding_id,
                version=intake.binding_version,
                occurred_at=intake.occurred_at,
            )
        except (ChatConnectionError, AccessDenied, ResourceNotFound):
            return None  # Устаревший или неразрешённый контекст терминален.

    async def _analyze(
        self, intake: ClaimedIntake, *, entrance: str | None, use_model: bool
    ) -> WindowAnalysis:
        window = WindowInput(
            channel="group_report",
            lines=(
                WindowLine(
                    line_id=LINE_ID,
                    author_ref=AUTHOR_REF,
                    text=intake.text,
                    sent_at=intake.occurred_at,
                ),
            ),
            entrance_hint=entrance,
        )
        if not use_model:
            return await self.rules_analyzer.analyze(window)
        if self.budget is None:
            return await self.analyzer.analyze(window)
        # Единица бюджета списывается до обращения к провайдеру; исчерпанный
        # бюджет даёт `fallback_budget` и результат правил без вызова.
        async with self.budget.reserve(str(intake.chat_binding_id)):
            return await self.analyzer.analyze(window)

    # --------------------------------------------------------------- решение

    async def _apply(
        self,
        session: AsyncSession,
        intake: ClaimedIntake,
        context: OperationContext,
        analysis: WindowAnalysis,
        decision: ExplicitReportDecision,
    ) -> ExplicitOutcome:
        danger: tuple[DangerKind, ...] = tuple(decision.emergency.kinds)
        subtype = decision.subtype or UNSPECIFIED_SUBTYPE
        scope: LocationScope = decision.location_scope
        route, house = await self.routing.route_for_house(
            session,
            house_id=context.house_id,
            subtype=subtype,
            location_scope=scope,
            danger_kinds=danger,
        )
        report_id: UUID | None = None
        if route.route_type in EXTERNAL_ROUTE_TYPES:
            result_kind, db_decision = "external_route", "external"
        elif route.route_type == "uk_internal" and decision.confident:
            result_kind, db_decision = "ticket", "ticket"
        else:
            result_kind, db_decision = "needs_clarification", "needs_clarification"

        if db_decision != "external":
            category = (
                decision.product_category if db_decision == "ticket" else ReportCategory.OTHER
            )
            report_id = await self._create_report(
                session,
                intake,
                context,
                category=category,
                analysis=analysis,
                decision=decision,
                route=route,
            )

        outcome = RouteOutcome(
            house_id=context.house_id,
            source="group_report",
            subtype=subtype,
            location_scope=scope,
            route_type=route.route_type,
            organization_id=route.organization_id,
            channel_id=route.channels[0].id if route.channels else None,
            decision=db_decision,
            report_id=report_id,
            intake_event_id=intake.event_id,
        )
        session.add(outcome)
        # Проверенная переформулировка живёт рядом с исходной репликой и нужна
        # только черновику обращения, где её правит человек.
        clean = guarded_clean_description(analysis, intake.text)
        if clean is not None:
            await session.execute(
                update(ExplicitIntake)
                .where(ExplicitIntake.event_id == intake.event_id)
                .values(clean_description=clean)
            )
        await session.flush()

        card = self.action_cards.build(
            route,
            house,
            audience="resident",
            source="explicit",
            danger_kinds=danger,
        )
        if self._needs_card(db_decision, danger):
            await self._enqueue_card(
                session,
                intake,
                card,
                route_outcome_id=outcome.id,
                house_id=context.house_id,
                recipient_user_id=context.actor_user_id,
                danger_kinds=danger,
                next_step=DISPATCHER_REVIEW_NOTE
                if db_decision == "needs_clarification"
                else None,
            )
        return ExplicitOutcome(
            result_kind=result_kind, report_id=report_id, route_outcome_id=outcome.id
        )

    @staticmethod
    def _needs_card(db_decision: str, danger: tuple[DangerKind, ...]) -> bool:
        """Карточка нужна внешнему маршруту, неопределённому — и всегда при опасности."""
        return bool(danger) or db_decision in {"external", "needs_clarification"}

    async def _create_report(
        self,
        session: AsyncSession,
        intake: ClaimedIntake,
        context: OperationContext,
        *,
        category: ReportCategory,
        analysis: WindowAnalysis,
        decision: ExplicitReportDecision,
        route: ResponsibilityRoute,
    ) -> UUID:
        truncated = len(intake.text) > DESCRIPTION_LIMIT
        payload = ReportCreate(
            house_id=context.house_id,
            category=category,
            description=intake.text[:DESCRIPTION_LIMIT],
            classification_mode="model" if analysis.mode == "model" else "rules",
        )
        created = await self.reports.create_in_context(
            session,
            context=context,
            payload=payload,
            idempotency_key=f"explicit:{intake.event_id}",
        )
        await session.execute(
            update(Report)
            .where(Report.id == created.report_id)
            .values(
                analysis=analysis_provenance(
                    analysis, decision, route, text_truncated=truncated
                )
            )
        )
        # Место и «с какого времени» — только значения с дословной цитатой.
        located = {
            "location_entrance": decision.entrance.value if decision.entrance else None,
            "location_floor": decision.floor.value if decision.floor else None,
            "observed_since": decision.since.value if decision.since else None,
        }
        if any(located.values()):
            await session.execute(
                update(Incident)
                .where(Incident.id == created.incident.id)
                .values(**located)
            )
        return created.report_id

    async def _enqueue_card(
        self,
        session: AsyncSession,
        intake: ClaimedIntake,
        card: ActionCard,
        *,
        route_outcome_id: UUID,
        house_id: UUID,
        recipient_user_id: UUID,
        danger_kinds: tuple[DangerKind, ...],
        next_step: str | None,
    ) -> None:
        """Положить карточку в существующий outbox; доставка живёт в A-05."""
        intent: RouteCardIntent = build_route_card_intent(
            card,
            route_outcome_id=route_outcome_id,
            house_id=house_id,
            recipient_user_id=recipient_user_id,
            danger_kinds=danger_kinds,
            next_step=next_step,
        )
        ReliabilityRepository(session).add_outbox(
            kind=ROUTE_CARD_INTENT_KIND,
            aggregate_id=route_outcome_id,
            payload=intent.model_dump(mode="json"),
            dedupe_key=f"route_card:{intake.event_id}",
        )


def guarded_clean_description(analysis: WindowAnalysis, source: str) -> str | None:
    """Деловая переформулировка модели, если она прошла guard `no_new_facts`.

    Guard детерминированный и не обращается ни к модели, ни в сеть: любое
    число, дата, номер подъезда, имя собственное или название организации,
    которого нет в исходной реплике, отбрасывает текст целиком. В режиме
    правил переформулировки нет вовсе, и это нормальный исход.
    """
    for signal in analysis.signals:
        block = signal.clean_description
        if block is None or not block.text.strip():
            continue
        if check_no_new_facts(block.text, [source]).ok:
            return block.text.strip()
        logger.info("explicit_report_clean_description_rejected")
    return None


def analysis_provenance(
    analysis: WindowAnalysis,
    decision: ExplicitReportDecision,
    route: ResponsibilityRoute,
    *,
    text_truncated: bool,
) -> dict[str, Any]:
    """Происхождение разбора без текста реплики.

    Здесь только режим, состояния, версии, подтип, территория, флаги, число
    отброшенных полей и идентификатор модели: по этой записи видно, чем и как
    был получен результат, но не что именно написал житель.
    """
    execution = analysis.execution
    return {
        "mode": analysis.mode,
        "classification_mode": "model" if analysis.mode == "model" else "rules",
        "state": execution.state,
        "provider_called": execution.provider_called,
        "latency_ms": execution.latency_ms,
        "model": execution.provider_model,
        "tokens_in": execution.tokens_in,
        "tokens_out": execution.tokens_out,
        "cost_rub": execution.cost_rub,
        "versions": {
            "taxonomy": analysis.versions.taxonomy,
            "rules": analysis.versions.rules,
            "schema_id": analysis.versions.schema_id,
            "prompt": analysis.versions.prompt,
            "model": analysis.versions.model,
            "input_sha256": analysis.versions.input_sha256,
        },
        "subtype": decision.subtype,
        "location_scope": decision.location_scope,
        "confident": decision.confident,
        "reason": decision.reason,
        "danger_kinds": list(decision.emergency.kinds),
        "emergency": {
            "is_emergency": decision.emergency.is_emergency,
            "sources": list(decision.emergency.sources),
            "downgraded": decision.emergency.downgraded,
            "downgrade_reason": decision.emergency.downgrade_reason,
            "evidence_unverified": decision.emergency.evidence_unverified,
        },
        "flags": sorted({flag for signal in analysis.signals for flag in signal.flags}),
        "dropped_fields": analysis.dropped_fields,
        "audit_events": sorted({event.kind for event in analysis.audit_events}),
        "route_type": route.route_type,
        "directory_version": route.directory_version,
        "text_truncated": text_truncated,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


__all__ = [
    "EXTERNAL_ROUTE_TYPES",
    "ClaimedIntake",
    "ExplicitOutcome",
    "ExplicitReportService",
    "analysis_provenance",
    "guarded_clean_description",
]
