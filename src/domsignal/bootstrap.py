from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from domsignal.ai import (
    CircuitBreaker,
    ConcurrencyLimiter,
    ModelProfile,
    ModelsUnavailable,
    OpenAICompatibleProvider,
    ResilientProvider,
    WindowAnalyzer,
    load_models,
)
from domsignal.ai.schema_modes import SchemaMode
from domsignal.bot.chat_provider import HttpMaxChatProvider
from domsignal.bot.ingress import InboundService
from domsignal.bot.messaging import HttpMaxMessagingProvider
from domsignal.bot.transport import MaxTransport, OffTransport, RecordingTransport
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.action_cards import ActionCardBuilder
from domsignal.services.ai_budget import PostgresBudgetGuard
from domsignal.services.appeal_drafts import AppealDraftService
from domsignal.services.chat_connections import ChatConnectionService
from domsignal.services.company_signup import notify_digest
from domsignal.services.explicit_reports import ExplicitReportService
from domsignal.services.group_messages import MaxWebhookService
from domsignal.services.membership import MembershipService
from domsignal.services.notifications import TicketNotificationHandler
from domsignal.services.passive_analysis import PassiveWindowAnalysis
from domsignal.services.passive_capture import PassiveCaptureService
from domsignal.services.personal_bot import PersonalBotService
from domsignal.services.reports import DemoRule, ReportService
from domsignal.services.resident_access import ResidentAccessService
from domsignal.services.routing import RoutingService, load_directory_or_none
from domsignal.services.sessions import SessionService
from domsignal.services.signal_inbox import SignalInboxService
from domsignal.services.signals import PassiveConfig, SignalEngine
from domsignal.services.tickets import TicketService
from domsignal.settings import LlmProvider, MaxTransportMode, Settings
from domsignal.worker.handlers import WorkerHandlers

logger = logging.getLogger(__name__)

#: Запас к таймауту провайдера: фасад обрывает вызов чуть позже самого клиента.
ANALYZER_TIMEOUT_MARGIN_SECONDS = 2.0
#: Таймаут модели без профиля и без `LLM_TIMEOUT_SECONDS` (прежнее значение настроек).
DEFAULT_LLM_TIMEOUT_SECONDS = 10.0


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    session_service: SessionService
    membership_service: MembershipService
    report_service: ReportService
    ticket_service: TicketService
    inbound_service: InboundService
    transport: MaxTransport
    worker_handlers: WorkerHandlers
    chat_connections: ChatConnectionService
    max_webhook: MaxWebhookService
    notifications: TicketNotificationHandler
    routing: RoutingService
    action_cards: ActionCardBuilder
    analyzer: WindowAnalyzer
    rules_analyzer: WindowAnalyzer
    explicit_reports: ExplicitReportService
    appeal_drafts: AppealDraftService
    signals: SignalEngine
    passive: PassiveCaptureService
    passive_analysis: PassiveWindowAnalysis
    signal_inbox: SignalInboxService
    resident_access: ResidentAccessService
    personal_bot: PersonalBotService
    ai_budget: PostgresBudgetGuard | None = None
    ai_provider: OpenAICompatibleProvider | None = field(default=None, repr=False)
    #: Таймаут одного вызова модели; `None` — модель не подключена.
    ai_timeout_seconds: float | None = None

    @property
    def ai_analysis_enabled(self) -> bool:
        """Есть ли внешний провайдер разбора. Правила работают всегда.

        Процесс без ключа (api) узнаёт о провайдере AI-пула из
        `AI_POOL_LLM_PROVIDER`: модель вызывает только ai-worker.
        """
        return (
            self.ai_provider is not None
            or self.settings.ai_pool_llm_provider is LlmProvider.OPENAI_COMPATIBLE
        )

    @property
    def passive_ai_analysis_enabled(self) -> bool:
        """Разбирает ли модель окна пассивного чтения (`PASSIVE_LLM_ENABLED`)."""
        return self.ai_analysis_enabled and self.settings.passive_llm_enabled

    @property
    def routes_enabled(self) -> bool:
        """Справочник региона загружен и роутер собран."""
        return self.routing.available

    @property
    def appeals_enabled(self) -> bool:
        """Черновики обращений доступны: их каркас берётся из того же справочника."""
        return self.routing.available

    async def aclose(self) -> None:
        """Закрыть HTTP-клиент провайдера и пул соединений с БД."""
        if self.ai_provider is not None:
            await self.ai_provider.aclose()
        await self.engine.dispose()


