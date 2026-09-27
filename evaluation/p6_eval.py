"""P6: оценка ядра на D3/D5 — режим модели против режима правил на тех же окнах.

    uv run python evaluation/p6_eval.py --dataset d3_dev --config gpt5mini_v1_low --run r01
    uv run python evaluation/p6_eval.py --dataset d5 --config rules --run r02
    uv run python evaluation/p6_eval.py --summarize evaluation/reports/p6-runs/r01.jsonl
    uv run python evaluation/p6_eval.py --slice p6b --dataset d5_dev --config rules --run t01

Жёсткие правила (docs/decisions.md#p6-prereg-2026-09-23):

1. Во внешний API уходят только строки `datasets/synthetic/*` с `synthetic: true`
   (`evaluation.guard`); каталог `data/` не читается ни в каком виде.
2. Все вызовы модели идут через общий лимит среза `SliceBudget`
   (P6: 700 вызовов и 300 ₽, P6b: 400 вызовов и 150 ₽; файл-счётчик в
   `evaluation/reports`).
3. holdout прогоняется один раз итоговой конфигурацией; промпт настраивается
   только на dev. В P6b настройка — только на `d5_dev` и dev D3, D5 и holdout
   D3 — контроль.

Окна режутся политикой ядра по умолчанию (`WindowPolicy()`), каждый диалог —
отдельный поток. Открытые элементы симулируют продукт: сигналы Inbox,
созданные предыдущими окнами того же диалога **в том же режиме**, с
категорией, подтипом, подъездом и видами опасности.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import statistics
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from domsignal.ai import (  # noqa: E402
    WindowAnalyzer,
    WindowInput,
    WindowLine,
    chat_memo_hits,
    screen_message_for_danger,
)
from domsignal.ai.contracts import OpenItem, WindowAnalysis  # noqa: E402
from domsignal.ai.providers.base import ProviderRequest, ProviderResult  # noqa: E402
from domsignal.ai.providers.openai_compatible import (  # noqa: E402
    DEFAULT_BASE_URL,
    OpenAICompatibleProvider,
)
from domsignal.ai.schema_modes import SchemaMode  # noqa: E402
from domsignal.ai.taxonomy import load_taxonomy  # noqa: E402
from domsignal.ai.windowing import build_windows  # noqa: E402
from domsignal.core.routing import (  # noqa: E402
    HouseRoutingContext,
    RoutingQuery,
    resolve_route,
)
from domsignal.services.routing import load_directory  # noqa: E402
from evaluation.guard import SliceBudget, SliceBudgetExceeded, load_allowed_jsonl  # noqa: E402
from evaluation.metrics import BASE_TIME, ratio  # noqa: E402
from evaluation.select_models import _count_quotes  # noqa: E402

DATASETS = {
    "d3_dev": pathlib.Path("datasets/synthetic/d3_dialogs.v1.dev.jsonl"),
    "d3_holdout": pathlib.Path("datasets/synthetic/d3_dialogs.v1.holdout.jsonl"),
    "d5": pathlib.Path("datasets/synthetic/d5_danger.v1.jsonl"),
    # P6b: набор настройки опасности другого стиля; D5 остаётся контролем.
    "d5_dev": pathlib.Path("datasets/synthetic/d5_dev.v1.jsonl"),
    # P6b (живой шаг 6): открытая опасность в доме + новый вид или продолжение.
    "open_danger_dev": pathlib.Path("datasets/synthetic/open_danger_dev.v1.jsonl"),
    # D2 появляется только после сессии с добровольцами (evaluation/d2_convert.py).
    "d2": pathlib.Path("datasets/synthetic/d2_dialogs.v1.jsonl"),
}
#: Окно D5-типа: одно окно на строку набора, без нарезки.
SINGLE_WINDOW = frozenset({"d5", "d5_dev", "open_danger_dev"})


@dataclass(frozen=True)
class Slice:
    """Каталог прогонов и лимит вызовов модели одного среза."""

    runs: pathlib.Path
    ledger: pathlib.Path
    max_calls: int
    max_rub: float


SLICES = {
    "p6": Slice(
        pathlib.Path("evaluation/reports/p6-runs"),
        pathlib.Path("evaluation/reports/2026-09-23-p6-ledger.json"),
        700,
        300.0,
    ),
    # 400 вызовов по заданию; 600 — после живого шага 6 (решение владельца
    # «чинить сейчас», промпт window.v3 на наборах настройки).
    "p6b": Slice(
        pathlib.Path("evaluation/reports/p6b-runs"),
        pathlib.Path("evaluation/reports/2026-09-24-p6b-ledger.json"),
        600,
        150.0,
    ),
    # P6c: закрытие AI-ступени — регрессия window.v3 против window.v2 на dev.
    "p6c": Slice(
        pathlib.Path("evaluation/reports/p6c-runs"),
        pathlib.Path("evaluation/reports/2026-09-24-p6c-ledger.json"),
        200,
        30.0,
    ),
    # M1: смена модели на открытую неамериканскую в Cloud.ru — только наборы
    # настройки (d5_dev, open_danger_dev, подвыборка dev D3); контроль — D6.
    "m1": Slice(
        pathlib.Path("evaluation/reports/m1-runs"),
        pathlib.Path("evaluation/reports/2026-09-27-m1-ledger.json"),
        400,
        30.0,
    ),
}
RUNS_DIR = SLICES["p6"].runs
LEDGER = SLICES["p6"].ledger
MAX_OPEN_ITEMS = 10
#: Профиль дома для маршрута от начала до конца (live-стенд, решение владельца).
HOUSE = HouseRoutingContext(
    is_demo=False,
    has_active_connected_uk=True,
    region_code="RU-TA",
    municipality_code="kazan",
    territory_policy="mixed",
)
ROUTE_DAY = date(2026, 9, 23)


@dataclass(frozen=True)
class ModelConfig:
    """Как обращаться к модели в прогоне. `model=None` — режим правил."""

    name: str
    model: str | None = None
    prompt: str = "window.v1"
    few_shot: bool = True
    effort: str | None = "low"
    provider_only: tuple[str, ...] = ()
    provider_order: tuple[str, ...] = ()
    temperature: float | None = None
    max_tokens: int = 1600
    timeout_seconds: float = 60.0
    #: P6b (A2): рассуждения для окон, где правила нашли опасность без отрицания.
    danger_effort: str | None = None
    #: P6b (живой шаг 6): рассуждения для окон при открытом сигнале об опасности.
    open_danger_effort: str | None = None
    #: P6c: лимит ответа тех же окон (рассуждения low упирались в 1600).
    open_danger_max_tokens: int | None = None
    #: M1: режим схемы, цена (₽ за млн токенов входа/выхода) и параметры семейства.
    schema_mode: SchemaMode = "json_schema_strict"
    price_rub_per_million: tuple[float, float] | None = None
    extra: tuple[tuple[str, Any], ...] = ()

    def for_window(self, rules_danger: bool, open_danger: bool = False) -> ModelConfig:
        """Конфигурация вызова окна: другие рассуждения только в особых окнах."""
        if rules_danger and self.danger_effort is not None:
            return replace(self, effort=self.danger_effort)
        if open_danger and self.open_danger_effort is not None:
            return replace(
                self,
                effort=self.open_danger_effort,
                max_tokens=self.open_danger_max_tokens or self.max_tokens,
            )
        return self

    def extra_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self.effort is not None:
            body["reasoning"] = {"effort": self.effort}
        if self.provider_only:
            body["provider"] = {"only": list(self.provider_only), "allow_fallbacks": False}
        elif self.provider_order:
            body["provider"] = {"order": list(self.provider_order), "allow_fallbacks": True}
        body.update(dict(self.extra))
        return body


CONFIGS: dict[str, ModelConfig] = {
    "rules": ModelConfig(name="rules"),
    # A: профиль production на 23.09 (flex, reasoning low, промпт v1).
    "gpt5mini_v1_low": ModelConfig(name="gpt5mini_v1_low", model="openai/gpt-5-mini"),
    # B: обычный уровень обслуживания OpenAI вместо flex (в 2 раза дороже).
    "gpt5mini_v1_low_standard": ModelConfig(
        name="gpt5mini_v1_low_standard", model="openai/gpt-5-mini", provider_only=("openai",)
    ),
    # B': явный flex-уровень (в каталоге polza — `openai/flex`, вдвое дешевле).
    "gpt5mini_v1_low_flex": ModelConfig(
        name="gpt5mini_v1_low_flex", model="openai/gpt-5-mini", provider_only=("openai/flex",)
    ),
    "gpt5mini_v1_minimal_flex": ModelConfig(
        name="gpt5mini_v1_minimal_flex",
        model="openai/gpt-5-mini",
        effort="minimal",
        provider_only=("openai/flex",),
    ),
    "gpt5mini_v2_minimal_flex": ModelConfig(
        name="gpt5mini_v2_minimal_flex",
        model="openai/gpt-5-mini",
        prompt="window.v2",
        effort="minimal",
        provider_only=("openai/flex",),
    ),
    # C: минимальные рассуждения.
    "gpt5mini_v1_minimal": ModelConfig(
        name="gpt5mini_v1_minimal", model="openai/gpt-5-mini", effort="minimal"
    ),
    # D: компактный промпт v2.
    "gpt5mini_v2_low": ModelConfig(
        name="gpt5mini_v2_low", model="openai/gpt-5-mini", prompt="window.v2"
    ),
    "gpt5mini_v2_minimal": ModelConfig(
        name="gpt5mini_v2_minimal", model="openai/gpt-5-mini", prompt="window.v2", effort="minimal"
    ),
    "gpt5mini_v2_minimal_standard": ModelConfig(
        name="gpt5mini_v2_minimal_standard",
        model="openai/gpt-5-mini",
        prompt="window.v2",
        effort="minimal",
        provider_only=("openai",),
    ),
    # F: итоговый кандидат — flex первым, при отказе flex — обычный уровень.
    "gpt5mini_v2_minimal_flexfirst": ModelConfig(
        name="gpt5mini_v2_minimal_flexfirst",
        model="openai/gpt-5-mini",
        prompt="window.v2",
        effort="minimal",
        provider_order=("openai/flex", "openai"),
    ),
    # P6b A2: итоговый профиль, но `low` для окон с опасностью правил.
    "gpt5mini_v2_minimal_flexfirst_dangerlow": ModelConfig(
        name="gpt5mini_v2_minimal_flexfirst_dangerlow",
        model="openai/gpt-5-mini",
        prompt="window.v2",
        effort="minimal",
        provider_order=("openai/flex", "openai"),
        danger_effort="low",
    ),
    # P6b после живого шага 6: промпт window.v3, профиль прежний.
    "gpt5mini_v3_minimal_flexfirst": ModelConfig(
        name="gpt5mini_v3_minimal_flexfirst",
        model="openai/gpt-5-mini",
        prompt="window.v3",
        effort="minimal",
        provider_order=("openai/flex", "openai"),
    ),
    "gpt5mini_v3_minimal_flexfirst_openlow": ModelConfig(
        name="gpt5mini_v3_minimal_flexfirst_openlow",
        model="openai/gpt-5-mini",
        prompt="window.v3",
        effort="minimal",
        provider_order=("openai/flex", "openai"),
        open_danger_effort="low",
    ),
    # P6c: профиль production после §3 — тот же, лимит ответа окон при
    # открытой опасности 2800 (решение владельца).
    "gpt5mini_v3_openlow_2800": ModelConfig(
        name="gpt5mini_v3_openlow_2800",
        model="openai/gpt-5-mini",
        prompt="window.v3",
        effort="minimal",
        provider_order=("openai/flex", "openai"),
        open_danger_effort="low",
        open_danger_max_tokens=2800,
    ),
    # E: резервная модель на тех же окнах.
    "gemini_v1": ModelConfig(
        name="gemini_v1", model="google/gemini-3.1-flash-lite", effort=None, temperature=0.0
    ),
    "gemini_v2": ModelConfig(
        name="gemini_v2",
        model="google/gemini-3.1-flash-lite",
        prompt="window.v2",
        effort=None,
        temperature=0.0,
    ),
    # M1 (27.09): открытые неамериканские модели внутри Cloud.ru, промпт
    # production `window.v3`; рассуждений у GigaChat3-10B нет.
    "gigachat3_10b_v3": ModelConfig(
        name="gigachat3_10b_v3",
        model="ai-sage/GigaChat3-10B-A1.8B",
        prompt="window.v3",
        effort=None,
        temperature=0.0,
        timeout_seconds=30.0,
        price_rub_per_million=(12.2, 12.2),
    ),
    # Диагностика петли: ответы до лимита 1600 повторяли одно и то же.
    "gigachat3_10b_v3_rep": ModelConfig(
        name="gigachat3_10b_v3_rep",
        model="ai-sage/GigaChat3-10B-A1.8B",
        prompt="window.v3",
        effort=None,
        temperature=0.0,
        timeout_seconds=30.0,
        price_rub_per_million=(12.2, 12.2),
        extra=(("repetition_penalty", 1.1),),
    ),
    "gigachat35_v3": ModelConfig(
        name="gigachat35_v3",
        model="ai-sage/GigaChat3.5-432B-A28B",
        prompt="window.v3",
        effort=None,
        temperature=0.0,
        timeout_seconds=30.0,
        price_rub_per_million=(96.22, 288.6),
    ),
    # Qwen3-30B-A3B в каталоге Cloud.ru — «внешняя» модель (данные вне
    # инфраструктуры Cloud.ru); рассуждения выключаются шаблоном чата.
    "qwen3_30b_v3": ModelConfig(
        name="qwen3_30b_v3",
        model="Qwen/Qwen3-30B-A3B",
        prompt="window.v3",
        effort=None,
        temperature=0.0,
        timeout_seconds=30.0,
        price_rub_per_million=(13.908, 55.6076),
        extra=(("chat_template_kwargs", {"enable_thinking": False}),),
    ),
    "qwen36_v3": ModelConfig(
        name="qwen36_v3",
        model="Qwen/Qwen3.6-35B-A3B",
        prompt="window.v3",
        effort=None,
        temperature=0.0,
        timeout_seconds=30.0,
        price_rub_per_million=(219.6, 329.4),
        extra=(("chat_template_kwargs", {"enable_thinking": False}),),
    ),
}


# ----------------------------------------------------------------- окна


@dataclass
class EvalUnit:
    """Поток одного диалога D3 или одно окно D5 — с эталоном."""

    id: str
    lines: list[WindowLine]
    labels: dict[str, Any]
    context: tuple[WindowLine, ...] = ()
    open_items: tuple[OpenItem, ...] = ()


def load_units(dataset: str) -> list[EvalUnit]:
    rows = load_allowed_jsonl(DATASETS[dataset])
    units: list[EvalUnit] = []
    for row in rows:
        lines = [
            WindowLine(
                line_id=f"{row['id']}-{item['n']}",
                author_ref=f"{row['id']}-{item['author']}",
                text=item["text"],
                sent_at=BASE_TIME + timedelta(seconds=item["offset_s"]),
                reply_to=f"{row['id']}-{item['reply_to']}" if item.get("reply_to") else None,
            )
            for item in row["lines"]
        ]
        context = tuple(
            WindowLine(
                line_id=f"{row['id']}-c{item['n']}",
                author_ref=f"{row['id']}-{item['author']}",
                text=item["text"],
                sent_at=BASE_TIME + timedelta(seconds=item["offset_s"]),
                is_context=True,
            )
            for item in row.get("context", [])
        )
        open_items = tuple(OpenItem.model_validate(item) for item in row.get("open_items", []))
        units.append(
            EvalUnit(
                id=row["id"], lines=lines, labels=row, context=context, open_items=open_items
            )
        )
    return units


def unit_windows(unit: EvalUnit, dataset: str) -> list[WindowInput]:
    if dataset in SINGLE_WINDOW:
        return [
            WindowInput(
                channel="group_passive",
                lines=(*unit.context, *unit.lines),
                open_items=unit.open_items,
            )
        ]
    return build_windows(unit.lines, channel="group_passive")


# ------------------------------------------------------------- провайдер


@dataclass
class CallRecorder:
    """Провайдер-обёртка одного окна: сырой ответ, учёт и лимит среза."""

    inner: OpenAICompatibleProvider
    budget: SliceBudget
    run: str
    last: ProviderResult | None = None
    called: bool = False

    @property
    def prompt_version(self) -> str | None:
        return self.inner.prompt_version

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        self.budget.reserve()
        self.called = True
        try:
            result = await self.inner.analyze_window(request)
        except BaseException:
            self.budget.commit(self.run, None)
            raise
        self.last = result
        self.budget.commit(self.run, result.cost_rub)
        return result


class UsageTap:
    """Запоминает `usage` и имя вышестоящего провайдера из тела ответа."""

    def __init__(self) -> None:
        self.by_request: dict[int, dict[str, Any]] = {}
        self.last: dict[str, Any] = {}

    async def __call__(self, response: httpx.Response) -> None:
        await response.aread()
        self.last = {"status": response.status_code}
        try:
            body = response.json()
        except ValueError:
            return
        if isinstance(body, dict):
            self.last = {
                "usage": body.get("usage"),
                "provider": body.get("provider"),
                "status": response.status_code,
            }
            if response.status_code != 200:
                # M1: причина отказа провайдера (тип и код, без текста окна).
                error = body.get("error")
                if isinstance(error, dict):
                    self.last["error"] = {
                        key: str(error.get(key))[:200] for key in ("type", "code", "message")
                    }


def build_provider(config: ModelConfig, api_key: str, tap: UsageTap) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(timeout=config.timeout_seconds, event_hooks={"response": [tap]})
    assert config.model is not None
    return OpenAICompatibleProvider(
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
        model=config.model,
        schema_mode=config.schema_mode,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        extra_body=config.extra_body(),
        client=client,
        prompt_version=config.prompt,
        few_shot=config.few_shot,
        price_rub_per_million=config.price_rub_per_million,
    )


# ------------------------------------------------------------- прогон


def _signal_record(analysis: WindowAnalysis) -> list[dict[str, Any]]:
    return [
        {
            "ref": signal.ref,
            "subtype": signal.subtype,
            "category": signal.product_category.value,
            "scope": signal.location_scope.value,
            "entrance": signal.entrance.value if signal.entrance else None,
            "floor": signal.floor.value if signal.floor else None,
            "since": signal.since.value if signal.since else None,
            "strength": signal.strength,
            "disposition": signal.disposition,
            "line_ids": list(signal.line_ids),
            "emergency": {
                "is": signal.emergency.is_emergency,
                "kinds": list(signal.emergency.kinds),
                "sources": list(signal.emergency.sources),
                "downgraded": signal.emergency.downgraded,
                "memo": signal.emergency.memo_allowed,
            },
            "flags": list(signal.flags),
            "has_summary": signal.summary is not None,
            "has_clean_description": signal.clean_description is not None,
        }
        for signal in analysis.signals
    ]


def rules_danger(window: WindowInput) -> bool:
    """Правила нашли в репликах окна опасность без отрицания."""
    return any(
        not hit.negated
        for line in window.lines
        if not line.is_context
        for hit in screen_message_for_danger(line.text, line_id=line.line_id)
    )


def intake_record(window: WindowInput) -> list[dict[str, Any]]:
    """Путь приёма продукта по каждой реплике окна: до окна и до модели.

    Продукт проверяет каждую реплику правилами опасности в транзакции приёма
    (`passive_capture`): любое срабатывание без отрицания — предварительный
    критический сигнал и оповещение оператора; памятка в чат — только по
    срабатываниям с правом на памятку (`chat_memo_hits`).
    """
    records: list[dict[str, Any]] = []
    for line in window.lines:
        if line.is_context:
            continue
        hits = screen_message_for_danger(line.text, line_id=line.line_id)
        active = [hit for hit in hits if not hit.negated]
        records.append(
            {
                "line": line.line_id,
                "alert": bool(active),
                "memo": bool(chat_memo_hits(hits)),
                "kinds": sorted({hit.kind for hit in active}),
            }
        )
    return records


def _update_open_items(
    open_items: list[OpenItem], analysis: WindowAnalysis, unit_id: str, counter: list[int]
) -> list[OpenItem]:
    """Продукт в миниатюре: новый сигнал Inbox становится открытым элементом."""
    items = {item.ref: item for item in open_items}
    for signal in analysis.signals:
        if signal.disposition != "inbox":
            continue
        kinds = tuple(signal.emergency.kinds)
        if signal.ref in items:
            old = items[signal.ref]
            merged = tuple(dict.fromkeys(old.danger_kinds + kinds))
            items[signal.ref] = old.model_copy(update={"danger_kinds": merged})
            continue
        counter[0] += 1
        ref = f"sig:{unit_id}:{counter[0]}"
        items[ref] = OpenItem(
            ref=ref,
            kind="signal",
            category=signal.product_category,
            subtype=signal.subtype,
            entrance=signal.entrance.value if signal.entrance else None,
            title=signal.object_label[:200],
            danger_kinds=kinds,
        )
    ordered = list(items.values())
    return ordered[-MAX_OPEN_ITEMS:]


async def run_unit(
    unit: EvalUnit,
    dataset: str,
    config: ModelConfig,
    *,
    api_key: str | None,
    budget: SliceBudget | None,
    run: str,
    pace_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    open_items: list[OpenItem] = list(unit.open_items)
    counter = [0]
    windows = unit_windows(unit, dataset)
    for index, base in enumerate(windows):
        window = base.model_copy(update={"open_items": tuple(open_items)})
        tap = UsageTap()
        recorder: CallRecorder | None = None
        danger = rules_danger(window)
        call = config.for_window(
            danger, open_danger=any(item.danger_kinds for item in window.open_items)
        )
        if config.model is None:
            analyzer = WindowAnalyzer()
        else:
            assert api_key is not None and budget is not None
            recorder = CallRecorder(build_provider(call, api_key, tap), budget, run)
            analyzer = WindowAnalyzer(recorder, timeout_s=call.timeout_seconds + 2)
        if pace_seconds and recorder is not None:
            # M1: лимит Cloud.ru — 100 тыс. токенов в минуту на ключ.
            await asyncio.sleep(pace_seconds)
        started = time.perf_counter()
        try:
            analysis = await analyzer.analyze(window)
        finally:
            if recorder is not None:
                await recorder.inner.aclose()
        wall_ms = int((time.perf_counter() - started) * 1000)
        quotes_total, quotes_fabricated = (
            _count_quotes(recorder.last, window) if recorder is not None else (0, 0)
        )
        records.append(
            {
                "run": run,
                "config": config.name,
                "dataset": dataset,
                "unit": unit.id,
                "window": index,
                "own_lines": [line.line_id for line in window.lines if not line.is_context],
                "context_lines": [line.line_id for line in window.lines if line.is_context],
                "open_items": [item.ref for item in window.open_items],
                "mode": analysis.mode,
                "state": analysis.execution.state,
                "provider_called": analysis.execution.provider_called,
                "latency_ms": analysis.execution.latency_ms,
                "wall_ms": wall_ms,
                "tokens_in": analysis.execution.tokens_in,
                "tokens_out": analysis.execution.tokens_out,
                "cost_rub": analysis.execution.cost_rub,
                "usage": tap.last.get("usage"),
                "upstream": tap.last.get("provider"),
                "http_status": tap.last.get("status"),
                "provider_error": tap.last.get("error"),
                "prompt": analysis.versions.prompt,
                "model": analysis.versions.model,
                "quotes_total": quotes_total,
                "quotes_fabricated": quotes_fabricated,
                "dropped_fields": analysis.dropped_fields,
                "audit": dict(Counter(event.kind for event in analysis.audit_events)),
                "roles": {verdict.line_id: verdict.role for verdict in analysis.lines},
                "signals": _signal_record(analysis),
                "semantic_danger": [danger.kind for danger in analysis.semantic_danger],
                "intake": intake_record(window),
                "rules_danger": danger,
                "effort": call.effort,
            }
        )
        open_items = _update_open_items(open_items, analysis, unit.id, counter)
    return records


async def run_dataset(
    dataset: str,
    config: ModelConfig,
    *,
    run: str,
    units: Sequence[EvalUnit],
    api_key: str | None,
    budget: SliceBudget | None,
    concurrency: int,
    pace_seconds: float = 0.0,
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    stopped: list[str] = []

    async def one(unit: EvalUnit) -> list[dict[str, Any]]:
        async with semaphore:
            if stopped:
                return []
            try:
                return await run_unit(
                    unit,
                    dataset,
                    config,
                    api_key=api_key,
                    budget=budget,
                    run=run,
                    pace_seconds=pace_seconds,
                )
            except SliceBudgetExceeded as exc:
                stopped.append(str(exc))
                return []

    results = await asyncio.gather(*(one(unit) for unit in units))
    if stopped:
        print(f"ОСТАНОВЛЕНО лимитом среза: {stopped[0]}", file=sys.stderr)
    return [record for part in results for record in part]


# ------------------------------------------------------------- метрики


def _percentile(values: Sequence[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
    return ordered[index]


def _route_type(subtype: str, scope: str, kinds: Sequence[str], directory: Any) -> str:
    route = resolve_route(
        RoutingQuery(
            subtype=subtype,
            location_scope=scope,  # type: ignore[arg-type]
            danger_kinds=tuple(kinds),  # type: ignore[arg-type]
            house=HOUSE,
        ),
        directory,
        known_subtypes=load_taxonomy().codes,
        today=ROUTE_DAY,
    )
    if route.requires_operator_choice:
        return "operator_choice"
    return str(route.route_type)


ROUTES_FILE = pathlib.Path("datasets/routing/route_reference.v1.jsonl")


def route_reference_accuracy() -> dict[str, Any]:
    """Роутер (только чтение) на эталоне «подтип × территория × опасность»."""
    directory = load_directory(pathlib.Path("regions"))
    rows = load_allowed_jsonl(ROUTES_FILE)
    mismatches: list[dict[str, Any]] = []
    ok = 0
    for row in rows:
        kinds = [row["danger_kind"]] if row["danger_kind"] else []
        got = _route_type(row["subtype"], row["location_scope"], kinds, directory)
        if got == row["expected_route_type"]:
            ok += 1
        else:
            mismatches.append(
                {
                    "subtype": row["subtype"],
                    "location_scope": row["location_scope"],
                    "danger_kind": row["danger_kind"],
                    "expected": row["expected_route_type"],
                    "router": got,
                }
            )
    return {"accuracy": ratio(ok, len(rows)), "mismatches": mismatches}


def summarize_d3(records: Sequence[dict[str, Any]], dataset: str) -> dict[str, Any]:
    units = {unit.id: unit for unit in load_units(dataset)}
    directory = load_directory(pathlib.Path("regions"))
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_unit.setdefault(record["unit"], []).append(record)

    incidents = 0
    captured = 0
    subtype_ok = scope_ok = entrance_ok = entrance_n = route_ok = route_n = 0
    category_ok = 0
    danger_found = danger_n = 0
    inbox_signals = non_problem = 0
    roles_ok = roles_n = 0
    missed: list[str] = []
    details: list[dict[str, Any]] = []
    for unit_id, unit_records in sorted(by_unit.items()):
        labels = units[unit_id].labels
        expected = {
            item["id"]: item for item in labels["incidents"] if item["signal_expected"]
        }
        lines_of: dict[str, set[str]] = {}
        for line in labels["lines"]:
            for incident in line["incidents"]:
                lines_of.setdefault(incident, set()).add(f"{unit_id}-{line['n']}")
            roles_n += int(line["role"] is not None)
        problem_lines = {
            line_id for incident in expected for line_id in lines_of.get(incident, set())
        }
        signals = [
            signal
            for record in unit_records
            for signal in record["signals"]
            if signal["disposition"] == "inbox"
        ]
        inbox_signals += len(signals)
        non_problem += sum(1 for signal in signals if not set(signal["line_ids"]) & problem_lines)
        predicted_roles = {
            line_id: role for record in unit_records for line_id, role in record["roles"].items()
        }
        for line in labels["lines"]:
            if line["role"] is not None:
                roles_ok += int(predicted_roles.get(f"{unit_id}-{line['n']}") == line["role"])
        for incident_id, incident in expected.items():
            incidents += 1
            own = lines_of.get(incident_id, set())
            hits = [signal for signal in signals if set(signal["line_ids"]) & own]
            if incident["danger_kind"]:
                danger_n += 1
                danger_found += int(any(signal["emergency"]["is"] for signal in hits))
            if not hits:
                missed.append(incident_id)
                continue
            captured += 1
            best = max(hits, key=lambda signal: len(set(signal["line_ids"]) & own))
            subtype_ok += int(best["subtype"] == incident["subtype"])
            category_ok += int(
                load_taxonomy().product_category(best["subtype"])
                == load_taxonomy().product_category(incident["subtype"])
            )
            scope_ok += int(best["scope"] == incident["location_scope"])
            if incident["entrance"]:
                entrance_n += 1
                entrance_ok += int(best["entrance"] == incident["entrance"])
            if incident["expected_route_type"]:
                route_n += 1
                got = _route_type(
                    best["subtype"], best["scope"], best["emergency"]["kinds"], directory
                )
                route_ok += int(got == incident["expected_route_type"])
                details.append(
                    {
                        "incident": incident_id,
                        "subtype": [incident["subtype"], best["subtype"]],
                        "scope": [incident["location_scope"], best["scope"]],
                        "route": [incident["expected_route_type"], got],
                    }
                )
    return {
        "incidents": incidents,
        "incident_capture": ratio(captured, incidents),
        "non_problem_signals": ratio(non_problem, inbox_signals),
        "subtype_accuracy": ratio(subtype_ok, captured),
        "category_accuracy": ratio(category_ok, captured),
        "scope_accuracy": ratio(scope_ok, captured),
        "entrance_accuracy": ratio(entrance_ok, entrance_n),
        "route_end_to_end": ratio(route_ok, route_n),
        "d3_danger_found": ratio(danger_found, danger_n),
        "role_accuracy": ratio(roles_ok, roles_n),
        "missed_incidents": missed,
        "route_details": details,
    }


def _intake_of(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Исход приёма по репликам; у прогонов P6 его нет."""
    intake = record.get("intake")
    return intake if isinstance(intake, list) else []


