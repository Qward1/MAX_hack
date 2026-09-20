"""Отбор моделей P2 на синтетических окнах.

    uv run python evaluation/select_models.py --out evaluation/reports/

Что делает скрипт: прогоняет кандидатов из `evaluation/candidates.v1.yaml`
через готовое ядро (`WindowAnalyzer` + адаптер polza.ai), считает долю
валидных ответов, задержки, токены и рубли, затем берёт лучших на
стратифицированной выборке и записывает выбранную модель с резервами в
`src/domsignal/ai/resources/models.v1.yaml`.

**Жёсткие правила.**

1. Во внешний API уходят только строки наборов `datasets/synthetic/*` с
   `synthetic: true`. Путь в `data/` и строка без пометки останавливают
   прогон (`evaluation.guard`).
2. Общий лимит прогона — не более 300 вызовов и 500 ₽. При приближении
   скрипт останавливается и пишет отчёт с уже полученными числами.
3. Числа отбора — **синтетика**. Это не оценка качества на реальных
   сообщениях жителей; решение о включении LLM принимается в P6 на данных D2.

Без ключа (`LLM_API_KEY`) скрипт не обращается в сеть: он собирает окна,
проверяет их сторожем данных и пишет отчёт с пометкой NOT RUN.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import pathlib
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

if __package__ in (None, ""):  # запуск файлом, а не модулем
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml  # type: ignore[import-untyped]  # noqa: E402

from domsignal.ai import WindowAnalyzer  # noqa: E402
from domsignal.ai.contracts import Channel, WindowAnalysis, WindowInput, WindowLine  # noqa: E402
from domsignal.ai.model_output import WindowModelOutput  # noqa: E402
from domsignal.ai.normalize import contains_quote  # noqa: E402
from domsignal.ai.providers.base import ProviderRequest, ProviderResult  # noqa: E402
from domsignal.ai.providers.openai_compatible import (  # noqa: E402
    DEFAULT_BASE_URL,
    OpenAICompatibleProvider,
)
from domsignal.ai.schema_modes import SCHEMA_MODES, SchemaMode  # noqa: E402
from domsignal.ai.taxonomy import load_taxonomy  # noqa: E402
from evaluation.guard import DataGuardError, load_allowed_jsonl  # noqa: E402
from evaluation.metrics import BASE_TIME, DATASETS, predict  # noqa: E402

CANDIDATES_FILE = pathlib.Path("evaluation/candidates.v1.yaml")
MODELS_FILE = pathlib.Path("src/domsignal/ai/resources/models.v1.yaml")

MAX_CALLS = 300
MAX_RUB = 500.0
#: Доля лимита, после которой прогон считается «на подходе к границе».
STOP_MARGIN = 0.95

WARNING = (
    "**СИНТЕТИКА — ЭТО НЕ ОЦЕНКА КАЧЕСТВА НА РЕАЛЬНЫХ СООБЩЕНИЯХ.** Окна "
    "написаны той же командой, что и правила; реальных реплик жителей здесь "
    "нет и быть не может. Числа годятся для инженерного выбора модели и "
    "режима схемы, но не для утверждения, что система работает на живых "
    "домовых чатах. Решение о включении LLM-слоя принимается в P6 на данных "
    "D2/D3."
)

#: Инженерное правило выбора (задание P2 §3.6.4).
RULE_VALID_JSON = 0.98
RULE_FABRICATED_QUOTES = 0.02
RULE_CONTEXTUAL_HITS = 4
RULE_P95_SECONDS = 10.0
RULE_QUALITY_MARGIN = 0.03

#: Что именно этот прогон не измеряет. Печатается в отчёт как есть.
LIMITATIONS = (
    "Окна собраны из тех же синтетических наборов, по которым писались правила. "
    "Числа годятся для сравнения моделей между собой и для выбора режима схемы, "
    "но не переносятся на реальные домовые чаты.",
    "Этап 2 частично пересекается с этапом 1 по строкам набора территории "
    "(`sd01`, `sd02`, `sd05`): это одна и та же выборка, а не независимая проверка.",
    "Условия обработки данных вышестоящими провайдерами отдельно не открывались. "
    "Основание допуска модели — страница polza.ai «Конфиденциальность» и поля "
    "каталога моделей; для пилота нужен отдельный gate выбора провайдера.",
    "Режим схемы понижается только на первом окне кандидата: колонка «Окон» "
    "считает окна, а не вызовы, поэтому лишние вызовы понижения в неё не входят "
    "(поле `calls` в JSON).",
    "Резервов может оказаться меньше двух: в резервы попадают только кандидаты, "
    "прошедшие правило на этапе 2. Третий резерв потребовал бы отдельного "
    "прогона кандидатов, отсеянных на этапе 1.",
    "`max_tokens` одинаков для всех кандидатов. У моделей с внутренними "
    "рассуждениями рассуждения расходуют тот же лимит, поэтому часть отказов "
    "может быть обрезкой ответа, а не неумением следовать схеме.",
)


# --------------------------------------------------------------------- вход


@dataclass(frozen=True)
class Candidate:
    """Модель-кандидат вместе с основанием политики обработки данных."""

    id: str
    label: str
    upstream: str
    schema_mode: SchemaMode
    max_tokens: int
    timeout_seconds: float
    temperature: float | None
    extra_body: dict[str, Any]
    price_in_per_million: float
    price_out_per_million: float
    stores_data_in_russia: bool
    policy_basis: str
    policy_checked_at: str


@dataclass(frozen=True)
class EvalWindow:
    """Окно оценки с эталоном. Тексты берутся только из синтетических наборов."""

    id: str
    texts: tuple[str, ...]
    stratum: str = "-"
    channel: Channel = "group_passive"
    authors: tuple[str, ...] = ()
    expected_role: str | None = None
    expected_subtype: str | None = None
    expected_scope: str | None = None
    is_problem: bool = False
    expected_emergency: bool = False
    expected_semantic_danger: str | None = None
    expected_refuted: bool = False

    def to_input(self) -> WindowInput:
        authors = self.authors or tuple(f"resident-{index}" for index in range(len(self.texts)))
        lines = tuple(
            WindowLine(
                line_id=f"{self.id}-{index}",
                author_ref=authors[index],
                text=text,
                sent_at=BASE_TIME + timedelta(seconds=40 * index),
            )
            for index, text in enumerate(self.texts)
        )
        return WindowInput(channel=self.channel, lines=lines)


def load_dataset(path: pathlib.Path) -> list[dict[str, Any]]:
    """Набор читается только через сторожа данных (`evaluation.guard`)."""
    return load_allowed_jsonl(path)


def load_candidates(path: pathlib.Path = CANDIDATES_FILE) -> list[Candidate]:
    document = cast(dict[str, Any], yaml.safe_load(path.read_text(encoding="utf-8")))
    candidates: list[Candidate] = []
    for raw in document["candidates"]:
        entry = cast(dict[str, Any], raw)
        mode = entry.get("schema_mode", "json_schema_strict")
        if mode not in SCHEMA_MODES:
            raise ValueError(f"{entry['id']}: неизвестный режим схемы {mode!r}")
        candidates.append(
            Candidate(
                id=str(entry["id"]),
                label=str(entry.get("label", entry["id"])),
                upstream=str(entry.get("upstream", "")),
                schema_mode=cast(SchemaMode, mode),
                max_tokens=int(entry.get("max_tokens", 1600)),
                timeout_seconds=float(entry.get("timeout_seconds", 25)),
                temperature=entry.get("temperature"),
                extra_body=dict(entry.get("extra_body") or {}),
                price_in_per_million=float(entry.get("price_in_per_million", 0.0)),
                price_out_per_million=float(entry.get("price_out_per_million", 0.0)),
                stores_data_in_russia=bool(entry.get("stores_data_in_russia", False)),
                policy_basis=" ".join(str(entry["policy_basis"]).split()),
                policy_checked_at=str(entry["policy_checked_at"]),
            )
        )
    if len(candidates) > 6:
        raise ValueError("в отбор допускается не более 6 кандидатов")
    return candidates


# ------------------------------------------------------------------- окна


def guard_windows(windows: list[EvalWindow], allowed_texts: set[str]) -> None:
    """Последняя проверка: каждая реплика окна пришла из разрешённого набора."""
    unknown = [
        window.id for window in windows if any(text not in allowed_texts for text in window.texts)
    ]
    if unknown:
        raise DataGuardError(
            "во внешний вызов попали окна с текстами не из синтетического набора: "
            + ", ".join(unknown[:5])
        )


def _scope_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == "message"]


def _scope_windows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == "window"]


def build_stage1_windows(datasets: dict[str, list[dict[str, Any]]]) -> list[EvalWindow]:
    """20 фиксированных окон: контекстная опасность, отрицания, внешние места, поток."""
    windows: list[EvalWindow] = []
    for row in _scope_windows(datasets["scope"])[:5]:
        windows.append(
            EvalWindow(
                id=str(row["id"]),
                texts=tuple(item["text"] for item in row["lines"]),
                authors=tuple(f"resident-{item['author']}" for item in row["lines"]),
                stratum="contextual_danger",
                expected_semantic_danger=str(row["expected_semantic_danger"]),
                expected_emergency=True,
            )
        )
    negations = [row for row in datasets["singles"] if row.get("slice") == "negation"][:5]
    windows.extend(_single_window(row, "negation") for row in negations)

    external = [
        row
        for row in _scope_rows(datasets["scope"])
        if row.get("location_scope")
        in ("municipal_territory", "external_network", "other_building")
    ][:5]
    windows.extend(_single_window(row, "external_scope") for row in external)

    windows.extend(_stream_windows(datasets["stream"], limit=5, stratum="stream"))
    return windows


def build_stage2_windows(
    datasets: dict[str, list[dict[str, Any]]], *, limit: int = 60
) -> list[EvalWindow]:
    """Стратифицированная выборка: типичное, перефразы, шум, опасность и места."""
    taken: list[EvalWindow] = []
    singles = datasets["singles"]
    plan = {
        "typical": 14,
        "paraphrase": 7,
        "noisy": 6,
        "emergency": 6,
        "negation": 3,
        "status": 3,
        "resolved": 3,
        "chatter": 3,
        "out_of_scope": 3,
        "announcement": 2,
        "multi": 2,
    }
    for slice_name, count in plan.items():
        rows = [row for row in singles if row.get("slice") == slice_name][:count]
        taken.extend(_single_window(row, slice_name) for row in rows)
    scope_rows = _scope_rows(datasets["scope"])[:5]
    taken.extend(_single_window(row, "location_scope") for row in scope_rows)
    taken.extend(_stream_windows(datasets["stream"], limit=3, stratum="stream", skip=5))
    return taken[:limit]


def _single_window(row: dict[str, Any], stratum: str) -> EvalWindow:
    return EvalWindow(
        id=str(row["id"]),
        texts=(str(row["text"]),),
        stratum=stratum,
        channel="group_report",
        expected_role=str(row["role"]),
        expected_subtype=row.get("subtype"),
        expected_scope=row.get("location_scope"),
        is_problem=row["role"] == "new_problem",
        expected_emergency=bool(row.get("emergency")),
    )


def _stream_windows(
    rows: list[dict[str, Any]], *, limit: int, stratum: str, skip: int = 0
) -> list[EvalWindow]:
    """Окна потока E0c по нарезке ядра, взятые подряд после `skip`."""
    from domsignal.ai.windowing import build_windows

    lines = [
        WindowLine(
            line_id=str(row["id"]),
            author_ref=f"resident-{row['author']}",
            text=str(row["text"]),
            sent_at=BASE_TIME + timedelta(minutes=int(row["minute"])),
            reply_to=row.get("reply_to"),
        )
        for row in rows
    ]
    built = build_windows(lines, channel="group_passive")[skip : skip + limit]
    return [
        EvalWindow(
            id=f"stream-{index + skip + 1}",
            texts=tuple(line.text for line in window.lines),
            authors=tuple(line.author_ref for line in window.lines),
            stratum=stratum,
            channel="group_passive",
        )
        for index, window in enumerate(built)
    ]


# ----------------------------------------------------------------- бюджет


@dataclass
class RunBudget:
    """Жёсткий общий лимит прогона: вызовы и рубли."""

    max_calls: int = MAX_CALLS
    max_rub: float = MAX_RUB
    calls: int = 0
    spent_rub: float = 0.0
    stop_reason: str | None = None
    approaching: str | None = None

    def allow(self) -> bool:
        """Можно ли делать ещё один вызов. Граница жёсткая, а не «примерно»."""
        if self.calls >= self.max_calls:
            self.stop_reason = f"исчерпан лимит вызовов ({self.calls}/{self.max_calls})"
            return False
        if self.spent_rub >= self.max_rub:
            self.stop_reason = (
                f"исчерпан денежный лимит ({self.spent_rub:.2f}/{self.max_rub} ₽)"
            )
            return False
        if (
            self.calls >= self.max_calls * STOP_MARGIN
            or self.spent_rub >= self.max_rub * STOP_MARGIN
        ):
            self.approaching = (
                f"израсходовано {self.calls}/{self.max_calls} вызовов и "
                f"{self.spent_rub:.2f}/{self.max_rub:.0f} ₽"
            )
        return True

    def record(self, cost_rub: float | None) -> None:
        self.calls += 1
        self.spent_rub += cost_rub or 0.0


# ---------------------------------------------------------------- прогон


@dataclass
class Recorder:
    """Провайдер-обёртка: запоминает сырой ответ, чтобы считать выдуманные цитаты."""

    inner: OpenAICompatibleProvider
    last: ProviderResult | None = None

    @property
    def prompt_version(self) -> str | None:
        return self.inner.prompt_version

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        self.last = None
        result = await self.inner.analyze_window(request)
        self.last = result
        return result


@dataclass
class WindowOutcome:
    window_id: str
    stratum: str
    state: str
    latency_ms: int
    tokens_in: int | None
    tokens_out: int | None
    cost_rub: float | None
    quotes_total: int = 0
    quotes_fabricated: int = 0
    dropped_fields: int = 0
    no_new_facts: int = 0
    role_ok: bool | None = None
    subtype_ok: bool | None = None
    scope_ok: bool | None = None
    missed_problem: bool = False
    false_problem: bool = False
    danger_found: bool | None = None
    refutation_ok: bool | None = None
    rules_agree: bool | None = None


@dataclass
class StageResult:
    stage: str
    candidate: str
    schema_mode: str
    windows: int = 0
    calls: int = 0
    valid: int = 0
    states: dict[str, int] = field(default_factory=dict)
    latencies_ms: list[int] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_rub: float = 0.0
    outcomes: list[WindowOutcome] = field(default_factory=list)
    stopped: str | None = None

    # ------------------------------------------------------------- сводка

    @property
    def valid_share(self) -> float:
        return self.valid / self.windows if self.windows else 0.0

    @property
    def p50_ms(self) -> int:
        return int(statistics.median(self.latencies_ms)) if self.latencies_ms else 0

    @property
    def p95_ms(self) -> int:
        if not self.latencies_ms:
            return 0
        ordered = sorted(self.latencies_ms)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]

    @property
    def cost_per_window(self) -> float:
        return self.cost_rub / self.windows if self.windows else 0.0

    @property
    def quotes_total(self) -> int:
        return sum(item.quotes_total for item in self.outcomes)

    @property
    def quotes_fabricated(self) -> int:
        return sum(item.quotes_fabricated for item in self.outcomes)

    @property
    def fabricated_share(self) -> float:
        total = self.quotes_total
        return self.quotes_fabricated / total if total else 0.0

    @property
    def contextual_hits(self) -> int:
        return sum(1 for item in self.outcomes if item.danger_found)

    def _share(self, name: str) -> tuple[int, int]:
        values = [getattr(item, name) for item in self.outcomes]
        applicable = [value for value in values if value is not None]
        return sum(1 for value in applicable if value), len(applicable)

    @property
    def quality(self) -> float:
        """Среднее по ролям, подтипам и территории — инженерная сводка, не оценка."""
        parts: list[float] = []
        for name in ("role_ok", "subtype_ok", "scope_ok"):
            hits, total = self._share(name)
            if total:
                parts.append(hits / total)
        return sum(parts) / len(parts) if parts else 0.0

    def as_dict(self) -> dict[str, Any]:
        role_ok, role_n = self._share("role_ok")
        subtype_ok, subtype_n = self._share("subtype_ok")
        scope_ok, scope_n = self._share("scope_ok")
        refutation_ok, refutation_n = self._share("refutation_ok")
        rules_ok, rules_n = self._share("rules_agree")
        return {
            "stage": self.stage,
            "candidate": self.candidate,
            "schema_mode": self.schema_mode,
            "windows": self.windows,
            "calls": self.calls,
            "valid_json": {"k": self.valid, "n": self.windows, "value": round(self.valid_share, 4)},
            "states": dict(sorted(self.states.items())),
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_rub": round(self.cost_rub, 4),
            "cost_per_window_rub": round(self.cost_per_window, 4),
            "quotes": {
                "total": self.quotes_total,
                "fabricated": self.quotes_fabricated,
                "share": round(self.fabricated_share, 4),
            },
            "dropped_fields": sum(item.dropped_fields for item in self.outcomes),
            "no_new_facts_violations": sum(item.no_new_facts for item in self.outcomes),
            "role": {"k": role_ok, "n": role_n},
            "subtype": {"k": subtype_ok, "n": subtype_n},
            "location_scope": {"k": scope_ok, "n": scope_n},
            "refutations": {"k": refutation_ok, "n": refutation_n},
            "rules_agreement": {"k": rules_ok, "n": rules_n},
            "missed_problems": sum(1 for item in self.outcomes if item.missed_problem),
            "false_problems": sum(1 for item in self.outcomes if item.false_problem),
            "contextual_danger": {
                "k": self.contextual_hits,
                "n": sum(1 for item in self.outcomes if item.danger_found is not None),
            },
            "quality": round(self.quality, 4),
            "stopped": self.stopped,
        }


def _count_quotes(result: ProviderResult | None, window: WindowInput) -> tuple[int, int]:
    """Сколько цитат вернула модель и сколько из них не нашлись в репликах."""
    if result is None:
        return (0, 0)
    try:
        payload = json.loads(result.content)
        parsed = WindowModelOutput.model_validate(payload)
    except Exception:
        return (0, 0)
    texts = {f"m{index}": line.text for index, line in enumerate(window.lines, start=1)}
    total = fabricated = 0
    pairs: list[tuple[str | None, str | None]] = []
    for signal in parsed.signals:
        for name in ("entrance", "floor", "since"):
            raw = getattr(signal, name)
            if raw is not None:
                pairs.append((raw.msg, raw.quote))
        if signal.location_scope.value != "unknown":
            pairs.append((signal.location_scope.msg, signal.location_scope.quote))
        for name in ("current", "local", "observed"):
            facet = getattr(signal.facets, name)
            if facet.quote:
                pairs.append((facet.msg, facet.quote))
        for danger in signal.danger:
            pairs.extend((item.msg, item.quote) for item in danger.evidence)
        if signal.danger_refutation is not None:
            pairs.append((signal.danger_refutation.msg, signal.danger_refutation.quote))
    for msg, quote in pairs:
        if not quote:
            continue
        total += 1
        text = texts.get(msg or "")
        if text is None or not contains_quote(text, quote):
            fabricated += 1
    return (total, fabricated)


def _score(
    window: EvalWindow,
    analysis: WindowAnalysis,
    rules: WindowAnalysis,
    outcome: WindowOutcome,
) -> None:
    outcome.dropped_fields = analysis.dropped_fields
    outcome.no_new_facts = sum(
        1 for event in analysis.audit_events if event.kind == "no_new_facts_violation"
    )
    if window.expected_semantic_danger is not None:
        outcome.danger_found = any(
            danger.kind == window.expected_semantic_danger for danger in analysis.semantic_danger
        ) or any(signal.emergency.is_emergency for signal in analysis.signals)
    if len(window.texts) != 1:
        return
    line_id = f"{window.id}-0"
    prediction = predict(analysis, line_id)
    if window.expected_role is not None:
        outcome.role_ok = prediction.role == window.expected_role
    if window.expected_subtype is not None:
        outcome.subtype_ok = window.expected_subtype in prediction.subtypes
    if window.expected_scope is not None:
        outcome.scope_ok = prediction.scope == window.expected_scope
    predicted_problem = prediction.role == "new_problem" and bool(prediction.categories)
    if window.is_problem:
        outcome.missed_problem = not predicted_problem
    else:
        outcome.false_problem = prediction.role == "new_problem"
    rules_prediction = predict(rules, line_id)
    outcome.rules_agree = prediction.categories == rules_prediction.categories
    detected = [signal for signal in analysis.signals if signal.emergency.is_emergency]
    if window.expected_emergency:
        outcome.refutation_ok = bool(detected) and not any(
            signal.emergency.downgraded for signal in detected
        )
    elif detected:
        outcome.refutation_ok = False


async def run_stage(
    stage: str,
    candidate: Candidate,
    windows: list[EvalWindow],
    *,
    api_key: str,
    base_url: str,
    budget: RunBudget,
) -> StageResult:
    """Прогнать кандидата по окнам с подбором режима схемы и общим лимитом.

    Клиент создаётся один на режим схемы: понижение режима — единственная
    причина пересобрать провайдера.
    """
    mode = candidate.schema_mode
    result = StageResult(stage=stage, candidate=candidate.id, schema_mode=mode)
    rules_only = WindowAnalyzer()
    taxonomy = load_taxonomy()
    recorder, analyzer = _build(candidate, mode, api_key, base_url, taxonomy)
    index = 0
    try:
        while index < len(windows):
            if not budget.allow():
                result.stopped = budget.stop_reason
                break
            window = windows[index]
            window_input = window.to_input()
            analysis = await analyzer.analyze(window_input)
            budget.record(analysis.execution.cost_rub)
            result.calls += 1

            if index == 0 and _looks_like_schema_refusal(analysis, recorder):
                # Подбор режима идёт только на первом окне: дальше отказ — это
                # отказ провайдера, а не повод молча ослабить схему.
                downgraded = _downgrade(mode)
                if downgraded is not None:
                    mode = downgraded
                    result.schema_mode = mode
                    await recorder.inner.aclose()
                    recorder, analyzer = _build(candidate, mode, api_key, base_url, taxonomy)
                    continue

            result.windows += 1
            state = analysis.execution.state
            result.states[state] = result.states.get(state, 0) + 1
            result.latencies_ms.append(analysis.execution.latency_ms)
            result.tokens_in += analysis.execution.tokens_in or 0
            result.tokens_out += analysis.execution.tokens_out or 0
            result.cost_rub += analysis.execution.cost_rub or 0.0
            outcome = WindowOutcome(
                window_id=window.id,
                stratum=window.stratum,
                state=state,
                latency_ms=analysis.execution.latency_ms,
                tokens_in=analysis.execution.tokens_in,
                tokens_out=analysis.execution.tokens_out,
                cost_rub=analysis.execution.cost_rub,
            )
            if state == "ok":
                result.valid += 1
                total, fabricated = _count_quotes(recorder.last, window_input)
                outcome.quotes_total, outcome.quotes_fabricated = total, fabricated
                _score(window, analysis, await rules_only.analyze(window_input), outcome)
            result.outcomes.append(outcome)
            index += 1
    finally:
        await recorder.inner.aclose()
    return result


def _build(
    candidate: Candidate, mode: SchemaMode, api_key: str, base_url: str, taxonomy: Any
) -> tuple[Recorder, WindowAnalyzer]:
    provider = OpenAICompatibleProvider(
        base_url=base_url,
        api_key=api_key,
        model=candidate.id,
        schema_mode=mode,
        timeout_seconds=candidate.timeout_seconds,
        max_tokens=candidate.max_tokens,
        temperature=candidate.temperature,
        taxonomy=taxonomy,
        extra_body=candidate.extra_body,
    )
    recorder = Recorder(provider)
    return recorder, WindowAnalyzer(recorder, timeout_s=candidate.timeout_seconds + 5)


def _looks_like_schema_refusal(analysis: WindowAnalysis, recorder: Recorder) -> bool:
    """Провайдер отказал до ответа — вероятно, не принял форму схемы."""
    return analysis.execution.state == "fallback_provider_error" and recorder.last is None


def _downgrade(mode: SchemaMode) -> SchemaMode | None:
    order = list(SCHEMA_MODES)
    position = order.index(mode)
    return cast(SchemaMode, order[position + 1]) if position + 1 < len(order) else None


def passes_rule(stage: StageResult) -> tuple[bool, list[str]]:
    """Инженерное правило выбора. Это не решение о включении LLM."""
    problems: list[str] = []
    if stage.valid_share < RULE_VALID_JSON:
        problems.append(f"валидный JSON {stage.valid_share:.2%} < {RULE_VALID_JSON:.0%}")
    if stage.fabricated_share > RULE_FABRICATED_QUOTES:
        problems.append(
            f"выдуманных цитат {stage.fabricated_share:.2%} > {RULE_FABRICATED_QUOTES:.0%}"
        )
    if stage.p95_ms > RULE_P95_SECONDS * 1000:
        problems.append(f"p95 {stage.p95_ms / 1000:.1f} с > {RULE_P95_SECONDS:.0f} с")
    return (not problems, problems)


def choose(stage2: list[StageResult], contextual: dict[str, int]) -> tuple[str | None, list[str]]:
    """Модель по умолчанию и резервы: сначала правило, затем меньшая цена."""
    eligible: list[StageResult] = []
    for stage in stage2:
        ok, _problems = passes_rule(stage)
        if ok and contextual.get(stage.candidate, 0) >= RULE_CONTEXTUAL_HITS:
            eligible.append(stage)
    if not eligible:
        return (None, [stage.candidate for stage in stage2])
    best_quality = max(stage.quality for stage in eligible)
    close = [
        stage for stage in eligible if best_quality - stage.quality <= RULE_QUALITY_MARGIN
    ]
    close.sort(key=lambda stage: (stage.cost_per_window, -stage.quality))
    ordered = [stage.candidate for stage in close]
    rest = [stage.candidate for stage in eligible if stage.candidate not in ordered]
    return (ordered[0], ordered[1:] + rest)


# ---------------------------------------------------------------- отчёт


def git_sha() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return done.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def recommended_timeout_seconds(p95_ms: int, floor_seconds: float = 10.0) -> float:
    """Таймаут, который модель реально успевает выдержать.

    Берётся измеренный p95 плюс две секунды запаса и не опускается ниже
    значения по умолчанию из целевой архитектуры (10 с). Профиль говорит
    продукту, сколько на самом деле нужно этой модели; окончательное значение
    всё равно приходит из настроек.
    """
    return max(floor_seconds, float(math.ceil(p95_ms / 1000) + 2))


def write_models_file(
    default: str | None,
    reserves: list[str],
    candidates: dict[str, Candidate],
    measured: dict[str, dict[str, Any]],
    path: pathlib.Path = MODELS_FILE,
) -> None:
    """Записать выбранную модель и резервы в ресурс пакета.

    `measured` — сводки этапа 2 (`StageResult.as_dict()`) по идентификатору
    модели. Файл можно перестроить из сохранённого отчёта, не обращаясь к
    провайдеру заново.
    """
    chosen = [name for name in [default, *reserves] if name][:3]
    document: dict[str, Any] = {
        "version": "v1",
        "selected_at": datetime.now(UTC).date().isoformat(),
        "note": (
            "Выбор сделан на синтетических окнах. Это инженерный выбор модели и "
            "режима схемы, а не решение о включении LLM-слоя: оно принимается в "
            "P6 на данных D2/D3."
        ),
        "default": chosen[0] if chosen else None,
        "models": [],
    }
    for name in chosen:
        candidate = candidates[name]
        stage = measured.get(name)
        p95_ms = int(stage["p95_ms"]) if stage else 0
        document["models"].append(
            {
                "id": candidate.id,
                "label": candidate.label,
                "role": "default" if name == default else "fallback",
                "schema_mode": stage["schema_mode"] if stage else candidate.schema_mode,
                "max_tokens": candidate.max_tokens,
                "timeout_seconds": recommended_timeout_seconds(p95_ms) if stage else 10.0,
                "temperature": candidate.temperature,
                "extra_body": candidate.extra_body or None,
                "upstream": candidate.upstream,
                "stores_data_in_russia": candidate.stores_data_in_russia,
                "policy_basis": candidate.policy_basis,
                "policy_checked_at": candidate.policy_checked_at,
                "measured": (
                    {
                        "windows": stage["windows"],
                        "valid_json": stage["valid_json"]["value"],
                        "fabricated_quotes": stage["quotes"]["share"],
                        "p50_ms": stage["p50_ms"],
                        "p95_ms": p95_ms,
                        "cost_per_window_rub": stage["cost_per_window_rub"],
                        "note": "синтетика, не оценка качества на реальных сообщениях",
                    }
                    if stage
                    else None
                ),
            }
        )
    text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    path.write_text(text, encoding="utf-8", newline="\n")


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# Отбор моделей P2 — {report['generated_at'][:10]}",
        "",
        f"> {report['warning']}",
        "",
        f"- Дата прогона: {report['generated_at']}",
        f"- Commit: `{report['git_sha']}`",
        f"- Провайдер: `{report['base_url']}`",
        f"- Промпт: `{report['prompt']}`, схема: `{report['schema']}`, "
        f"таксономия: `{report['taxonomy']}`",
        f"- Итог прогона: **{report['budget']['calls']} вызовов**, "
        f"**{report['budget']['spent_rub']:.2f} ₽** "
        f"(лимит {report['budget']['max_calls']} вызовов и "
        f"{report['budget']['max_rub']:.0f} ₽)",
        "",
    ]
    if report["status"] != "done":
        lines += [f"## Статус: {report['status']}", "", report["status_note"], ""]

    lines += [
        "## Кандидаты и основание политики обработки данных",
        "",
        "| Модель | Вышестоящий провайдер | Данные в РФ | ₽/млн вход | ₽/млн выход | Основание |",
        "|---|---|---|---|---|---|",
    ]
    for item in report["candidates"]:
        lines.append(
            f"| `{item['id']}` | {item['upstream']} | "
            f"{'да' if item['stores_data_in_russia'] else 'нет'} | "
            f"{item['price_in_per_million']} | {item['price_out_per_million']} | "
            f"{item['policy_basis']} (проверено {item['policy_checked_at']}) |"
        )
    lines.append("")

    for stage_name, title in (("stage1", "Этап 1 — 20 фиксированных окон"),
                              ("stage2", "Этап 2 — стратифицированная выборка")):
        rows = report[stage_name]
        lines += [f"## {title}", ""]
        if not rows:
            lines += ["Не выполнялся.", ""]
            continue
        lines += [
            "| Модель | Режим схемы | Окон | Валидный JSON | p50, с | p95, с | Токены вх/вых | "
            "₽ за окно | Выдуманные цитаты | Качество |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                f"| `{row['candidate']}` | `{row['schema_mode']}` | {row['windows']} | "
                f"{row['valid_json']['k']}/{row['valid_json']['n']} "
                f"({row['valid_json']['value']:.0%}) | "
                f"{row['p50_ms'] / 1000:.1f} | {row['p95_ms'] / 1000:.1f} | "
                f"{row['tokens_in']}/{row['tokens_out']} | {row['cost_per_window_rub']:.4f} | "
                f"{row['quotes']['fabricated']}/{row['quotes']['total']} "
                f"({row['quotes']['share']:.1%}) | {row['quality']:.2f} |"
            )
        lines.append("")
        if stage_name == "stage2":
            lines += [
                "| Модель | Роль | Подтип | Территория | Пропущено | Ложных | "
                "Опровержения | Согласие с правилами | `no_new_facts` |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for row in rows:
                lines.append(
                    f"| `{row['candidate']}` | {row['role']['k']}/{row['role']['n']} | "
                    f"{row['subtype']['k']}/{row['subtype']['n']} | "
                    f"{row['location_scope']['k']}/{row['location_scope']['n']} | "
                    f"{row['missed_problems']} | {row['false_problems']} | "
                    f"{row['refutations']['k']}/{row['refutations']['n']} | "
                    f"{row['rules_agreement']['k']}/{row['rules_agreement']['n']} | "
                    f"{row['no_new_facts_violations']} |"
                )
            lines.append("")

    lines += ["## Контекстная опасность (окна sw01–sw05)", ""]
    if report["contextual"]:
        lines += ["| Модель | Найдено из 5 |", "|---|---|"]
        for name, hits in report["contextual"].items():
            lines.append(f"| `{name}` | {hits} |")
    else:
        lines.append("Не измерялась.")
    lines.append("")

    lines += ["## Что этот прогон не измеряет", ""]
    for item in report.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")

    lines += [
        "## Правило выбора",
        "",
        f"Валидный JSON ≥ {RULE_VALID_JSON:.0%}; выдуманных цитат ≤ "
        f"{RULE_FABRICATED_QUOTES:.0%}; контекстная опасность найдена не менее чем в "
        f"{RULE_CONTEXTUAL_HITS} из 5 окон sw01–sw05; p95 ≤ {RULE_P95_SECONDS:.0f} с; "
        f"затем меньшая цена при качестве в пределах "
        f"{RULE_QUALITY_MARGIN * 100:.0f} п. п. от лучшего.",
        "",
        f"**Модель по умолчанию:** `{report['default'] or 'не выбрана'}`.",
        f"**Резервы:** {', '.join(f'`{name}`' for name in report['reserves']) or '—'}.",
        "",
        "Это инженерный выбор модели и режима схемы. Решение о включении "
        "LLM-слоя принимается в P6 на данных D2/D3, не здесь.",
        "",
    ]
    if report["rejected"]:
        lines += ["### Не прошли правило", ""]
        for name, problems in report["rejected"].items():
            lines.append(f"- `{name}`: {'; '.join(problems) or 'не дошёл до этапа 2'}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- запуск


async def build_report(arguments: argparse.Namespace) -> dict[str, Any]:
    datasets = {
        "singles": load_dataset(DATASETS / "single_messages.v1.jsonl"),
        "scope": load_dataset(DATASETS / "scope_and_danger.v1.jsonl"),
        "stream": load_dataset(DATASETS / "chat_stream.v1.jsonl"),
    }
    allowed_texts: set[str] = set()
    for rows in datasets.values():
        for row in rows:
            if isinstance(row.get("text"), str):
                allowed_texts.add(row["text"])
            for item in row.get("lines", []):
                allowed_texts.add(item["text"])

    stage1_windows = build_stage1_windows(datasets)
    stage2_windows = build_stage2_windows(datasets, limit=arguments.stage2_windows)
    guard_windows(stage1_windows, allowed_texts)
    guard_windows(stage2_windows, allowed_texts)

    candidates = load_candidates()
    by_id = {candidate.id: candidate for candidate in candidates}
    budget = RunBudget(max_calls=arguments.max_calls, max_rub=arguments.max_rub)
    api_key = os.environ.get("LLM_API_KEY", "").strip()

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "base_url": arguments.base_url,
        "warning": WARNING,
        "prompt": "window.v1",
        "schema": "window_output.v1",
        "taxonomy": load_taxonomy().version,
        "status": "done",
        "status_note": "",
        "limitations": list(LIMITATIONS),
        "candidates": [
            {
                "id": candidate.id,
                "upstream": candidate.upstream,
                "stores_data_in_russia": candidate.stores_data_in_russia,
                "price_in_per_million": candidate.price_in_per_million,
                "price_out_per_million": candidate.price_out_per_million,
                "policy_basis": candidate.policy_basis,
                "policy_checked_at": candidate.policy_checked_at,
            }
            for candidate in candidates
        ],
        "stage1_windows": [window.id for window in stage1_windows],
        "stage2_windows": [window.id for window in stage2_windows],
        "stage1": [],
        "stage2": [],
        "contextual": {},
        "default": None,
        "reserves": [],
        "rejected": {},
        "budget": {
            "calls": 0,
            "spent_rub": 0.0,
            "max_calls": arguments.max_calls,
            "max_rub": arguments.max_rub,
            "stop_reason": None,
            "approaching": None,
        },
    }

    if not api_key:
        report["status"] = "NOT RUN"
        report["status_note"] = (
            "Ключ `LLM_API_KEY` не задан, поэтому ни один внешний вызов не сделан. "
            "Окна собраны и проверены сторожем данных; скрипт готов к запуску: "
            "`LLM_API_KEY=... uv run python evaluation/select_models.py`."
        )
        return report

    stage1: list[StageResult] = []
    for candidate in candidates:
        stage = await run_stage(
            "stage1",
            candidate,
            stage1_windows,
            api_key=api_key,
            base_url=arguments.base_url,
            budget=budget,
        )
        stage1.append(stage)
        report["contextual"][candidate.id] = stage.contextual_hits
        print(
            f"stage1 {candidate.id}: {stage.valid}/{stage.windows} валидных, "
            f"p95 {stage.p95_ms / 1000:.1f} s, {stage.cost_rub:.2f} RUB, "
            f"режим {stage.schema_mode}",
            flush=True,
        )
    report["stage1"] = [stage.as_dict() for stage in stage1]

    ranked = sorted(
        stage1,
        key=lambda stage: (-stage.valid_share, stage.p95_ms, stage.cost_per_window),
    )
    finalists = ranked[: arguments.top]
    stage2: list[StageResult] = []
    for stage in finalists:
        candidate = by_id[stage.candidate]
        result = await run_stage(
            "stage2",
            candidate,
            stage2_windows,
            api_key=api_key,
            base_url=arguments.base_url,
            budget=budget,
        )
        result.schema_mode = stage.schema_mode
        stage2.append(result)
        print(
            f"stage2 {candidate.id}: {result.valid}/{result.windows} валидных, "
            f"качество {result.quality:.2f}, {result.cost_rub:.2f} RUB",
            flush=True,
        )
    report["stage2"] = [stage.as_dict() for stage in stage2]

    default, reserves = choose(stage2, cast(dict[str, int], report["contextual"]))
    report["default"] = default
    report["reserves"] = reserves[:2]
    for stage in stage2:
        ok, problems = passes_rule(stage)
        hits = cast(dict[str, int], report["contextual"]).get(stage.candidate, 0)
        if hits < RULE_CONTEXTUAL_HITS:
            problems.append(f"контекстная опасность {hits}/5 < {RULE_CONTEXTUAL_HITS}")
        if not ok or problems:
            report["rejected"][stage.candidate] = problems
    report["budget"] = {
        "calls": budget.calls,
        "spent_rub": round(budget.spent_rub, 4),
        "max_calls": budget.max_calls,
        "max_rub": budget.max_rub,
        "stop_reason": budget.stop_reason,
        "approaching": budget.approaching,
    }
    if budget.stop_reason:
        report["status"] = "STOPPED AT BUDGET"
        report["status_note"] = f"Прогон остановлен: {budget.stop_reason}."

    if default is not None and not arguments.dry_run:
        write_models_file(
            default,
            report["reserves"],
            by_id,
            {stage.candidate: stage.as_dict() for stage in stage2},
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Отбор моделей P2 на синтетических окнах")
    parser.add_argument("--out", default="evaluation/reports/")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--max-calls", type=int, default=MAX_CALLS)
    parser.add_argument("--max-rub", type=float, default=MAX_RUB)
    parser.add_argument("--stage2-windows", type=int, default=60)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="не записывать models.v1.yaml")
    arguments = parser.parse_args()

    report = asyncio.run(build_report(arguments))
    out_dir = pathlib.Path(arguments.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['generated_at'][:10]}-p2-model-selection"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / f"{stem}.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")
    print(f"report: {out_dir / f'{stem}.md'}")
    print(f"report: {out_dir / f'{stem}.json'}")
    print(
        f"итог: {report['budget']['calls']} вызовов, "
        f"{report['budget']['spent_rub']:.2f} RUB, статус {report['status']}"
    )
    return 0 if report["status"] in ("done", "NOT RUN") else 1


if __name__ == "__main__":
    raise SystemExit(main())