@dataclass(frozen=True)
class AiComposition:
    """Собранный слой анализа: с моделью или только правила."""

    analyzer: WindowAnalyzer
    rules_analyzer: WindowAnalyzer
    budget: PostgresBudgetGuard | None = None
    provider: OpenAICompatibleProvider | None = None
    timeout_seconds: float | None = None


def _profile(settings: Settings) -> ModelProfile | None:
    """Профиль выбранной модели из ресурса отбора; его отсутствие не фатально."""
    try:
        catalog = load_models()
    except ModelsUnavailable as exc:
        logger.warning("ai_model_profile_unavailable", extra={"error_type": type(exc).__name__})
        return None
    return catalog.get(settings.llm_model) or catalog.default


def build_ai(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> AiComposition:
    """Собрать анализатор из настроек и профиля модели.

    Таймаут берётся из профиля модели: он измерен по p99 конкретной модели.
    `LLM_TIMEOUT_SECONDS` переопределяет его только когда задан непустым
    значением; пустое значение в Compose означает «не задан» (P6b).
    """
    rules_only = WindowAnalyzer()
    if settings.llm_provider is not LlmProvider.OPENAI_COMPATIBLE:
        return AiComposition(analyzer=rules_only, rules_analyzer=WindowAnalyzer())
    assert settings.llm_api_key and settings.llm_model  # проверено в Settings
    profile = _profile(settings)
    explicit = settings.model_fields_set
    if settings.llm_timeout_seconds is not None:
        timeout = settings.llm_timeout_seconds
    elif profile is not None:
        timeout = profile.timeout_seconds
    else:
        timeout = DEFAULT_LLM_TIMEOUT_SECONDS
    schema_mode: SchemaMode = (
        settings.llm_schema_mode.value
        if profile is None or "llm_schema_mode" in explicit
        else profile.schema_mode
    )
    max_tokens = (
        settings.llm_max_tokens
        if profile is None or "llm_max_tokens" in explicit
        else profile.max_tokens
    )
    provider = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        schema_mode=schema_mode,
        timeout_seconds=timeout,
        max_tokens=max_tokens,
        temperature=profile.temperature if profile else 0.0,
        extra_body=profile.extra_body if profile else None,
        open_danger_extra_body=profile.open_danger_extra_body if profile else None,
    )
    budget = PostgresBudgetGuard(
        session_factory,
        daily_calls=settings.llm_daily_call_budget,
        chat_share=settings.llm_chat_daily_share,
    )
    analyzer = WindowAnalyzer(
        ResilientProvider(
            provider,
            breaker=CircuitBreaker(),
            limiter=ConcurrencyLimiter(settings.llm_max_concurrency),
            budget=budget,
        ),
        timeout_s=timeout + ANALYZER_TIMEOUT_MARGIN_SECONDS,
    )
    logger.info(
        "ai_provider_composed",
        extra={
            "ai_model": settings.llm_model,
            "ai_schema_mode": schema_mode,
            "ai_timeout_seconds": timeout,
            "ai_profile": profile.id if profile else None,
        },
    )
    return AiComposition(
        analyzer=analyzer,
        rules_analyzer=rules_only,
        budget=budget,
        provider=provider,
        timeout_seconds=timeout,
    )


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    transport: MaxTransport
    if settings.max_transport is MaxTransportMode.RECORDING:
        transport = RecordingTransport()
    else:
        # Live MAX HTTP transport is deliberately not part of FND-01.
        transport = OffTransport()
    # Справочник проверяется один раз на старте; ошибка данных оставляет все
    # маршруты unknown и не меняет готовность приложения.
    routing = RoutingService(load_directory_or_none(Path(settings.regions_dir)))
    action_cards = ActionCardBuilder(routing)
    report_service = ReportService(
        demo_rule=DemoRule(
            source_url="https://example.invalid/domsignal-demo-source",
            source_title="Демонстрационный пакет ДомСигнала",
            verification_status="demo",
            note="Правило не проверено; нормативный срок не рассчитан.",
        ),
        routing=routing,
        action_cards=action_cards,
    )
    chat_provider = HttpMaxChatProvider(
        base_url=settings.max_api_base_url,
        # Off/recording must never cause outbound MAX calls, even if a token is present.
        token=settings.max_bot_token
        if settings.max_transport == MaxTransportMode.WEBHOOK
        else None,
        timeout=settings.max_api_timeout_seconds,
    )
    chat_connections = ChatConnectionService(
        chat_provider,
        ttl_seconds=settings.chat_connection_ttl_seconds,
        required_permissions=settings.max_required_permissions,
    )
    ticket_service = TicketService()
    messaging = HttpMaxMessagingProvider(
        chat_provider.client, bot_username=settings.max_bot_username
    )
    webhook_mode = settings.max_transport == MaxTransportMode.WEBHOOK
    notifications = TicketNotificationHandler(
        session_factory=session_factory,
        tickets=ticket_service,
        provider=messaging,
        enabled=webhook_mode,
        public_base_url=settings.public_base_url,
        display_timezone=settings.display_timezone,
    )
    # Житель = участник домового чата (RESIDENT-BY-CHAT-2026-09-25): события
    # MAX и точечная проверка участия; открытый доступ к дому.
    resident_access = ResidentAccessService(
        session_factory=session_factory,
        connections=chat_connections,
        check_all_max_chats=settings.resident_check_all_max_chats,
        check_interval_seconds=settings.resident_check_interval_seconds,
        membership_ttl_seconds=settings.resident_membership_ttl_seconds,
    )
    ai = build_ai(settings, session_factory)
    explicit_reports = ExplicitReportService(
        session_factory=session_factory,
        chat_connections=chat_connections,
        reports=report_service,
        routing=routing,
        action_cards=action_cards,
        analyzer=ai.analyzer,
        rules_analyzer=ai.rules_analyzer,
        budget=ai.budget,
        resident_access=resident_access,
        hold_seconds=settings.bot_hold_seconds,
    )
    personal_bot = PersonalBotService(
        session_factory=session_factory,
        resident_access=resident_access,
        explicit_reports=explicit_reports,
        reports=report_service,
        notifications=notifications,
        rules_analyzer=ai.rules_analyzer,
        routing=routing,
        answer_enabled=webhook_mode,
        build_commit=settings.build_commit,
        bot_username=settings.max_bot_username,
        daily_limit=settings.bot_daily_report_limit,
        hold_seconds=settings.bot_hold_seconds,
        application_digest=lambda code: notify_digest(settings, code),
    )
    appeal_drafts = AppealDraftService(routing=routing)
    # Пассивное чтение чата: приём и окна в операционном контуре, разбор окна —
    # тем же анализатором, что и явный путь, в AI-пуле.
    signals = SignalEngine(routing, PassiveConfig.from_settings(settings))
    passive = PassiveCaptureService(
        session_factory=session_factory,
        connections=chat_connections,
        engine=signals,
    )
    # Выключатель модели пассивного режима (P6-DECISION): окна идут в правила,
    # бюджет модели не списывается; явный путь сохраняет модель.
    passive_llm = settings.passive_llm_enabled
    if not passive_llm and ai.provider is not None:
        logger.info("passive_llm_disabled", extra={"ai_model": settings.llm_model})
    passive_analysis = PassiveWindowAnalysis(
        session_factory=session_factory,
        engine=signals,
        analyzer=ai.analyzer if passive_llm else ai.rules_analyzer,
        budget=ai.budget if passive_llm else None,
        rules_analyzer=ai.rules_analyzer,
    )
    worker_handlers = WorkerHandlers(
        session_factory=session_factory,
        report_service=report_service,
        transport=transport,
        chat_connections=chat_connections,
        notifications=notifications,
        explicit_reports=explicit_reports,
        passive=passive,
        passive_analysis=passive_analysis,
        personal_bot=personal_bot,
        resident_access=resident_access,
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        session_service=SessionService(
            secret=settings.session_secret,
            ttl_seconds=settings.session_ttl_seconds,
        ),
        membership_service=MembershipService(),
        report_service=report_service,
        inbound_service=InboundService(),
        ticket_service=ticket_service,
        transport=transport,
        worker_handlers=worker_handlers,
        chat_connections=chat_connections,
        max_webhook=MaxWebhookService(
            chat_connections, passive, resident_access=resident_access, bot=personal_bot
        ),
        notifications=notifications,
        routing=routing,
        action_cards=action_cards,
        analyzer=ai.analyzer,
        rules_analyzer=ai.rules_analyzer,
        explicit_reports=explicit_reports,
        appeal_drafts=appeal_drafts,
        signals=signals,
        passive=passive,
        passive_analysis=passive_analysis,
        signal_inbox=SignalInboxService(
            routing=routing, action_cards=action_cards, reports=report_service
        ),
        resident_access=resident_access,
        personal_bot=personal_bot,
        ai_budget=ai.budget,
        ai_provider=ai.provider,
        ai_timeout_seconds=ai.timeout_seconds,
    )
