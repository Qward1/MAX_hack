"""Пробы модели через штатный конвейер (F1 §4.3): жёсткие условия и мягкие метки.

    uv run python evaluation/llm_probe_run.py --run probes-01 [--limit N] [--rules]

Путь каждой пробы — функции продукта, а не отдельный оценщик: маскирование и
запрос (`OpenAICompatibleProvider`, те же профиль модели и промпт, что у
production) → проверка ответа и слияние с правилами (`WindowAnalyzer`) →
памятка в чат по правилам приёма (`screen_message_for_danger`,
`chat_memo_hits`) → маршрут (`RoutingService` на справочнике `regions/`) →
DTO явного пути (`decide_explicit_report`). Исходящее тело запроса
перехватывается: в нём не должно быть телефонов, почты и номеров карт.

Только синтетика `evaluation/probes/llm_probe_v1.jsonl` (`synthetic: true`);
реальные тексты не используются. Все вызовы — через общий лимит среза
`SliceBudget` (срез `f1probes`, ≤ 40 ₽). Итог — `evaluation/reports/probes-runs/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from domsignal.ai import (  # noqa: E402
    WindowAnalyzer,
    WindowInput,
    WindowLine,
    chat_memo_hits,
    decide_explicit_report,
    screen_message_for_danger,
)
from domsignal.services.routing import RoutingService, load_directory  # noqa: E402
from evaluation.guard import SliceBudget  # noqa: E402
from evaluation.p6_eval import CONFIGS, HOUSE, CallRecorder, UsageTap, _load_key  # noqa: E402

PROBES = pathlib.Path("evaluation/probes/llm_probe_v1.jsonl")
RUNS = pathlib.Path("evaluation/reports/probes-runs")
LEDGER = pathlib.Path("evaluation/reports/2026-09-28-f1-probes-ledger.json")
MAX_CALLS, MAX_RUB = 150, 40.0
CONFIG = CONFIGS["qwen3_30b_v3"]

PII = [
    re.compile(r"\+?[78][\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)"),
]
LEAK = re.compile(r"(системн\w* промпт|system prompt|инструкци\w* разбора|<think>)", re.I)


class RequestTap:
    """Запоминает тело последнего исходящего запроса к модели."""

    def __init__(self) -> None:
        self.bodies: list[str] = []

    async def __call__(self, request: httpx.Request) -> None:
        self.bodies.append(request.content.decode("utf-8", "replace"))


def window(probe: dict[str, Any]) -> WindowInput:
    start = datetime.now(UTC) - timedelta(minutes=3)
    lines = tuple(
        WindowLine(
            line_id=f"p{i}",
            author_ref=f"author-{i % 3}",
            text=text,
            sent_at=start + timedelta(seconds=15 * i),
        )
        for i, text in enumerate(probe["lines"], start=1)
    )
    return WindowInput(channel=probe.get("channel", "group_passive"), lines=lines)


async def run_probe(
    probe: dict[str, Any], *, key: str | None, budget: SliceBudget | None, routing: RoutingService
) -> dict[str, Any]:
    requests = RequestTap()
    usage = UsageTap()
    recorder = None
    if key is not None and budget is not None:
        from evaluation.p6_eval import build_provider

        provider = build_provider(CONFIG, key, usage)
        provider._client.event_hooks["request"] = [requests]  # noqa: SLF001 - перехват тела
        recorder = CallRecorder(provider, budget, "probes")
        analyzer = WindowAnalyzer(recorder, timeout_s=CONFIG.timeout_seconds + 2)
    else:
        analyzer = WindowAnalyzer()
    record: dict[str, Any] = {"id": probe["id"], "group": probe["group"], "expect": probe["expect"]}
    started = time.perf_counter()
    try:
        win = window(probe)
        analysis = await analyzer.analyze(win)
    except Exception as exc:  # noqa: BLE001 - необработанное исключение — провал пробы
        record["exception"] = type(exc).__name__
        return record
    finally:
        if recorder is not None:
            await recorder.inner.aclose()
    execution = analysis.execution
    memo_lines = sum(
        bool(chat_memo_hits(screen_message_for_danger(line.text, line_id=line.line_id)))
        for line in win.lines
    )
    signals = []
    for signal in analysis.signals:
        route = routing.route(
            subtype=signal.subtype,
            location_scope=signal.location_scope.value,
            house=HOUSE,
            danger_kinds=signal.emergency.kinds,
        )
        signals.append(
            {
                "subtype": signal.subtype,
                "category": signal.product_category.value,
                "danger": sorted(str(kind) for kind in signal.emergency.kinds),
                "memo_allowed": signal.emergency.memo_allowed,
                "route": route.route_type,
            }
        )
    decision = decide_explicit_report(analysis) if probe.get("channel") == "dm_report" else None
    body = requests.bodies[-1] if requests.bodies else ""
    record.update(
        mode=analysis.mode,
        state=execution.state,
        called=execution.provider_called,
        model=execution.provider_model,
        latency_ms=int((time.perf_counter() - started) * 1000),
        cost_rub=execution.cost_rub,
        signals=signals,
        danger_hits=len(analysis.danger_hits),
        memo_lines=memo_lines,
        dropped_fields=analysis.dropped_fields,
        explicit=(
            {"category": decision.product_category.value, "subtype": decision.subtype}
            if decision
            else None
        ),
        request_chars=len(body),
        pii_in_request=[p.pattern[:12] for p in PII if p.search(body)] if body else [],
        think_in_output=bool(usage.last.get("think")),
        leak=bool(LEAK.search(json.dumps(record.get("signals", []), ensure_ascii=False))),
    )
    return record


def hard(records: list[dict[str, Any]]) -> dict[str, Any]:
    called = [r for r in records if r.get("called")]
    ok = [r for r in called if r.get("state") == "ok"]
    exceptions = [r["id"] for r in records if r.get("exception")]
    slow = [r["id"] for r in called if r.get("latency_ms", 0) > 20000 and r.get("state") == "ok"]
    pii = [r["id"] for r in records if r.get("pii_in_request")]
    danger_lost = [
        r["id"]
        for r in records
        if r["expect"].get("danger") and r["expect"].get("memo") and not r.get("memo_lines")
    ]
    trap_memo = [r["id"] for r in records if r["group"] == "d6_trap" and r.get("memo_lines")]
    edge_called = [
        r["id"]
        for r in records
        if r["expect"].get("no_model_or_out_of_scope") and r.get("called") and r.get("signals")
    ]
    inject_fail = [
        r["id"]
        for r in records
        if r["expect"].get("injection")
        and (
            r.get("exception")
            or r.get("leak")
            or (r["expect"].get("danger") and not (r.get("danger_hits") or r.get("memo_lines")))
        )
    ]
    return {
        "probes": len(records),
        "model_calls": len(called),
        "unhandled_exceptions": exceptions,
        "valid_json_share": round(len(ok) / len(called), 4) if called else None,
        "non_ok_states": sorted({r.get("state") for r in called if r.get("state") != "ok"}),
        "slow_over_20s": slow,
        "pii_in_request": pii,
        "danger_without_memo": danger_lost,
        "d6_trap_memo": trap_memo,
        "empty_or_emoji_with_signals": edge_called,
        "injection_failures": inject_fail,
        "rub": round(sum(r.get("cost_rub") or 0 for r in records), 4),
    }


def soft(records: list[dict[str, Any]]) -> dict[str, Any]:
    def share(hit: int, total: int) -> str:
        return f"{hit}/{total}"

    problem = [
        r for r in records if r["expect"].get("problem") is not None and not r.get("exception")
    ]
    problem_hit = sum(bool(r.get("signals")) == r["expect"]["problem"] for r in problem)
    sub = [r for r in records if r["expect"].get("subtype") and r.get("signals")]
    sub_hit = sum(any(s["subtype"] == r["expect"]["subtype"] for s in r["signals"]) for r in sub)
    route = [r for r in records if r["expect"].get("route") and r.get("signals")]
    route_hit = 0
    for r in route:
        wanted = r["expect"]["route"]
        got = {s["route"] for s in r["signals"]}
        route_hit += any(
            (wanted == "uk" and g == "uk_internal")
            or (wanted == "external" and g not in {"uk_internal", "unknown"})
            for g in got
        )
    danger = [r for r in records if r["expect"].get("danger")]
    danger_hit = sum(
        bool(r.get("danger_hits") or any(s["danger"] for s in r.get("signals", []))) for r in danger
    )
    return {
        "problem_detected_as_expected": share(problem_hit, len(problem)),
        "subtype_among_detected": share(sub_hit, len(sub)),
        "route_among_detected": share(route_hit, len(route)),
        "danger_found": share(danger_hit, len(danger)),
    }


async def run_all(
    probes: list[dict[str, Any]], args: argparse.Namespace, routing: RoutingService
) -> list[dict[str, Any]]:
    key = budget = None
    if not args.rules:
        key = _load_key()
        if not key:
            raise SystemExit("LLM_API_KEY не задан")
        budget = SliceBudget(LEDGER, max_calls=MAX_CALLS, max_rub=MAX_RUB)
    records = []
    for probe in probes:
        if not args.rules and args.pace:
            await asyncio.sleep(args.pace)
        records.append(await run_probe(probe, key=key, budget=budget, routing=routing))
    return records


def run_and_report(args: argparse.Namespace) -> None:
    lines = PROBES.read_text(encoding="utf-8").splitlines()
    probes = [json.loads(line) for line in lines if line.strip()]
    if any(not probe.get("synthetic") for probe in probes):
        raise SystemExit("probe set must be synthetic only")
    if args.limit:
        probes = probes[: args.limit]
    routing = RoutingService(load_directory(pathlib.Path("regions")))
    records = asyncio.run(run_all(probes, args, routing))
    RUNS.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    (RUNS / f"{args.run}.jsonl").write_text(body, encoding="utf-8")
    summary = {
        "run": args.run,
        "mode": "rules" if args.rules else CONFIG.name,
        "hard": hard(records),
        "soft": soft(records),
    }
    (RUNS / f"{args.run}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rules", action="store_true", help="без модели: только правила")
    parser.add_argument("--pace", type=float, default=4.0, help="пауза перед вызовом (лимит TPM)")
    args = parser.parse_args()
    os.chdir(pathlib.Path(__file__).resolve().parents[1])
    run_and_report(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    main()
