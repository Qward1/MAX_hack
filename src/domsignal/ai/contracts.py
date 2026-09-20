"""Внутренний контракт AI-ядра: вход окна и типизированный результат анализа.

Ядро отвечает только на вопросы «что», «где», «когда», «какой объект»,
«какой подтип», «сейчас ли», «у нас ли», «наблюдение ли это», «какая
предварительная территория» и «есть ли опасность». Вопрос «кто отвечает»
решает детерминированный Responsibility Router продукта, поэтому здесь нет
организаций, каналов, телефонов, ссылок, сроков, статусов, уверенности и
текстов для жителя.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from domsignal.core.incidents import ReportCategory

Channel = Literal["group_passive", "group_report", "form"]
OpenItemKind = Literal["signal", "incident"]
LineRole = Literal[
    "new_problem",
    "me_too",
    "more_info",
    "objection",
    "status_question",
    "resolved_claim",
    "announcement",
    "discussion",
    "chatter",
    "out_of_scope",
]
LinkCertainty = Literal["sure", "unsure"]
LocationScope = Literal[
    "apartment",
    "house_common",
    "house_territory",
    "municipal_territory",
    "external_network",
    "other_building",
    "unknown",
]
FacetValue = Literal["yes", "no", "unclear"]
DangerKind = Literal[
    "gas",
    "smoke_fire",
    "electric",
    "person_trapped",
    "flooding",
    "structural",
    "other_hazard",
]
RefutationReason = Literal["past", "resolved", "other_place", "explicit_negation", "not_literal"]
EmergencySource = Literal["rules", "semantic"]
SignalStrength = Literal["critical", "strong", "medium", "weak", "filtered"]
Disposition = Literal["inbox", "audit_pool"]
SignalSource = Literal["rules", "model", "rules+model"]
AnalysisMode = Literal["model", "rules", "manual"]
ExecutionState = Literal[
    "ok",
    "disabled",
    "fallback_timeout",
    "fallback_provider_error",
    "fallback_invalid_output",
    "fallback_budget",
    "fallback_circuit_open",
    "fallback_overloaded",
    "error_rules",
]
AuditEventKind = Literal[
    "emergency_downgraded",
    "refutation_rejected",
    "evidence_unverified",
    "no_new_facts_violation",
    "model_missing_line",
    "field_dropped",
]

ROLES: tuple[LineRole, ...] = (
    "new_problem",
    "me_too",
    "more_info",
    "objection",
    "status_question",
    "resolved_claim",
    "announcement",
    "discussion",
    "chatter",
    "out_of_scope",
)
LOCATION_SCOPES: tuple[LocationScope, ...] = (
    "apartment",
    "house_common",
    "house_territory",
    "municipal_territory",
    "external_network",
    "other_building",
    "unknown",
)
DANGER_KINDS: tuple[DangerKind, ...] = (
    "gas",
    "smoke_fire",
    "electric",
    "person_trapped",
    "flooding",
    "structural",
    "other_hazard",
)
REFUTATION_REASONS: tuple[RefutationReason, ...] = (
    "past",
    "resolved",
    "other_place",
    "explicit_negation",
    "not_literal",
)
FACET_VALUES: tuple[FacetValue, ...] = ("yes", "no", "unclear")


class Frozen(BaseModel):
    """Неизменяемая модель без неизвестных полей."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- вход


class WindowLine(Frozen):
    """Одна реплика окна. Идентификаторы непрозрачны для AI-ядра."""

    line_id: str = Field(min_length=1, max_length=128)
    author_ref: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)
    sent_at: AwareDatetime
    reply_to: str | None = None
    is_context: bool = False


class OpenItem(Frozen):
    """Открытый сигнал или заявка дома, к которым окно может относиться."""

    ref: str = Field(min_length=1, max_length=128)
    kind: OpenItemKind
    category: ReportCategory
    subtype: str | None = None
    entrance: str | None = None
    title: str = Field(max_length=200)


class WindowInput(Frozen):
    """Окно реплик. Одиночное сообщение — окно из одной реплики."""

    channel: Channel
    lines: tuple[WindowLine, ...] = Field(min_length=1, max_length=40)
    open_items: tuple[OpenItem, ...] = Field(default=(), max_length=10)
    entrance_hint: str | None = None

    @model_validator(mode="after")
    def _check_lines(self) -> WindowInput:
        if not any(not line.is_context for line in self.lines):
            raise ValueError("window needs at least one non-context line")
        line_ids = [line.line_id for line in self.lines]
        if len(set(line_ids)) != len(line_ids):
            raise ValueError("line_id values must be unique inside a window")
        refs = [item.ref for item in self.open_items]
        if len(set(refs)) != len(refs):
            raise ValueError("open item refs must be unique inside a window")
        return self


