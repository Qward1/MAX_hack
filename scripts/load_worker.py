"""Воркер нагрузочного прогона: тот же код пула, что в установке, но модель — фейк.

Запускается `scripts/load_ingest.py` отдельными процессами, как `worker` и
`ai-worker` в Compose: `--pool ai --concurrency 4` — один процесс с четырьмя
циклами `run_loops`. Модель — фейковый провайдер с задержкой по измерениям P6
(p50 5,2 с, p95 7,5 с, хвост до 12 с), MAX — записывающий двойник: внешние
сервисы не вызываются. Останавливается по SIGTERM/SIGINT или файлу `--stop-file`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Задержка модели по P6: p50 5,2 с, p95 7,5 с → σ = ln(7,5/5,2) / 1,645.
LATENCY_MEDIAN = 5.2
LATENCY_SIGMA = math.log(7.5 / 5.2) / 1.645
#: Хвост: 2 % вызовов — 8–12 с (dev P6c p95 12,0 с); не больше 12 с.
TAIL_SHARE = 0.02
LATENCY_CAP = 12.0


class SlowFakeProvider:
    """Фейковая модель: ответ «тишина» (сигналы дают правила), задержка как у P6."""

    def __init__(self, seed: int, scale: float = 1.0) -> None:
        from domsignal.ai.providers.fake import FakeProvider

        self.inner = FakeProvider("ok", cost_rub=0.06)
        self.random = random.Random(seed)
        self.scale = scale
        self.calls = 0
        self.model = "fake/load"

    def delay(self) -> float:
        if self.random.random() < TAIL_SHARE:
            return self.random.uniform(8.0, LATENCY_CAP) * self.scale
        value = LATENCY_MEDIAN * math.exp(self.random.gauss(0, LATENCY_SIGMA))
        return min(value, LATENCY_CAP) * self.scale

    async def analyze_window(self, request: Any) -> Any:
        self.calls += 1
        await asyncio.sleep(self.delay())
        return await self.inner.analyze_window(request)


def unique_messaging() -> Any:
    """Записывающий двойник MAX с уникальными id (повторные прогоны на одной БД)."""
    from domsignal.bot.messaging import SentMessage
    from tests.fakes.max_messaging import RecordingMaxMessagingProvider

    class UniqueRecording(RecordingMaxMessagingProvider):
        async def send_chat_message(self, chat_id: str, message: Any) -> SentMessage:
            return SentMessage(f"mid.load-{uuid4().hex}")

        async def send_personal_message(self, destination: str, message: Any) -> SentMessage:
            return SentMessage(f"mid.load-{uuid4().hex}")

        async def edit_message(self, message_id: str, message: Any) -> None:
            return None

    return UniqueRecording()


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    from domsignal.ai import WindowAnalyzer
    from domsignal.bootstrap import build_container
    from domsignal.logs import configure_logging
    from domsignal.settings import get_settings
    from domsignal.worker.main import install_stop_signals
    from domsignal.worker.pools import lease_seconds_for
    from domsignal.worker.runner import WorkerRunner, run_loops
    from tests.fakes.max_chat import FakeMaxChatProvider

    configure_logging()
    container = build_container(get_settings())
    provider = SlowFakeProvider(args.seed, args.latency_scale)
    if args.pool == "ai":
        from domsignal.ai.resilience import CircuitBreaker, ConcurrencyLimiter, ResilientProvider

        # Та же обёртка, что в установке: семафор на процесс, бюджет в PostgreSQL.
        container.passive_analysis.analyzer = WindowAnalyzer(
            ResilientProvider(  # type: ignore[arg-type]
                provider,  # type: ignore[arg-type]
                breaker=CircuitBreaker(),
                limiter=ConcurrencyLimiter(max(args.concurrency, 1)),
                budget=None,
            ),
            timeout_s=30,
        )
    container.notifications.provider = unique_messaging()
    container.chat_connections.provider = FakeMaxChatProvider()
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        lease_seconds=lease_seconds_for(args.pool, ai_lease_seconds=80, model_timeout_seconds=30),
        notifications=container.notifications,
        pool=args.pool,
    )
    stop = asyncio.Event()
    install_stop_signals(stop)

    async def watch_stop_file() -> None:
        while not stop.is_set():
            if args.stop_file and os.path.exists(args.stop_file):  # noqa: ASYNC240
                stop.set()
                return
            await asyncio.sleep(0.5)

    try:
        await asyncio.gather(
            run_loops(runner, concurrency=args.concurrency, stop=stop, idle_seconds=0.2),
            watch_stop_file(),
        )
    finally:
        await container.aclose()
    return {"pool": args.pool, "concurrency": args.concurrency, "model_calls": provider.calls}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pool", choices=("ai", "operational"), required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--latency-scale", type=float, default=1.0)
    parser.add_argument("--stop-file", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    if os.environ.get("APP_ENV") == "production":
        print("Нагрузочный воркер только на своей тестовой БД", file=sys.stderr)
        return 2
    result = asyncio.run(main_async(args))
    if args.report:
        Path(args.report).write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
