"""D5 §3 Г: настоящий провайдер под параллельной нагрузкой — потолок провайдера.

    uv run python evaluation/d5_provider_parallel.py --windows 60 --levels 4,8,1 \\
        --max-rub 15 --out evaluation/reports/2026-09-27-d5-provider-parallel.json

Окна — синтетика набора настройки `datasets/synthetic/d3_dialogs.v1.dev.jsonl`
(не контроль), через сторож `evaluation/guard.py`: реальные тексты модели не
отправляются. Профиль — как в production (`models.v1.yaml`, модель по
умолчанию или `--model`; M1: Cloud.ru, до M1 — openai/gpt-5-mini через polza).
Семафор ядра обходится: параллельность задаёт прогон, чтобы увидеть поведение
самого провайдера (задержка, 429, ошибки).
Каждый вызов учитывается в `SliceBudget`; лимит рублей — жёсткий.
Ключ читается из окружения или `.env` и нигде не печатается.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import pathlib
import random
import sys
import time
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evaluation.guard import SliceBudget, SliceBudgetExceeded  # noqa: E402
from evaluation.p6_eval import _load_key, load_units, unit_windows  # noqa: E402

LEDGER = pathlib.Path("evaluation/reports/2026-09-27-d5-ledger.json")


def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))], 3)


def provider(api_key: str, model: str) -> Any:
    from domsignal.ai.models import load_models
    from domsignal.ai.providers.openai_compatible import OpenAICompatibleProvider
    from domsignal.settings import LLM_BASE_URL

    profile = load_models().get(model)
    assert profile is not None, f"нет профиля {model} в models.v1.yaml"
    return OpenAICompatibleProvider(
        base_url=LLM_BASE_URL,
        api_key=api_key,
        model=model,
        schema_mode=profile.schema_mode,
        timeout_seconds=profile.timeout_seconds,
        max_tokens=profile.max_tokens,
        temperature=profile.temperature,
        extra_body=profile.extra_body,
        open_danger_extra_body=profile.open_danger_extra_body,
        price_rub_per_million=profile.price_rub_per_million,
    )


async def level(
    client: Any, windows: list[Any], concurrency: int, budget: SliceBudget
) -> dict[str, Any]:
    from pydantic import ValidationError

    from domsignal.ai.model_output import WindowModelOutput
    from domsignal.ai.providers.base import ProviderTimeout, ProviderUnavailable, build_request
    from domsignal.ai.taxonomy import load_taxonomy

    taxonomy = load_taxonomy()
    gate = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    costs: list[float] = []
    outcome: dict[str, int] = {
        "ok": 0,
        "invalid_json": 0,
        "timeout": 0,
        "http_429": 0,
        "http_other": 0,
        "error": 0,
    }
    stopped = False

    async def one(window: Any) -> None:
        nonlocal stopped
        async with gate:
            if stopped:
                return
            try:
                budget.reserve()
            except SliceBudgetExceeded:
                stopped = True
                return
            request, _ = build_request(window, taxonomy)
            started = time.perf_counter()
            cost: float | None = None
            try:
                result = await client.analyze_window(request)
                cost = result.cost_rub
                latencies.append(time.perf_counter() - started)
                try:
                    content = result.content
                    WindowModelOutput.model_validate(
                        json.loads(content) if isinstance(content, str) else content
                    )
                    outcome["ok"] += 1
                except (ValidationError, ValueError, TypeError):
                    outcome["invalid_json"] += 1
                if cost is not None:
                    costs.append(cost)
            except ProviderTimeout:
                outcome["timeout"] += 1
            except ProviderUnavailable as exc:
                outcome["http_429" if "429" in str(exc) else "http_other"] += 1
            except Exception:  # noqa: BLE001 - прогон считает, а не падает
                outcome["error"] += 1
            finally:
                budget.commit(f"d5-provider-c{concurrency}", cost)

    started = time.perf_counter()
    await asyncio.gather(*(one(window) for window in windows))
    wall = time.perf_counter() - started
    calls = sum(outcome.values())
    return {
        "concurrency": concurrency,
        "calls": calls,
        "outcomes": outcome,
        "latency_s": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "wall_s": round(wall, 1),
        "windows_per_hour": round(outcome["ok"] / wall * 3600) if wall else None,
        "valid_json_share": round(outcome["ok"] / calls, 4) if calls else None,
        "rub_per_window_mean": round(sum(costs) / len(costs), 4) if costs else None,
        "rub_total": round(sum(costs), 3),
        "stopped_by_budget": stopped,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    key = _load_key()
    if not key:
        raise SystemExit("LLM_API_KEY не задан")
    rng = random.Random(20260927)
    windows = [w for unit in load_units("d3_dev") for w in unit_windows(unit, "d3_dev")]
    rng.shuffle(windows)
    windows = windows[: args.windows]
    budget = SliceBudget(args.ledger, max_calls=args.max_calls, max_rub=args.max_rub)
    from domsignal.ai.models import load_models

    model = args.model or load_models().default_id
    assert model is not None
    client = provider(key, model)
    results = []
    try:
        for concurrency in args.levels:
            results.append(await level(client, windows, concurrency, budget))
    finally:
        await client.aclose()
    return {
        "label": "измерено: настоящий провайдер, синтетические окна набора настройки",
        "model": model,
        "provider": args.provider_label,
        "dataset": "datasets/synthetic/d3_dialogs.v1.dev.jsonl (не контроль)",
        "windows": len(windows),
        "levels": results,
        "slice_budget": {
            "calls": budget.calls,
            "rub": round(budget.rub, 3),
            "max_rub": args.max_rub,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--windows", type=int, default=60)
    parser.add_argument(
        "--levels", type=lambda v: [int(x) for x in v.split(",")], default=[4, 8, 1]
    )
    parser.add_argument("--max-rub", type=float, default=15.0)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--model", help="model id from models.v1.yaml; default — its default")
    parser.add_argument("--ledger", type=pathlib.Path, default=LEDGER)
    parser.add_argument("--provider-label", default="Cloud.ru Evolution Foundation Models")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_bytes(body.encode("utf-8"))
    sys.stdout.buffer.write(body.encode("utf-8"))


if __name__ == "__main__":
    main()
