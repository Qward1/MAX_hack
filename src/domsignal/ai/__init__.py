"""AI-ядро ДомСигнала: детерминированный «пол» понимания текста.

Одно ядро разбирает окно реплик — и для пассивного чтения подключённого
домового чата, и для явного пути (форма mini app, `/report`), где окно
состоит из одной реплики.

Ядро отвечает только на вопросы: что, где, когда, какой объект, какой подтип,
происходит ли сейчас, у нас ли, наблюдение ли это, какая предварительная
территория и есть ли признаки опасности. Вопрос «кто отвечает» решает
детерминированный Responsibility Router продукта — здесь нет организаций,
каналов, телефонов, сроков, статусов и текстов для жителя.
"""

from __future__ import annotations

from domsignal.ai.contracts import (
    AuditEvent,
    DangerHit,
    DangerKind,
    EmergencyDecision,
    Evidence,
    ExplicitReportDecision,
    Facet,
    Facets,
    LineRole,
    LineVerdict,
    LocationEvidence,
    LocationScope,
    OpenItem,
    SemanticDanger,
    SignalDraft,
    SignalStrength,
    WindowAnalysis,
    WindowInput,
    WindowLine,
)
from domsignal.ai.engine import audit_sample, decide_explicit_report, decide_strength
from domsignal.ai.facade import WindowAnalyzer
from domsignal.ai.facts import NoNewFactsResult, check_no_new_facts
from domsignal.ai.fusion import fuse_emergency
from domsignal.ai.model_output import SCHEMA_ID, WindowModelOutput, build_json_schema
from domsignal.ai.models import ModelCatalog, ModelProfile, ModelsUnavailable, load_models
from domsignal.ai.prompts import PROMPT_VERSION, build_messages, render_system_prompt
from domsignal.ai.providers.base import (
    AnalysisProvider,
    ProviderBudgetExceeded,
    ProviderCircuitOpen,
    ProviderError,
    ProviderInvalidOutput,
    ProviderOverloaded,
    ProviderRequest,
    ProviderResult,
    ProviderTimeout,
    ProviderUnavailable,
)
from domsignal.ai.providers.openai_compatible import OpenAICompatibleProvider
from domsignal.ai.resilience import (
    BudgetGuard,
    BudgetOutcome,
    CircuitBreaker,
    ConcurrencyLimiter,
    InMemoryBudgetGuard,
    ResilientProvider,
    budget_scope,
)
from domsignal.ai.rules.danger import screen_message_for_danger
from domsignal.ai.rules.lexicon import passes_recall_gate
from domsignal.ai.schema_modes import SCHEMA_MODES, SchemaMode, response_format, strict_schema
from domsignal.ai.taxonomy import Taxonomy, load_taxonomy
from domsignal.ai.windowing import WindowPolicy, build_windows, split_stream

__all__ = [
    "PROMPT_VERSION",
    "SCHEMA_ID",
    "SCHEMA_MODES",
    "AnalysisProvider",
    "AuditEvent",
    "BudgetGuard",
    "BudgetOutcome",
    "CircuitBreaker",
    "ConcurrencyLimiter",
    "DangerHit",
    "DangerKind",
    "EmergencyDecision",
    "Evidence",
    "ExplicitReportDecision",
    "Facet",
    "Facets",
    "InMemoryBudgetGuard",
    "LineRole",
    "LineVerdict",
    "LocationEvidence",
    "LocationScope",
    "ModelCatalog",
    "ModelProfile",
    "ModelsUnavailable",
    "NoNewFactsResult",
    "OpenAICompatibleProvider",
    "OpenItem",
    "ProviderBudgetExceeded",
    "ProviderCircuitOpen",
    "ProviderError",
    "ProviderInvalidOutput",
    "ProviderOverloaded",
    "ProviderRequest",
    "ProviderResult",
    "ProviderTimeout",
    "ProviderUnavailable",
    "ResilientProvider",
    "SchemaMode",
    "SemanticDanger",
    "SignalDraft",
    "SignalStrength",
    "Taxonomy",
    "WindowAnalysis",
    "WindowAnalyzer",
    "WindowInput",
    "WindowLine",
    "WindowModelOutput",
    "WindowPolicy",
    "audit_sample",
    "budget_scope",
    "build_json_schema",
    "build_messages",
    "build_windows",
    "check_no_new_facts",
    "decide_explicit_report",
    "decide_strength",
    "fuse_emergency",
    "load_models",
    "load_taxonomy",
    "passes_recall_gate",
    "render_system_prompt",
    "response_format",
    "screen_message_for_danger",
    "split_stream",
    "strict_schema",
]
