"""Модель под нагрузкой и при отказах — через штатную сборку (F1 §4.4, §4.5).

    uv run python evaluation/llm_load_run.py --run load-01 [--phase burst|parallel|failures]

Сборка — `build_ai` из настроек production: предохранитель, семафор
`LLM_MAX_CONCURRENCY`, дневной бюджет и токены минуты в PostgreSQL
(`PostgresBudgetGuard`, нужна своя база с миграциями в `DATABASE_URL`). После
429 окно откладывается как в конвейере (`passive_analysis`: 20–60 с, пока окну
меньше 150 с), затем — правила. Окна — синтетика из
`evaluation/probes/llm_probe_v1.jsonl`; тексты в итог не пишутся.

Фазы:
* `burst` — 30 окон за минуту (по одному каждые 2 с);
* `parallel` — 8 окон одновременно;
* `failures` — локально: неверный ключ (401), несуществующий хост (DNS),
  ответ 500 и медленный ответ дольше таймаута (заглушка на 127.0.0.1).

Ключ — `LLM_API_KEY` из окружения или `.env`, не печатается. Итог —
`evaluation/reports/load-runs/<run>.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import random
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domsignal.ai import (  # noqa: E402
    WindowInput,
    WindowLine,
    chat_memo_hits,
    screen_message_for_danger,
)
from domsignal.bootstrap import AiComposition, build_ai  # noqa: E402
from domsignal.db.session import create_engine, create_session_factory  # noqa: E402
from domsignal.services.ai_budget import estimate_tokens  # noqa: E402
from domsignal.settings import Settings  # noqa: E402
from evaluation.p6_eval import _load_key  # noqa: E402

PROBES = pathlib.Path("evaluation/probes/llm_probe_v1.jsonl")
RUNS = pathlib.Path("evaluation/reports/load-runs")
MAX_PROVIDER_CALLS = 90
DEFER_AGE_S, DEFER_MIN_S, DEFER_MAX_S = 150, 20, 60
calls = 0


def window(lines: list[str]) -> WindowInput:
    start = datetime.now(UTC) - timedelta(minutes=2)
    return WindowInput(
        channel="group_passive",
        lines=tuple(
            WindowLine(
                line_id=f"l{i}",
                author_ref=f"a{i % 2}",
                text=text,
                sent_at=start + timedelta(seconds=10 * i),
            )
            for i, text in enumerate(lines, start=1)
        ),
    )


async def one(ai: AiComposition, lines: list[str], *, defer: bool = True) -> dict[str, Any]:
    """Окно как в конвейере: резерв бюджета → разбор → отложить после 429."""
    global calls
    started = time.monotonic()
    retries = 0
    while True:
        win = window(lines)
        try:
            assert ai.budget is not None
            async with ai.budget.reserve(
                None, tokens=estimate_tokens([line.text for line in win.lines])
            ):
                analysis = await ai.analyzer.analyze(win)
        except Exception as exc:  # noqa: BLE001 - необработанное исключение — потеря окна
            return {"lost": type(exc).__name__}
        execution = analysis.execution
        calls += int(execution.provider_called)
        if (
            execution.state == "fallback_rate_limited"
            and defer
            and time.monotonic() - started < DEFER_AGE_S
        ):
            retries += 1
            hinted = execution.retry_after_s or DEFER_MIN_S
            await asyncio.sleep(min(max(hinted, DEFER_MIN_S), DEFER_MAX_S) + random.uniform(0, 5))
            continue
        memo = sum(
            bool(chat_memo_hits(screen_message_for_danger(line.text, line_id=line.line_id)))
            for line in win.lines
        )
        return {
            "mode": analysis.mode,
            "state": execution.state,
            "retries": retries,
            "latency_ms": execution.latency_ms,
            "total_ms": int((time.monotonic() - started) * 1000),
            "cost_rub": execution.cost_rub or 0.0,
            "signals": len(analysis.signals),
            "danger_hits": len(analysis.danger_hits),
            "memo_lines": memo,
        }


def summary(records: list[dict[str, Any]], ai: AiComposition) -> dict[str, Any]:
    done = [r for r in records if "lost" not in r]
    latencies = sorted(r["total_ms"] for r in done)
    provider = ai.analyzer.provider
    breaker = getattr(provider, "breaker", None)
    return {
        "windows": len(records),
        "lost": [r["lost"] for r in records if "lost" in r],
        "states": dict(Counter(r["state"] for r in done)),
        "model_share": round(sum(r["state"] == "ok" for r in done) / len(done), 3)
        if done
        else None,
        "retries": sum(r["retries"] for r in done),
        "windows_retried": sum(r["retries"] > 0 for r in done),
        "total_ms_p50": latencies[len(latencies) // 2] if latencies else None,
        "total_ms_max": latencies[-1] if latencies else None,
        "breaker_open_at_end": bool(breaker and breaker.is_open),
        "rate_limited_seen": getattr(breaker, "rate_limited", None),
        "danger_windows_with_memo": sum(r["danger_hits"] > 0 and r["memo_lines"] > 0 for r in done),
        "danger_windows": sum(r["danger_hits"] > 0 for r in done),
        "rub": round(sum(r["cost_rub"] for r in done), 4),
    }


def corpus() -> list[list[str]]:
    rows = [
        json.loads(line) for line in PROBES.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [row["lines"] for row in rows if row["group"] in {"category", "danger", "continuation"}]


async def burst(ai: AiComposition) -> dict[str, Any]:
    items = corpus()
    tasks = []
    for i in range(30):
        tasks.append(asyncio.create_task(one(ai, items[i % len(items)])))
        await asyncio.sleep(2)
    return summary(list(await asyncio.gather(*tasks)), ai)


async def parallel(ai: AiComposition) -> dict[str, Any]:
    items = corpus()[5:13]
    return summary(list(await asyncio.gather(*(one(ai, lines) for lines in items))), ai)


class Stub(BaseHTTPRequestHandler):
    mode = "500"
    delay = 0.0

    def do_POST(self) -> None:  # noqa: N802 - имя из http.server
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if Stub.mode == "slow":
            time.sleep(Stub.delay)
        body = b'{"error":"stub"}'
        self.send_response(500 if Stub.mode == "500" else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def log_message(self, *args: Any) -> None:
        return


async def failures(base: Settings, factory: Any) -> dict[str, Any]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stub = f"http://127.0.0.1:{server.server_address[1]}/v1"
    windows = [
        ["Во втором подъезде лифт стоит с утра"],
        ["На третьем этаже сильно пахнет газом у лифта"],
    ] * 3
    cases = {
        "401": {"llm_api_key": "invalid-key-for-local-probe"},
        "dns": {"llm_base_url": "https://no-such-host.invalid/v1"},
        "500": {"llm_base_url": stub},
        "slow": {"llm_base_url": stub},
    }
    out: dict[str, Any] = {}
    try:
        for name, update in cases.items():
            Stub.mode = name if name in {"500", "slow"} else "500"
            # Отказы провайдера проверяются без ограничителя токенов минуты: иначе
            # предыдущие случаи исчерпали бы минуту и вызов не дошёл бы до заглушки.
            ai = build_ai(base.model_copy(update={**update, "llm_tokens_per_minute": 0}), factory)
            Stub.delay = (ai.timeout_seconds or 20) + 5
            records = [await one(ai, lines, defer=False) for lines in windows]
            out[name] = summary(records, ai)
    finally:
        server.shutdown()
    return out


async def main_async(args: argparse.Namespace, settings: Settings) -> dict[str, Any]:
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    result: dict[str, Any] = {
        "run": args.run,
        "model": settings.llm_model,
        "started": datetime.now(UTC).isoformat(),
    }
    try:
        for phase in args.phase:
            if calls > MAX_PROVIDER_CALLS:
                result[phase] = "skipped: call cap"
                continue
            if phase == "failures":
                result[phase] = await failures(settings, factory)
            else:
                ai = build_ai(settings, factory)
                result[phase] = await (burst(ai) if phase == "burst" else parallel(ai))
            print(json.dumps({phase: result[phase]}, ensure_ascii=False), flush=True)
    finally:
        await engine.dispose()
    result["provider_calls"] = calls
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True)
    parser.add_argument("--phase", action="append", choices=["burst", "parallel", "failures"])
    args = parser.parse_args()
    args.phase = args.phase or ["burst", "parallel", "failures"]
    os.chdir(pathlib.Path(__file__).resolve().parents[1])
    key = _load_key()
    if not key:
        raise SystemExit("LLM_API_KEY не задан")
    settings = Settings(
        app_env="local",
        database_url=os.environ["DATABASE_URL"],
        llm_provider="openai_compatible",
        llm_api_key=key,
        llm_model=os.getenv("LLM_MODEL", "Qwen/Qwen3-30B-A3B"),
        llm_daily_call_budget=int(os.getenv("LLM_DAILY_CALL_BUDGET", "300")),
        llm_tokens_per_minute=int(os.getenv("LLM_TOKENS_PER_MINUTE", "80000")),
    )
    result = asyncio.run(main_async(args, settings))
    RUNS.mkdir(parents=True, exist_ok=True)
    (RUNS / f"{args.run}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    main()
