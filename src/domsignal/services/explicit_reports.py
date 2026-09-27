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

Сообщение в личке бота (`dm_report`, D1) проходит тот же путь: окно из одной
реплики, AI-пул и сторож правил, тот же `_apply`. Отличия — вокруг: дом
выбран до разбора, карточка уходит всегда, текст, который разбор отнёс к
болтовне или вопросу, не сохраняется, а при открытой проблеме той же
категории житель сам выбирает «та же проблема» или «другое».
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text, update
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
    DuplicateCandidate,
    ReportAnalysisView,
    ReportCreate,
    ReportCreated,
    ReportPreview,
    ReportSubmitRequest,
    ReportSubmitted,
)
from domsignal.contracts.routing import (
    LOCATION_SCOPES,
    ActionCard,
    DangerKind,
    LocationScope,
    ResponsibilityRoute,
    RouteDecision,
    RouteOutcomeView,
)
from domsignal.core.incidents import IncidentStatus, ReportCategory
from domsignal.core.routing import UNSPECIFIED_SUBTYPE
from domsignal.db.models import (
    AppealDraft,
    ExplicitIntake,
    Incident,
    Report,
    RouteOutcome,
    Ticket,
    User,
)
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.incidents import IncidentRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.action_cards import ActionCardBuilder
from domsignal.services.ai_budget import PostgresBudgetGuard, estimate_tokens
from domsignal.services.ai_provenance import execution_provenance
from domsignal.services.bot_replies import (
    DUPLICATE_LEAD,
    DUPLICATE_QUESTION,
    HELP,
    HOLD_JOB,
    NO_ACCESS,
    NOT_A_PROBLEM,
    OTHER_PROBLEM_LABEL,
    SAME_PROBLEM_LABEL,
    callback_button,
    enqueue_reply,
)
from domsignal.services.chat_connections import ChatConnectionError, ChatConnectionService
from domsignal.services.context import OperationContext
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.services.reports import ReportService
from domsignal.services.resident_access import ResidentAccessService, ensure_max_user
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

#: Следующий шаг в личке при зоне УК: заявка есть в очереди УК или проблема
#: появилась на доске дома, если приём заявок у дома выключен.
TICKET_QUEUED_NOTE = (
    "Заявка появилась в очереди вашей управляющей компании. Ход работ — в ДомСигнале."
)
BOARD_NOTE = "Проблема появилась на доске дома в ДомСигнале."

#: Реплика из лички ждёт ответа «та же проблема / другое».
AWAITING_CHOICE = "awaiting_choice"

#: Роли реплики, которые разбор относит к болтовне, вопросу или объявлению.
NOT_A_PROBLEM_ROLES = frozenset(
    {"chatter", "out_of_scope", "status_question", "discussion", "announcement"}
)

#: Опознавательный признак окна явного пути: одна реплика, один автор.
LINE_ID = "m1"
AUTHOR_REF = "a1"

#: Захват записи старше этого возраста считается брошенным упавшим воркером.
CLAIM_STALE_SECONDS = 600

#: Сколько уже открытых проблем показывается жителю до отправки.
MAX_DUPLICATES = 3

#: Возраст, после которого открытая проблема перестаёт считаться той же самой.
DUPLICATE_WINDOW_DAYS = 14

#: Шаблоны пояснения к кандидату. Свободного текста здесь нет.
SAME_CATEGORY_REASON = "Та же категория, проблема открыта"
SAME_ENTRANCE_REASON = "Тот же подъезд, проблема открыта"

