"""P6: оценка ядра на D3/D5 — режим модели против режима правил на тех же окнах.

    uv run python evaluation/p6_eval.py --dataset d3_dev --config gpt5mini_v1_low --run r01
    uv run python evaluation/p6_eval.py --dataset d5 --config rules --run r02
    uv run python evaluation/p6_eval.py --summarize evaluation/reports/p6-runs/r01.jsonl

Жёсткие правила (docs/decisions.md#p6-prereg-2026-09-23):

1. Во внешний API уходят только строки `datasets/synthetic/*` с `synthetic: true`
   (`evaluation.guard`); каталог `data/` не читается ни в каком виде.
2. Все вызовы модели идут через общий лимит среза `SliceBudget`
   (700 вызовов и 300 ₽ на весь срез, файл-счётчик в `evaluation/reports`).
3. holdout прогоняется один раз итоговой конфигурацией; промпт настраивается
   только на dev.

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
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from domsignal.ai import WindowAnalyzer, WindowInput, WindowLine  # noqa: E402
from domsignal.ai.contracts import OpenItem, WindowAnalysis  # noqa: E402
from domsignal.ai.providers.base import ProviderRequest, ProviderResult  # noqa: E402
from domsignal.ai.providers.openai_compatible import (  # noqa: E402
    DEFAULT_BASE_URL,
    OpenAICompatibleProvider,
)
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
    # D2 появляется только после сессии с добровольцами (evaluation/d2_convert.py).
    "d2": pathlib.Path("datasets/synthetic/d2_dialogs.v1.jsonl"),
}
RUNS_DIR = pathlib.Path("evaluation/reports/p6-runs")
LEDGER = pathlib.Path("evaluation/reports/2026-09-23-p6-ledger.json")
SLICE_MAX_CALLS = 700
SLICE_MAX_RUB = 300.0
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

    def extra_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self.effort is not None:
            body["reasoning"] = {"effort": self.effort}
        if self.provider_only:
            body["provider"] = {"only": list(self.provider_only), "allow_fallbacks": False}
        elif self.provider_order:
            body["provider"] = {"order": list(self.provider_order), "allow_fallbacks": True}
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
}


# ----------------------------------------------------------------- окна


@dataclass
class EvalUnit:
    """Поток одного диалога D3 или одно окно D5 — с эталоном."""

    id: str
    lines: list[WindowLine]
    labels: dict[str, Any]


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
        units.append(EvalUnit(id=row["id"], lines=lines, labels=row))
    return units


def unit_windows(unit: EvalUnit, dataset: str) -> list[WindowInput]:
    if dataset == "d5":
        return [WindowInput(channel="group_passive", lines=tuple(unit.lines))]
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


def build_provider(config: ModelConfig, api_key: str, tap: UsageTap) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(timeout=config.timeout_seconds, event_hooks={"response": [tap]})
    assert config.model is not None
    return OpenAICompatibleProvider(
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
        model=config.model,
        schema_mode="json_schema_strict",
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        extra_body=config.extra_body(),
        client=client,
        prompt_version=config.prompt,
        few_shot=config.few_shot,
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
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    open_items: list[OpenItem] = []
    counter = [0]
    windows = unit_windows(unit, dataset)
    for index, base in enumerate(windows):
        window = base.model_copy(update={"open_items": tuple(open_items)})
        tap = UsageTap()
        recorder: CallRecorder | None = None
        if config.model is None:
            analyzer = WindowAnalyzer()
        else:
            assert api_key is not None and budget is not None
            recorder = CallRecorder(build_provider(config, api_key, tap), budget, run)
            analyzer = WindowAnalyzer(recorder, timeout_s=config.timeout_seconds + 2)
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
                "prompt": analysis.versions.prompt,
                "model": analysis.versions.model,
                "quotes_total": quotes_total,
                "quotes_fabricated": quotes_fabricated,
                "dropped_fields": analysis.dropped_fields,
                "audit": dict(Counter(event.kind for event in analysis.audit_events)),
                "roles": {verdict.line_id: verdict.role for verdict in analysis.lines},
                "signals": _signal_record(analysis),
                "semantic_danger": [danger.kind for danger in analysis.semantic_danger],
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
) -> list[dict[str, Any]]:
    semaphore = asyncio.Semaphore(concurrency)
    stopped: list[str] = []

    async def one(unit: EvalUnit) -> list[dict[str, Any]]:
        async with semaphore:
            if stopped:
                return []
            try:
                return await run_unit(
                    unit, dataset, config, api_key=api_key, budget=budget, run=run
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


def summarize_d5(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    units = {unit.id: unit for unit in load_units("d5")}
    groups: dict[str, list[bool]] = {"danger": [], "trap": [], "contextual": []}
    misses: list[str] = []
    false_alarms: list[str] = []
    for record in records:
        labels = units[record["unit"]].labels
        alarm = any(signal["emergency"]["is"] for signal in record["signals"])
        groups[labels["group"]].append(alarm)
        if labels["expected_danger"] and not alarm:
            misses.append(record["unit"])
        if not labels["expected_danger"] and alarm:
            false_alarms.append(record["unit"])
    return {
        "danger_found": ratio(sum(groups["danger"]), len(groups["danger"])),
        "contextual_found": ratio(sum(groups["contextual"]), len(groups["contextual"])),
        "trap_false_alarms": ratio(sum(groups["trap"]), len(groups["trap"])),
        "misses": misses,
        "false_alarms": false_alarms,
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
    if dataset == "d5":
        result["d5"] = summarize_d5(records)
    elif dataset:
        result["d3"] = summarize_d3(records, dataset)
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
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--summarize", help="summarize an existing raw records file")
    parser.add_argument("--routes", action="store_true", help="router on the routing reference")
    args = parser.parse_args()

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
    api_key = budget = None
    if config.model is not None:
        api_key = _load_key()
        if not api_key:
            raise SystemExit("LLM_API_KEY не задан: вызов модели невозможен")
        budget = SliceBudget(LEDGER, max_calls=SLICE_MAX_CALLS, max_rub=SLICE_MAX_RUB)
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
        )
    )
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{run}.jsonl"
    body = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in sorted(records, key=lambda item: (item["unit"], item["window"]))
    )
    out.write_bytes(body.encode("utf-8"))
    summary = summarize(records)
    (RUNS_DIR / f"{run}.summary.json").write_bytes(
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
        print(f"срез: {budget.calls}/{SLICE_MAX_CALLS} вызовов, {budget.rub:.2f}/{SLICE_MAX_RUB} ₽")


if __name__ == "__main__":
    main()