def summarize_d5(records: Sequence[dict[str, Any]], dataset: str = "d5") -> dict[str, Any]:
    units = {unit.id: unit for unit in load_units(dataset)}
    names = ("danger", "trap", "contextual")
    groups: dict[str, list[bool]] = {name: [] for name in names}
    rules_groups: dict[str, list[bool]] = {name: [] for name in names}
    alerts: dict[str, list[bool]] = {name: [] for name in names}
    memos: dict[str, list[bool]] = {name: [] for name in names}
    families: dict[str, dict[str, int]] = {}
    misses: list[str] = []
    false_alarms: list[str] = []
    trap_memos: list[str] = []
    has_intake = bool(records) and all("intake" in record for record in records)
    for record in records:
        labels = units[record["unit"]].labels
        group = labels["group"]
        alarm = any(signal["emergency"]["is"] for signal in record["signals"])
        rules_alarm = any(
            signal["emergency"]["is"] and "rules" in signal["emergency"]["sources"]
            for signal in record["signals"]
        )
        groups[group].append(alarm)
        rules_groups[group].append(rules_alarm)
        if labels["expected_danger"] and not alarm:
            misses.append(record["unit"])
        if not labels["expected_danger"] and alarm:
            false_alarms.append(record["unit"])
        intake = _intake_of(record)
        alert = any(item["alert"] for item in intake)
        memo = any(item["memo"] for item in intake)
        alerts[group].append(alert)
        memos[group].append(memo)
        if group == "trap" and memo:
            trap_memos.append(record["unit"])
        family = str(labels.get("family") or group)
        entry = families.setdefault(
            family, {"windows": 0, "alarm": 0, "rules_alarm": 0, "intake_alert": 0, "memo": 0}
        )
        entry["windows"] += 1
        entry["alarm"] += int(alarm)
        entry["rules_alarm"] += int(rules_alarm)
        entry["intake_alert"] += int(alert)
        entry["memo"] += int(memo)
    result: dict[str, Any] = {
        "danger_found": ratio(sum(groups["danger"]), len(groups["danger"])),
        "contextual_found": ratio(sum(groups["contextual"]), len(groups["contextual"])),
        "trap_false_alarms": ratio(sum(groups["trap"]), len(groups["trap"])),
        "rules_danger_found": ratio(sum(rules_groups["danger"]), len(rules_groups["danger"])),
        "rules_contextual_found": ratio(
            sum(rules_groups["contextual"]), len(rules_groups["contextual"])
        ),
        "rules_trap_false_alarms": ratio(sum(rules_groups["trap"]), len(rules_groups["trap"])),
        "misses": misses,
        "false_alarms": false_alarms,
    }
    if has_intake:
        result["intake"] = {
            "danger_alert": ratio(sum(alerts["danger"]), len(alerts["danger"])),
            "danger_memo": ratio(sum(memos["danger"]), len(memos["danger"])),
            "contextual_memo": ratio(sum(memos["contextual"]), len(memos["contextual"])),
            "trap_alert": ratio(sum(alerts["trap"]), len(alerts["trap"])),
            "trap_memo": ratio(sum(memos["trap"]), len(memos["trap"])),
            "trap_memo_units": trap_memos,
        }
        result["families"] = dict(sorted(families.items()))
    return result