# -------------------------------------------------------------------------- выход


class Evidence(Frozen):
    """Значение поля вместе с дословной цитатой из конкретной реплики."""

    value: str
    quote: str
    line_id: str


class LocationEvidence(Frozen):
    """Предварительная территория. Без цитаты допустимо только `unknown`."""

    value: LocationScope
    quote: str | None = None
    line_id: str | None = None

    @model_validator(mode="after")
    def _check_quote(self) -> LocationEvidence:
        if self.value != "unknown" and not self.quote:
            raise ValueError("location scope other than unknown requires a quote")
        return self


class Facet(Frozen):
    """Признак `current`, `local` или `observed`."""

    value: FacetValue
    quote: str | None = None
    line_id: str | None = None


class Facets(Frozen):
    current: Facet
    local: Facet
    observed: Facet


class DangerHit(Frozen):
    """Срабатывание детерминированных правил опасности, включая отменённые."""

    kind: DangerKind
    line_id: str
    quote: str
    negated: bool = False
    displaced: bool = False
    source: Literal["rules"] = "rules"


class SemanticEvidence(Frozen):
    line_id: str
    quote: str
    quote_valid: bool


class SemanticDanger(Frozen):
    """Опасность, найденная моделью в том же вызове разбора окна."""

    kind: DangerKind
    evidence: tuple[SemanticEvidence, ...] = ()
    contextual: bool = False
    source: Literal["model"] = "model"


class EmergencyDecision(Frozen):
    """Результат Emergency Fusion: правила ИЛИ семантика, без голосования."""

    is_emergency: bool
    sources: tuple[EmergencySource, ...] = ()
    kinds: tuple[DangerKind, ...] = ()
    memo_allowed: bool = False
    downgraded: bool = False
    downgrade_reason: RefutationReason | None = None
    evidence_unverified: bool = False


class TextBlock(Frozen):
    """Текст модели со ссылками на реплики-источники (после guard)."""

    text: str
    source_line_ids: tuple[str, ...] = ()


class SignalDraft(Frozen):
    """Сигнал: что, где, когда и насколько это похоже на проблему дома."""

    ref: str
    subtype: str
    product_category: ReportCategory
    object_label: str
    entrance: Evidence | None = None
    floor: Evidence | None = None
    since: Evidence | None = None
    location_scope: LocationEvidence
    facets: Facets
    emergency: EmergencyDecision
    strength: SignalStrength
    strength_reason: str
    disposition: Disposition
    audit_sample: bool = False
    line_ids: tuple[str, ...] = ()
    source: SignalSource = "rules"
    flags: tuple[str, ...] = ()
    clean_description: TextBlock | None = None
    summary: TextBlock | None = None


class LineVerdict(Frozen):
    line_id: str
    role: LineRole
    signal_refs: tuple[str, ...] = ()
    link_certainty: LinkCertainty | None = None


class AuditEvent(Frozen):
    kind: AuditEventKind
    signal_ref: str | None = None
    details: str = ""


class ExecutionInfo(Frozen):
    state: ExecutionState
    latency_ms: int = 0
    provider_called: bool = False


class Versions(Frozen):
    """Версии артефактов анализа.

    Поле схемы называется `schema_id`, а не `schema`: имя `schema` затеняет
    устаревший метод `BaseModel.schema` и pydantic предупреждает об этом.
    """

    taxonomy: str
    rules: str
    schema_id: str
    input_sha256: str
    prompt: str | None = None
    model: str | None = None


class WindowAnalysis(Frozen):
    """Типизированный результат разбора окна. Продукт применяет его сам."""

    mode: AnalysisMode
    execution: ExecutionInfo
    versions: Versions
    lines: tuple[LineVerdict, ...] = ()
    signals: tuple[SignalDraft, ...] = ()
    danger_hits: tuple[DangerHit, ...] = ()
    semantic_danger: tuple[SemanticDanger, ...] = ()
    audit_events: tuple[AuditEvent, ...] = ()
    dropped_fields: int = 0


class ExplicitReportDecision(Frozen):
    """Помощник явного пути: форма mini app и `/report`."""

    product_category: ReportCategory
    subtype: str | None
    location_scope: LocationScope
    analysis_mode: AnalysisMode
    confident: bool
    reason: str
    entrance: Evidence | None = None
    floor: Evidence | None = None
    since: Evidence | None = None
    emergency: EmergencyDecision