_CLAIM = text(
    """
    UPDATE explicit_intakes
    SET state = 'claimed', claimed_at = now(), claimed_by = :worker, updated_at = now()
    WHERE event_id = :event_id
      AND (
        state = 'pending'
        OR (state = 'claimed' AND claimed_at < now() - make_interval(secs => :stale))
      )
      AND (channel = 'group_report' OR house_id IS NOT NULL)
    RETURNING chat_id, chat_binding_id, binding_version, external_user_id, text, occurred_at,
              channel, house_id, user_id
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


#: F1: пауза перед повтором вызова модели после 429 на явном пути.
EXPLICIT_RETRY_MAX_SECONDS = 5.0


@dataclass(frozen=True)
class ClaimedIntake:
    """Запись приёма, захваченная текущей задачей."""

    event_id: str
    chat_id: str
    chat_binding_id: UUID | None
    binding_version: int | None
    external_user_id: str
    text: str
    occurred_at: datetime
    channel: str = "group_report"
    house_id: UUID | None = None
    user_id: UUID | None = None


@dataclass(frozen=True)
class ReportOrigin:
    """Откуда пришло сообщение жителя: домовой чат или форма mini app.

    Решение «какой маршрут → что создаём» одно на оба пути и живёт в
    `_apply`. Источник отличается только тем, что вокруг: чат приносит запись
    приёма и получает карточку личным сообщением, форма приносит слова
    жителя и получает ту же карточку в ответе.
    """

    source: Literal["group_report", "form", "dm_report"]
    text: str
    occurred_at: datetime
    author_id: UUID
    idempotency_key: str
    intake_event_id: str | None = None
    #: Ключ дедупликации карточки в outbox. Пуст, когда карточку не шлют.
    card_dedupe_ref: str | None = None
    #: Категория, выбранная жителем вручную, когда разбор его не убедил.
    category: ReportCategory | None = None
    #: Личка: карточка уходит при любом исходе — это ответ на сообщение.
    always_card: bool = False


@dataclass(frozen=True)
class ExplicitOutcome:
    """Что получилось из одной реплики."""

    result_kind: str
    report_id: UUID | None = None
    route_outcome_id: UUID | None = None
    decision: RouteDecision = "needs_clarification"
    card: ActionCard | None = None
    report: ReportCreated | None = None


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
        resident_access: ResidentAccessService | None = None,
        hold_seconds: int = 1800,
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
        # Житель = участник чата: автор `/report` проверяется по MAX API (D1).
        self.resident_access = resident_access
        self.hold_seconds = hold_seconds

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
            analysis = await self.rules_analyzer.analyze(
                _form_window(description, datetime.now(UTC), entrance=context.entrance)
            )
            decision = decide_explicit_report(analysis)
            danger: tuple[DangerKind, ...] = tuple(decision.emergency.kinds)
            route, house = await self.routing.route_for_house(
                session,
                house_id=house_id,
                subtype=decision.subtype or UNSPECIFIED_SUBTYPE,
                location_scope=decision.location_scope,
                danger_kinds=danger,
            )
            # B-06: при опасности дубли не предлагаются — как в личке бота:
            # сначала блок безопасности, а не «присоединиться» к чужой проблеме.
            duplicates = (
                []
                if danger
                else await self._duplicates(
                    session,
                    context,
                    category=decision.product_category,
                    entrance=decision.entrance.value if decision.entrance else None,
                    now=datetime.now(UTC),
                )
            )
            card = self.action_cards.build(
                route,
                house,
                audience="resident",
                source="explicit",
                danger_kinds=danger,
                # Заголовок первой существующей проблемы включает в карточке
                # действие «присоединиться»; идентификатор интерфейс берёт из
                # `duplicates`, а не из этой строки.
                existing_ticket_ref=duplicates[0].title if duplicates else None,
            )
        return ReportPreview(
            analysis=_analysis_view(analysis, decision, danger),
            action_card=card,
            duplicates=duplicates,
        )

    async def submit(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        house_id: UUID,
        payload: ReportSubmitRequest,
        idempotency_key: str,
    ) -> ReportSubmitted:
        """Отправка формы по той же цепочке, что и сообщение в домовом чате.

        Разбор синхронный и только правилами: ответ нужен человеку сразу, а
        разбор моделью живёт в AI-пуле. Решение принимает общий `_apply`,
        поэтому форма не может разойтись с чатом.
        """
        now = datetime.now(UTC)
        async with session.begin():
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=house_id, for_write=True
            )
            self.memberships.require_permission(context, "report.create")
            analysis = await self.rules_analyzer.analyze(
                _form_window(payload.description, now, entrance=context.entrance)
            )
            decision = decide_explicit_report(analysis)
            origin = ReportOrigin(
                source="form",
                text=payload.description,
                occurred_at=now,
                author_id=context.actor_user_id,
                idempotency_key=idempotency_key,
                category=payload.category,
            )
            outcome = await self._apply(session, origin, context, analysis, decision)
        assert outcome.card is not None and outcome.route_outcome_id is not None
        return ReportSubmitted(
            route_outcome_id=outcome.route_outcome_id,
            decision=outcome.decision,
            analysis=_analysis_view(analysis, decision, tuple(decision.emergency.kinds)),
            action_card=outcome.card,
            report=outcome.report,
        )

    # ------------------------------------------------------------- кандидаты

    async def _duplicates(
        self,
        session: AsyncSession,
        context: OperationContext,
        *,
        category: ReportCategory,
        entrance: str | None,
        now: datetime,
    ) -> list[DuplicateCandidate]:
        """Уже открытые проблемы того же дома по детерминированному правилу.

        Продукт ничего не сливает сам: список нужен только для того, чтобы
        житель сам сказал «это та же проблема» или «нет, это другое».
        «Другое» — не категория, а её отсутствие: совпадением не считается (B-06).
        """
        if category == ReportCategory.OTHER:
            return []
        repo = IncidentRepository(session)
        incidents = await repo.open_candidates(
            context,
            category=category.value,
            created_after=now - timedelta(days=DUPLICATE_WINDOW_DAYS),
            limit=MAX_DUPLICATES,
        )
        counts = await repo.counts([incident.id for incident in incidents])
        return [
            DuplicateCandidate(
                incident_id=incident.id,
                title=incident.title,
                category=ReportCategory(incident.category),
                status=IncidentStatus(incident.status),
                created_at=incident.created_at,
                report_count=counts.get(incident.id, (0, 0))[0],
                participant_count=counts.get(incident.id, (0, 0))[1],
                match_reason=(
                    SAME_ENTRANCE_REASON
                    if entrance is not None and incident.location_entrance == entrance
                    else SAME_CATEGORY_REASON
                ),
            )
            for incident in incidents
        ]

    # --------------------------------------------------- чтение исхода

    async def outcome_view(
        self, session: AsyncSession, *, actor_id: UUID, outcome_id: UUID
    ) -> RouteOutcomeView:
        """Карточка по сохранённому исходу, собранная по текущему справочнику.

        Чужой и несуществующий исход неотличимы: оба дают 404. Карточка не
        берётся из снимка доставки — справочник мог обновиться, и житель
        должен видеть актуальный маршрут, а не вчерашний.
        """
        async with session.begin():
            outcome = await session.get(RouteOutcome, outcome_id)
            if outcome is None or outcome.author_id != actor_id:
                raise ResourceNotFound("Resource was not found")
            context = await self.memberships.require_house(
                session, user_id=actor_id, house_id=outcome.house_id
            )
            danger = await self._recorded_danger(session, outcome)
            route, house = await self.routing.route_for_house(
                session,
                house_id=outcome.house_id,
                subtype=outcome.subtype,
                location_scope=_known_scope(outcome.location_scope),
                danger_kinds=danger,
            )
            card = self.action_cards.build(
                route,
                house,
                audience="resident",
                source="explicit",
                danger_kinds=danger,
            )
            incident_id: UUID | None = None
            if outcome.report_id is not None:
                report = await session.get(Report, outcome.report_id)
                incident_id = report.incident_id if report is not None else None
            draft_id = await session.scalar(
                select(AppealDraft.id).where(
                    AppealDraft.route_outcome_id == outcome.id,
                    AppealDraft.author_id == context.actor_user_id,
                )
            )
            return RouteOutcomeView(
                id=outcome.id,
                house_id=outcome.house_id,
                created_at=outcome.created_at,
                decision=_known_decision(outcome.decision),
                route_type=route.route_type,
                action_card=card,
                incident_id=incident_id,
                appeal_draft_id=draft_id,
                directory_changed=route.route_type != outcome.route_type,
            )

    async def _recorded_danger(
        self, session: AsyncSession, outcome: RouteOutcome
    ) -> tuple[DangerKind, ...]:
        """Признаки опасности по тем же словам жителя и тем же правилам.

        Отдельного столбца для них нет сознательно: правила детерминированы,
        поэтому повторный разбор сохранённого текста даёт ровно тот же ответ,
        а лишнего приватного поля в базе не появляется.
        """
        source = outcome.submitted_text
        if source is None and outcome.intake_event_id is not None:
            intake = await session.get(ExplicitIntake, outcome.intake_event_id)
            source = intake.text if intake is not None else None
        if not source:
            return ()
        analysis = await self.rules_analyzer.analyze(
            _form_window(source, outcome.created_at, entrance=None)
        )
        return tuple(decide_explicit_report(analysis).emergency.kinds)

    async def handle(self, event_id: str, *, worker: str, use_model: bool) -> None:
        """Обработать запись приёма, если её удалось захватить."""
        intake = await self._claim(event_id, worker)
        if intake is None:
            return  # Запись уже взял кто-то другой: тихо завершаемся.
        try:
            outcome = await self._process(intake, use_model=use_model)
            if outcome.result_kind == AWAITING_CHOICE:
                return  # Запись ждёт ответа жителя; состояние уже записано.
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
        if intake.channel == "dm_report":
            return await self._process_dm(intake, use_model=use_model)
        assert intake.chat_binding_id is not None
        # Свежесть прав проверяется перед каждым групповым эффектом.
        async with self.sessions() as session, session.begin():
            await self.chat_connections.verify_binding_health(session, intake.chat_binding_id)

        probe = await self._context(intake)
        if probe is None:
            return ExplicitOutcome(result_kind="ignored")
        actor_id, house_id, entrance = probe

        # Вызов модели — вне транзакции БД.
        analysis = await self._analyze(intake, entrance=entrance, use_model=use_model)
        # Учёт вызова пишется сразу, до решения: у внешнего маршрута заявки
        # нет, а задержка и стоимость нужны метрикам при любом исходе.
        await self._record(intake.event_id, analysis)
        decision = decide_explicit_report(analysis)

        async with self.sessions() as session, session.begin():
            context = await self._resolve(session, actor_id=actor_id, intake=intake)
            if context is None or context.house_id != house_id:
                return ExplicitOutcome(result_kind="ignored")
            origin = ReportOrigin(
                source="group_report",
                text=intake.text,
                occurred_at=intake.occurred_at,
                author_id=actor_id,
                idempotency_key=f"explicit:{intake.event_id}",
                intake_event_id=intake.event_id,
                card_dedupe_ref=intake.event_id,
            )
            return await self._apply(session, origin, context, analysis, decision)

    # ------------------------------------------------------------- личка

    async def _process_dm(self, intake: ClaimedIntake, *, use_model: bool) -> ExplicitOutcome:
        """Сообщение из лички бота: дом уже выбран, права проверяются по дому."""
        assert intake.user_id is not None and intake.house_id is not None
        async with self.sessions() as session, session.begin():
            try:
                context = await self.memberships.require_house(
                    session, user_id=intake.user_id, house_id=intake.house_id, source="max_dm"
                )
                self.memberships.require_permission(context, "report.create")
            except (AccessDenied, ResourceNotFound):
                await enqueue_reply(
                    session,
                    user_id=intake.user_id,
                    event_id=intake.event_id,
                    key="noaccess",
                    text=NO_ACCESS,
                )
                await self._forget(session, intake.event_id)
                return ExplicitOutcome(result_kind="ignored")
        # Вызов модели — вне транзакции БД.
        analysis = await self._analyze(intake, entrance=None, use_model=use_model)
        await self._record(intake.event_id, analysis)
        decision = decide_explicit_report(analysis)
        if looks_like_no_problem(analysis, decision):
            async with self.sessions() as session, session.begin():
                await enqueue_reply(
                    session,
                    user_id=intake.user_id,
                    event_id=intake.event_id,
                    key="notproblem",
                    text=f"{NOT_A_PROBLEM}\n\n{HELP}",
                )
                # Такой текст не сохраняется.
                await self._forget(session, intake.event_id)
            return ExplicitOutcome(result_kind="not_a_problem")
        return await self._decide_dm(intake, analysis, decision, ask_duplicates=True)

    async def _decide_dm(
        self,
        intake: ClaimedIntake,
        analysis: WindowAnalysis,
        decision: ExplicitReportDecision,
        *,
        ask_duplicates: bool,
    ) -> ExplicitOutcome:
        """Решение по сообщению из лички: вопрос о дубле или общий `_apply`.

        При открытой проблеме той же категории продукт ничего не сливает сам:
        житель выбирает «та же проблема» или «другое» (семантика join P3c).
        При опасности вопроса нет — карточка с блоком безопасности сразу.
        """
        assert intake.user_id is not None and intake.house_id is not None
        danger: tuple[DangerKind, ...] = tuple(decision.emergency.kinds)
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            context = await self.memberships.require_house(
                session,
                user_id=intake.user_id,
                house_id=intake.house_id,
                source="max_dm",
                for_write=True,
            )
            self.memberships.require_permission(context, "report.create")
            if ask_duplicates and decision.confident and not danger:
                duplicates = await self._duplicates(
                    session,
                    context,
                    category=decision.product_category,
                    entrance=decision.entrance.value if decision.entrance else None,
                    now=now,
                )
                if duplicates:
                    first = duplicates[0]
                    await session.execute(
                        update(ExplicitIntake)
                        .where(ExplicitIntake.event_id == intake.event_id)
                        .values(
                            state=AWAITING_CHOICE,
                            pending_analysis=analysis.model_dump(mode="json"),
                            hold_until=now + timedelta(seconds=self.hold_seconds),
                        )
                    )
                    await enqueue_reply(
                        session,
                        user_id=intake.user_id,
                        event_id=intake.event_id,
                        key="duplicate",
                        text=f"{DUPLICATE_LEAD.format(title=first.title)}\n{DUPLICATE_QUESTION}",
                        buttons=[
                            [
                                callback_button(
                                    SAME_PROBLEM_LABEL,
                                    f"b:same:{intake.event_id}:{first.incident_id}",
                                )
                            ],
                            [callback_button(OTHER_PROBLEM_LABEL, f"b:new:{intake.event_id}")],
                        ],
                    )
                    await ReliabilityRepository(session).add_job(
                        kind=HOLD_JOB,
                        payload={"event_id": intake.event_id},
                        priority=90,
                        delay_seconds=self.hold_seconds,
                    )
                    return ExplicitOutcome(result_kind=AWAITING_CHOICE)
            origin = ReportOrigin(
                source="dm_report",
                text=intake.text,
                occurred_at=intake.occurred_at,
                author_id=intake.user_id,
                idempotency_key=f"explicit:{intake.event_id}",
                intake_event_id=intake.event_id,
                card_dedupe_ref=intake.event_id,
                always_card=True,
            )
            return await self._apply(session, origin, context, analysis, decision)

    async def choose_other(self, *, event_id: str, user_id: UUID) -> ExplicitOutcome | None:
        """«Другое»: разобранное сообщение становится новой проблемой.

        Разбор берётся сохранённый — модель повторно не вызывается. Повторное
        нажатие и чужая запись ничего не делают.
        """
        intake = await self._take_choice(event_id, user_id)
        if intake is None:
            return None
        claimed, payload = intake
        try:
            analysis = WindowAnalysis.model_validate(payload)
            decision = decide_explicit_report(analysis)
            outcome = await self._decide_dm(claimed, analysis, decision, ask_duplicates=False)
        except (AccessDenied, ResourceNotFound, ValidationError):
            await self._settle(event_id, "failed", None)
            return None
        await self._settle(event_id, "done", outcome.result_kind)
        return outcome

    async def joined(self, *, event_id: str, user_id: UUID) -> bool:
        """«Та же проблема»: житель присоединился — текст сообщения не нужен."""
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                update(ExplicitIntake)
                .where(
                    ExplicitIntake.event_id == event_id,
                    ExplicitIntake.channel == "dm_report",
                    ExplicitIntake.user_id == user_id,
                    ExplicitIntake.state == AWAITING_CHOICE,
                )
                .values(
                    state="done",
                    result_kind="joined",
                    text="",
                    clean_description=None,
                    pending_analysis=None,
                    hold_until=None,
                )
            )
            return bool(getattr(result, "rowcount", 0))

    async def pending_choice(self, *, event_id: str, user_id: UUID) -> bool:
        """Ждёт ли запись ответа этого жителя (не истекла ли)."""
        async with self.sessions() as session, session.begin():
            intake = await session.get(ExplicitIntake, event_id)
            return (
                intake is not None
                and intake.channel == "dm_report"
                and intake.user_id == user_id
                and intake.state == AWAITING_CHOICE
                and intake.pending_analysis is not None
                and (intake.hold_until is None or intake.hold_until > datetime.now(UTC))
            )

    async def _take_choice(
        self, event_id: str, user_id: UUID
    ) -> tuple[ClaimedIntake, dict[str, Any]] | None:
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            intake = await session.get(ExplicitIntake, event_id, with_for_update=True)
            if (
                intake is None
                or intake.channel != "dm_report"
                or intake.user_id != user_id
                or intake.state != AWAITING_CHOICE
                or intake.pending_analysis is None
                or (intake.hold_until is not None and intake.hold_until <= now)
            ):
                return None
            payload = dict(intake.pending_analysis)
            claimed = ClaimedIntake(
                event_id=intake.event_id,
                chat_id=intake.chat_id,
                chat_binding_id=None,
                binding_version=None,
                external_user_id=intake.external_user_id,
                text=intake.text,
                occurred_at=intake.occurred_at,
                channel=intake.channel,
                house_id=intake.house_id,
                user_id=intake.user_id,
            )
            # Второе нажатие не применит выбор повторно.
            intake.state = "claimed"
            intake.claimed_at = now
            intake.claimed_by = "bot.choice"
            intake.pending_analysis = None
            intake.hold_until = None
        return claimed, payload

    @staticmethod
    async def _forget(session: AsyncSession, event_id: str) -> None:
        """Стереть слова жителя из записи приёма: текст не нужен и не хранится."""
        await session.execute(
            update(ExplicitIntake)
            .where(ExplicitIntake.event_id == event_id)
            .values(text="", clean_description=None, pending_analysis=None, hold_until=None)
        )

    async def _record(self, event_id: str, analysis: WindowAnalysis) -> None:
        """Провенанс разбора в записи приёма: без текста, для любого исхода."""
        async with self.sessions() as session, session.begin():
            await session.execute(
                update(ExplicitIntake)
                .where(ExplicitIntake.event_id == event_id)
                .values(analysis=intake_provenance(analysis))
            )

    async def _context(self, intake: ClaimedIntake) -> tuple[UUID, UUID, str | None] | None:
        """Кто автор и к какому дому относится чат. Блокировки здесь не держим.

        Житель — участник чата (D1): автора без действующего членства бот
        проверяет точечным вызовом MAX API по этому чату. Сама реплика доступа
        не даёт.
        """
        async with self.sessions() as session, session.begin():
            actor: User | None
            if self.resident_access is not None:
                actor = await ensure_max_user(session, intake.external_user_id, None)
            else:
                actor = await AccessRepository(session).user_by_max_id(intake.external_user_id)
            if actor is None:
                return None  # Автор не найден среди жителей: выходим без действий.
            actor_id = actor.id
        if self.resident_access is not None:
            await self.resident_access.refresh(actor_id, chat_ids=(intake.chat_id,))
        async with self.sessions() as session, session.begin():
            context = await self._resolve(session, actor_id=actor_id, intake=intake)
            if context is None:
                return None
            return actor_id, context.house_id, context.entrance

    async def _resolve(
        self, session: AsyncSession, *, actor_id: UUID, intake: ClaimedIntake
    ) -> OperationContext | None:
        assert intake.chat_binding_id is not None and intake.binding_version is not None
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
            channel="dm_report" if intake.channel == "dm_report" else "group_report",
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
        # бюджет даёт `fallback_budget` и результат правил без вызова. Личка
        # делит дневной бюджет по жителю, как группа — по чату.
        scope = (
            f"dm:{intake.user_id}" if intake.channel == "dm_report" else str(intake.chat_binding_id)
        )
        tokens = estimate_tokens([intake.text])
        async with self.budget.reserve(scope, tokens=tokens):
            analysis = await self.analyzer.analyze(window)
        if analysis.execution.state != "fallback_rate_limited":
            return analysis
        # F1: житель ждёт ответа — одна повторная попытка не позже чем через
        # 5 с, затем правила с честной пометкой `fallback_rate_limited`.
        pause = min(analysis.execution.retry_after_s or 2.0, EXPLICIT_RETRY_MAX_SECONDS)
        await asyncio.sleep(pause)
        async with self.budget.reserve(scope, tokens=tokens):
            return await self.analyzer.analyze(window)

    # --------------------------------------------------------------- решение

    async def _apply(
        self,
        session: AsyncSession,
        origin: ReportOrigin,
        context: OperationContext,
        analysis: WindowAnalysis,
        decision: ExplicitReportDecision,
    ) -> ExplicitOutcome:
        """Единственное место, где маршрут превращается в результат.

        Чатовый и формовый пути приходят сюда с одним и тем же `ReportOrigin`:
        второй копии правила «какой маршрут → что создаём» в продукте нет.
        """
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
        report: ReportCreated | None = None
        db_decision: RouteDecision
        if route.route_type in EXTERNAL_ROUTE_TYPES:
            result_kind, db_decision = "external_route", "external"
        elif route.route_type == "uk_internal" and decision.confident:
            result_kind, db_decision = "ticket", "ticket"
        else:
            result_kind, db_decision = "needs_clarification", "needs_clarification"

        if db_decision != "external":
            # Категория, названная жителем вручную, не теряется и в неуверенной
            # зоне: маршрут там всё равно уточняет диспетчер, но заявка уходит
            # к нему не как «другое». Само решение выбор из списка не меняет.
            category = origin.category or (
                decision.product_category if db_decision == "ticket" else ReportCategory.OTHER
            )
            report = await self._create_report(
                session,
                origin,
                context,
                category=category,
                analysis=analysis,
                decision=decision,
                route=route,
                subtype=subtype,
                scope=scope,
                danger=danger,
            )

        outcome = RouteOutcome(
            house_id=context.house_id,
            source=origin.source,
            subtype=subtype,
            location_scope=scope,
            route_type=route.route_type,
            organization_id=route.organization_id,
            channel_id=route.channels[0].id if route.channels else None,
            decision=db_decision,
            report_id=report.report_id if report else None,
            intake_event_id=origin.intake_event_id,
            author_id=origin.author_id,
            # Слова жителя из формы живут здесь: записи приёма у неё нет, а без
            # текста черновик внешнего обращения остался бы без описания.
            submitted_text=origin.text if origin.source == "form" else None,
        )
        session.add(outcome)
        # Проверенная переформулировка живёт рядом с исходной репликой и нужна
        # только черновику обращения, где её правит человек.
        clean = guarded_clean_description(analysis, origin.text)
        if clean is not None and origin.intake_event_id is not None:
            await session.execute(
                update(ExplicitIntake)
                .where(ExplicitIntake.event_id == origin.intake_event_id)
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
        if origin.card_dedupe_ref and (
            origin.always_card or self._needs_card(db_decision, danger)
        ):
            next_step = None
            if db_decision == "needs_clarification":
                next_step = DISPATCHER_REVIEW_NOTE
            elif db_decision == "ticket" and origin.always_card and report is not None:
                next_step = (
                    TICKET_QUEUED_NOTE
                    if await session.scalar(
                        select(Ticket.id).where(Ticket.incident_id == report.incident.id)
                    )
                    else BOARD_NOTE
                )
            await self._enqueue_card(
                session,
                origin,
                card,
                route_outcome_id=outcome.id,
                house_id=context.house_id,
                recipient_user_id=context.actor_user_id,
                danger_kinds=danger,
                next_step=next_step,
            )
        return ExplicitOutcome(
            result_kind=result_kind,
            report_id=report.report_id if report else None,
            route_outcome_id=outcome.id,
            decision=db_decision,
            card=card,
            report=report,
        )

    @staticmethod
    def _needs_card(db_decision: str, danger: tuple[DangerKind, ...]) -> bool:
        """Карточка нужна внешнему маршруту, неопределённому — и всегда при опасности."""
        return bool(danger) or db_decision in {"external", "needs_clarification"}

    async def _create_report(
        self,
        session: AsyncSession,
        origin: ReportOrigin,
        context: OperationContext,
        *,
        category: ReportCategory,
        analysis: WindowAnalysis,
        decision: ExplicitReportDecision,
        route: ResponsibilityRoute,
        subtype: str,
        scope: LocationScope,
        danger: tuple[DangerKind, ...],
    ) -> ReportCreated:
        truncated = len(origin.text) > DESCRIPTION_LIMIT
        payload = ReportCreate(
            house_id=context.house_id,
            category=category,
            description=origin.text[:DESCRIPTION_LIMIT],
            # Происхождение классификации: выбор человека важнее разбора.
            classification_mode=(
                "manual"
                if origin.category is not None
                else "model"
                if analysis.mode == "model"
                else "rules"
            ),
        )
        created = await self.reports.create_in_context(
            session,
            context=context,
            payload=payload,
            idempotency_key=origin.idempotency_key,
            subtype=subtype,
            location_scope=scope,
            danger_kinds=danger,
        )
        await session.execute(
            update(Report)
            .where(Report.id == created.report_id)
            .values(
                analysis=analysis_provenance(analysis, decision, route, text_truncated=truncated)
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
                update(Incident).where(Incident.id == created.incident.id).values(**located)
            )
        return created

    async def _enqueue_card(
        self,
        session: AsyncSession,
        origin: ReportOrigin,
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
            dedupe_key=f"route_card:{origin.card_dedupe_ref}",
        )


def looks_like_no_problem(analysis: WindowAnalysis, decision: ExplicitReportDecision) -> bool:
    """Разбор отнёс реплику к болтовне, вопросу или объявлению — не проблема.

    Правило продукта над типизированным результатом: любая опасность или
    сигнал в Inbox — это проблема; иначе решает роль реплики.
    """
    if decision.emergency.kinds or analysis.semantic_danger:
        return False
    if any(not hit.negated for hit in analysis.danger_hits):
        return False
    if any(signal.disposition == "inbox" for signal in analysis.signals):
        return False
    roles = {line.role for line in analysis.lines if line.line_id == LINE_ID}
    return bool(roles) and roles <= NOT_A_PROBLEM_ROLES


def _form_window(text: str, sent_at: datetime, *, entrance: str | None) -> WindowInput:
    """Окно формы: одна реплика, один автор, подсказка подъезда с сервера."""
    return WindowInput(
        channel="form",
        lines=(WindowLine(line_id=LINE_ID, author_ref=AUTHOR_REF, text=text, sent_at=sent_at),),
        entrance_hint=entrance,
    )


def _analysis_view(
    analysis: WindowAnalysis,
    decision: ExplicitReportDecision,
    danger: tuple[DangerKind, ...],
) -> ReportAnalysisView:
    """Что удалось понять. Пустое поле остаётся пустым: догадок продукт не даёт."""
    return ReportAnalysisView(
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
    )


def _known_scope(value: str) -> LocationScope:
    """Сохранённая территория; незнакомое значение честно становится `unknown`."""
    for scope in LOCATION_SCOPES:
        if scope == value:
            return scope
    return "unknown"


def _known_decision(value: str) -> RouteDecision:
    """Сохранённое решение; незнакомое честно становится `needs_clarification`."""
    if value in {"ticket", "external", "needs_clarification"}:
        return value  # type: ignore[return-value]
    return "needs_clarification"


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


def intake_provenance(analysis: WindowAnalysis) -> dict[str, Any]:
    """Провенанс записи приёма: учёт вызова и версии, без решения и текста."""
    versions = analysis.versions
    return {
        **execution_provenance(analysis),
        "versions": {
            "taxonomy": versions.taxonomy,
            "rules": versions.rules,
            "schema_id": versions.schema_id,
            "prompt": versions.prompt,
            "model": versions.model,
            "input_sha256": versions.input_sha256,
        },
        "dropped_fields": analysis.dropped_fields,
        "recorded_at": datetime.now(UTC).isoformat(),
    }


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
    return {
        **execution_provenance(analysis),
        "classification_mode": "model" if analysis.mode == "model" else "rules",
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
    "DUPLICATE_WINDOW_DAYS",
    "EXTERNAL_ROUTE_TYPES",
    "MAX_DUPLICATES",
    "ClaimedIntake",
    "ExplicitOutcome",
    "ExplicitReportService",
    "ReportOrigin",
    "analysis_provenance",
    "guarded_clean_description",
    "intake_provenance",
    "looks_like_no_problem",
]