def summarize_open_danger(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Новый вид при открытой опасности — отдельный сигнал; продолжение — без чужого вида."""
    units = {unit.id: unit for unit in load_units("open_danger_dev")}
    new_ok: list[str] = []
    new_fail: list[str] = []
    cont_ok: list[str] = []
    cont_fail: list[str] = []
    for record in records:
        unit = units[record["unit"]]
        own = {kind for item in unit.open_items for kind in item.danger_kinds}
        refs = {item.ref for item in unit.open_items}
        expected = set(unit.labels["expected_new_kinds"])
        fresh = {
            kind
            for signal in record["signals"]
            if signal["ref"] not in refs and signal["disposition"] == "inbox"
            for kind in signal["emergency"]["kinds"]
        }
        foreign = {
            kind for signal in record["signals"] for kind in signal["emergency"]["kinds"]
        } - own
        if unit.labels["group"] == "new_kind":
            (new_ok if fresh & expected else new_fail).append(record["unit"])
        else:
            (cont_fail if foreign else cont_ok).append(record["unit"])
    return {
        "new_kind_separate_signal": ratio(len(new_ok), len(new_ok) + len(new_fail)),
        "continuation_without_foreign_kind": ratio(len(cont_ok), len(cont_ok) + len(cont_fail)),
        "new_kind_missed": new_fail,
        "continuation_foreign_kind": cont_fail,
    }


def summarize_d3_intake(records: Sequence[dict[str, Any]], dataset: str) -> dict[str, Any]:
    """Путь приёма на репликах D3: размеченная опасность против остальных."""
    units = {unit.id: unit for unit in load_units(dataset)}
    danger_of = {
        f"{unit_id}-{line['n']}": line["danger"]
        for unit_id, unit in units.items()
        for line in unit.labels["lines"]
    }
    danger_lines = sum(1 for value in danger_of.values() if value)
    counts: Counter[str] = Counter()
    other_memo_lines: list[str] = []
    for record in records:
        for item in _intake_of(record):
            danger = bool(danger_of.get(item["line"]))
            counts["danger_alert" if danger else "other_alert"] += int(item["alert"])
            counts["danger_memo" if danger else "other_memo"] += int(item["memo"])
            if item["memo"] and not danger:
                other_memo_lines.append(item["line"])
    return {
        "danger_lines": danger_lines,
        "other_lines": len(danger_of) - danger_lines,
        "danger_lines_alert": counts["danger_alert"],
        "danger_lines_memo": counts["danger_memo"],
        "other_lines_alert": counts["other_alert"],
        "other_lines_memo": counts["other_memo"],
        "other_memo_lines": other_memo_lines,
    }


def summarize_calls(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    called = [record for record in records if record["provider_called"]]
    states = Counter(record["state"] for record in records)
    answered = [r for r in called if r["state"] in ("ok", "fallback_invalid_output")]
    ok = [r for r in called if r["state"] == "ok"]
    latencies = [r["latency_ms"] for r in ok]
    costs = [r["cost_rub"] for r in called if r["cost_rub"] is not None]
    tokens_in = [r["tokens_in"] for r in ok if r["tokens_in"] is not None]
    tokens_out = [r["tokens_out"] for r in ok if r["tokens_out"] is not None]
    reasoning = [
        ((r.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens")
        for r in ok
    ]
    reasoning_known = [value for value in reasoning if isinstance(value, int)]
    return {
        "windows": len(records),
        "calls": len(called),
        "states": dict(sorted(states.items())),
        "valid_json": ratio(len(ok), len(answered)),
        "timeouts": states.get("fallback_timeout", 0),
        "provider_errors": states.get("fallback_provider_error", 0),
        "p50_ms": _percentile(latencies, 0.5),
        "p95_ms": _percentile(latencies, 0.95),
        "p99_ms": _percentile(latencies, 0.99),
        "max_ms": max(latencies) if latencies else None,
        "rub_total": round(sum(costs), 4),
        "rub_per_window": round(sum(costs) / len(costs), 4) if costs else None,
        "tokens_in_mean": round(statistics.mean(tokens_in)) if tokens_in else None,
        "tokens_out_mean": round(statistics.mean(tokens_out)) if tokens_out else None,
        "reasoning_tokens_mean": (
            round(statistics.mean(reasoning_known)) if reasoning_known else None
        ),
        "quotes": ratio(
            sum(r["quotes_fabricated"] for r in ok), sum(r["quotes_total"] for r in ok)
        ),
        "dropped_fields": sum(r["dropped_fields"] for r in records),
        "audit": dict(
            sum((Counter(r["audit"]) for r in records), Counter())  # type: ignore[arg-type]
        ),
        "upstreams": dict(Counter(str(r.get("upstream")) for r in called)),
    }


def summarize(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    dataset = records[0]["dataset"] if records else ""
    result: dict[str, Any] = {
        "dataset": dataset,
        "config": records[0]["config"] if records else "",
        "calls": summarize_calls(records),
    }
    if dataset == "open_danger_dev":
        result["open_danger"] = summarize_open_danger(records)
    elif dataset in SINGLE_WINDOW:
        result["d5"] = summarize_d5(records, dataset)
    elif dataset:
        result["d3"] = summarize_d3(records, dataset)
        if all("intake" in record for record in records):
            result["d3"]["intake"] = summarize_d3_intake(records, dataset)
    return result


# ---------------------------------------------------------------- CLI


def _load_key() -> str | None:
    key = os.environ.get("LLM_API_KEY")
    if key:
        return key
    env = pathlib.Path(".env")
    if env.exists():
        for raw in env.read_text(encoding="utf-8").splitlines():
            name, _, value = raw.partition("=")
            if name.strip() == "LLM_API_KEY" and value.strip():
                return value.strip()
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="P6 evaluation: model vs rules on D3/D5")
    parser.add_argument("--dataset", choices=sorted(DATASETS))
    parser.add_argument("--config", choices=sorted(CONFIGS), default="rules")
    parser.add_argument("--run", help="run name; raw records go to p6-runs/<run>.jsonl")
    parser.add_argument("--units", help="comma-separated unit ids (subset)")
    parser.add_argument("--exclude-units", help="comma-separated unit ids to skip")
    parser.add_argument(
        "--rules-danger-only",
        action="store_true",
        help="only units with at least one window where rules found danger (A2)",
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--pace-seconds", type=float, default=0.0, help="pause before each model call (M1)"
    )
    parser.add_argument("--summarize", help="summarize an existing raw records file")
    parser.add_argument("--routes", action="store_true", help="router on the routing reference")
    parser.add_argument(
        "--slice", choices=sorted(SLICES), default="p6b", help="runs directory and call budget"
    )
    args = parser.parse_args()
    current = SLICES[args.slice]

    if args.routes:
        print(json.dumps(route_reference_accuracy(), ensure_ascii=False, indent=2))
        return
    if args.summarize:
        path = pathlib.Path(args.summarize)
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        print(json.dumps(summarize(records), ensure_ascii=False, indent=2))
        return

    config = CONFIGS[args.config]
    units = load_units(args.dataset)
    if args.units:
        wanted = set(args.units.split(","))
        units = [unit for unit in units if unit.id in wanted]
    if args.exclude_units:
        skipped = set(args.exclude_units.split(","))
        units = [unit for unit in units if unit.id not in skipped]
    if args.rules_danger_only:
        units = [
            unit
            for unit in units
            if any(rules_danger(window) for window in unit_windows(unit, args.dataset))
        ]
    api_key = budget = None
    if config.model is not None:
        api_key = _load_key()
        if not api_key:
            raise SystemExit("LLM_API_KEY не задан: вызов модели невозможен")
        budget = SliceBudget(current.ledger, max_calls=current.max_calls, max_rub=current.max_rub)
    run = args.run or f"{args.dataset}-{config.name}"
    records = asyncio.run(
        run_dataset(
            args.dataset,
            config,
            run=run,
            units=units,
            api_key=api_key,
            budget=budget,
            concurrency=args.concurrency if config.model else 8,
            pace_seconds=args.pace_seconds,
        )
    )
    current.runs.mkdir(parents=True, exist_ok=True)
    out = current.runs / f"{run}.jsonl"
    body = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in sorted(records, key=lambda item: (item["unit"], item["window"]))
    )
    out.write_bytes(body.encode("utf-8"))
    summary = summarize(records)
    (current.runs / f"{run}.summary.json").write_bytes(
        (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    brief = {key: value for key, value in summary.items() if key != "d3"}
    if "d3" in summary:
        brief["d3"] = {
            key: value
            for key, value in summary["d3"].items()
            if key not in ("route_details", "missed_incidents")
        }
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    if budget is not None:
        print(
            f"срез: {budget.calls}/{current.max_calls} вызовов, "
            f"{budget.rub:.2f}/{current.max_rub} ₽"
        )


if __name__ == "__main__":
    main()
