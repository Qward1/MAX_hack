"""Локальный нагрузочный прогон приёма реплик (D2, docs/SCALING.md).

Что делает:

* поднимает API отдельным процессом uvicorn (как в установке: api отдельно
  от воркеров) на своей тестовой БД;
* создаёт K домов одной УК и K активных привязок чатов с включённым чтением;
* шлёт поток реплик `message_created` через `/max/webhook` с секретом
  (синтетические фразы: поломки, бытовые реплики, немного опасности);
* в этом же процессе крутит воркеры пулов `operational` (×N) и `ai` (×M);
  модель — фейковый провайдер с логнормальной задержкой (медиана 5 с, как у
  production), MAX — записывающий двойник, адрес MAX API — недоступный
  локальный порт: внешние сервисы не вызываются;
* меряет: p50/p95 приёма вебхука, время «окно закрыто → сигнал» и «окно
  закрыто → разбор завершён», глубину очередей пулов раз в секунду, ожидание
  задач операционного пула и доставку сообщений в чат (памятки опасности).

Запуск (своя PostgreSQL, не рабочая):

    DATABASE_URL=postgresql+asyncpg://.../domsignal_load \
      uv run python scripts/load_ingest.py --chats 50 --lines 12 --ai-workers 1

Результат — JSON в stdout и `--out` (по желанию). Скрипт отказывается
работать с APP_ENV=production и без явного `--i-own-this-database`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import random
import secrets
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WEBHOOK_SECRET = "synthetic-load-webhook-secret"
BOT_TOKEN = "synthetic-load-bot-token"
#: Недоступный адрес: случайный вызов MAX API падает локально, наружу не уходит.
DEAD_MAX_API = "https://127.0.0.1:9"

PROBLEMS = (
    (
        "Лифт во втором подъезде опять не работает",
        "Да, лифт стоит с утра",
        "Подтверждаю, лифт не едет",
    ),
    (
        "Во дворе не горит фонарь у третьего подъезда",
        "Фонарь не горит уже неделю",
        "Темно, фонарь сломан",
    ),
    ("Нет горячей воды с утра", "У нас тоже нет горячей воды", "Горячей воды нет во всём доме"),
    (
        "Протекает крыша на девятом этаже",
        "Опять течёт с потолка на лестнице",
        "Крыша течёт после дождя",
    ),
)
CHATTER = (
    "Доброе утро, соседи",
    "Кто-нибудь знает, когда собрание?",
    "Спасибо!",
    "Потерялся кот, рыжий, отзывается на Барсика",
    "Отдам детскую коляску бесплатно",
    "Во сколько сегодня приедет курьер?",
)
DANGER = "В подъезде сильно пахнет газом"


def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return round(ordered[index], 3)


def summary(values: list[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "max": round(max(values), 3) if values else None,
        "mean": round(statistics.fmean(values), 3) if values else None,
    }


@dataclass
class Samples:
    queue: list[dict[str, Any]] = field(default_factory=list)
    webhook_ms: list[float] = field(default_factory=list)
    webhook_errors: int = 0


class SlowFakeProvider:
    """Фейковая модель: ответ «тишина», задержка логнормальная (медиана `median` с)."""

    def __init__(self, median: float, sigma: float, seed: int) -> None:
        from domsignal.ai.providers.fake import FakeProvider

        self.inner = FakeProvider("ok", cost_rub=0.06)
        self.median = median
        self.sigma = sigma
        self.random = random.Random(seed)
        self.calls = 0
        self.model = "fake/load"

    async def analyze_window(self, request: Any) -> Any:
        self.calls += 1
        delay = self.median * math.exp(self.random.gauss(0, self.sigma))
        await asyncio.sleep(delay)
        result = await self.inner.analyze_window(request)
        return result


def unique_messaging() -> Any:
    """Записывающий двойник MAX с уникальными id сообщений.

    Двойник тестов нумерует сообщения `mid.chat-1, -2, …` заново в каждом
    процессе; повторные прогоны на одной БД упирались бы в уникальность
    `provider_message_id` (у настоящего MAX id уникальны).
    """
    from domsignal.bot.messaging import SentMessage
    from tests.fakes.max_messaging import RecordingMaxMessagingProvider

    class UniqueRecording(RecordingMaxMessagingProvider):
        async def send_chat_message(self, chat_id: str, message: Any) -> SentMessage:
            self.chat_sent.append((chat_id, "", message))
            return SentMessage(f"mid.load-{uuid4().hex}")

        async def send_personal_message(self, destination: str, message: Any) -> SentMessage:
            self.sent.append((destination, "", message))
            return SentMessage(f"mid.load-{uuid4().hex}")

    return UniqueRecording()


def settings_env(database_url: str, args: argparse.Namespace) -> dict[str, str]:
    return {
        "APP_ENV": "test",
        "DATABASE_URL": database_url,
        "SESSION_SECRET": "load-" + secrets.token_hex(8),
        "ALLOW_TEST_SESSION": "false",
        "DEMO_SEED": "false",
        "MAX_TRANSPORT": "webhook",
        "MAX_BOT_TOKEN": BOT_TOKEN,
        "MAX_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "MAX_API_BASE_URL": DEAD_MAX_API,
        "PASSIVE_CAPTURE_ENABLED": "true",
        "PASSIVE_LLM_ENABLED": "true",
        "PASSIVE_WINDOW_SILENCE_SECONDS": str(args.silence),
        "PASSIVE_WINDOW_MAX_LINES": "6",
        "LLM_DAILY_CALL_BUDGET": "100000",
        "LLM_CHAT_DAILY_SHARE": "1.0",
        "STATIC_DIR": "missing",
        "LLM_PROVIDER": "rules",
    }


async def prepare(database_url: str, chats: int) -> list[str]:
    """Дома, УК и активные привязки с чтением: как после подключения A-07."""
    from domsignal.db.session import create_engine

    engine = create_engine(database_url)
    now = datetime.now(UTC)
    tenant, admin = uuid4(), uuid4()
    run = int(time.time()) % 100000
    chat_ids = [f"-7{run:05d}{index:04d}" for index in range(chats)]
    async with engine.begin() as db:
        await db.execute(
            text("INSERT INTO management_companies (id, name, status) VALUES (:id, :n, 'active')"),
            {"id": tenant, "n": f"Нагрузка {now:%H%M%S}"},
        )
        await db.execute(
            text("INSERT INTO users (id, display_name) VALUES (:id, 'Нагрузка, администратор')"),
            {"id": admin},
        )
        for index, chat in enumerate(chat_ids):
            house, management, request, binding = uuid4(), uuid4(), uuid4(), uuid4()
            await db.execute(
                text("INSERT INTO houses (id, name, address) VALUES (:id, :n, :a)"),
                {"id": house, "n": f"Дом {index}", "a": f"Нагрузка {now:%H%M%S}, дом {index}"},
            )
            await db.execute(
                text(
                    "INSERT INTO house_managements (id, tenant_id, house_id, valid_from, status, "
                    "ticket_intake_enabled) VALUES (:id, :t, :h, :f, 'active', true)"
                ),
                {"id": management, "t": tenant, "h": house, "f": now - timedelta(days=1)},
            )
            await db.execute(
                text(
                    "INSERT INTO house_routing_profiles (house_id, region_code, municipality_code, "
                    "territory_policy) VALUES (:h, 'RU-TA', 'kazan', 'mixed')"
                ),
                {"h": house},
            )
            await db.execute(
                text(
                    "INSERT INTO max_chats (id, max_chat_id, type, title, is_channel, "
                    "bot_present, last_seen_at, binding_version) "
                    "VALUES (:id, :c, 'chat', :t, false, true, :at, 1)"
                ),
                {"id": uuid4(), "c": chat, "t": f"Чат дома {index}", "at": now},
            )
            await db.execute(
                text(
                    "INSERT INTO chat_connection_requests (id, management_id, house_id, "
                    "initiated_by_user_id, token_hash, expires_at, status, candidate_max_chat_id, "
                    "scope_type, completed_at) VALUES (:id, :m, :h, :u, :tok, :exp, 'completed', "
                    ":c, 'house', :at)"
                ),
                {
                    "id": request,
                    "m": management,
                    "h": house,
                    "u": admin,
                    "tok": secrets.token_hex(32),
                    "exp": now + timedelta(minutes=15),
                    "c": chat,
                    "at": now,
                },
            )
            await db.execute(
                text(
                    "INSERT INTO chat_bindings (id, max_chat_id, connection_request_id, house_id, "
                    "management_id, scope_type, status, verified_at, verified_by_user_id, "
                    "binding_version, activated_at, passive_capture_enabled) VALUES (:id, :c, :r, "
                    ":h, :m, 'house', 'active', :at, :u, 1, :act, true)"
                ),
                {
                    "id": binding,
                    "c": chat,
                    "r": request,
                    "h": house,
                    "m": management,
                    "at": now,
                    "u": admin,
                    "act": now - timedelta(hours=1),
                },
            )
    await engine.dispose()
    return chat_ids


def script_for_chat(
    index: int, lines: int, rng: random.Random, danger_every: int = 10
) -> list[str]:
    problem = PROBLEMS[index % len(PROBLEMS)]
    out: list[str] = []
    while len(out) < lines:
        out.extend(rng.sample(CHATTER, 2))
        out.extend(problem)
    out = out[:lines]
    if danger_every and index % danger_every == 0:
        out[len(out) // 2] = DANGER  # одна реплика об опасности на каждый N-й чат
    return out


async def send(
    client: httpx.AsyncClient, chat: str, actor: int, line: str, samples: Samples
) -> None:
    payload = {
        "update_type": "message_created",
        "timestamp": int(time.time() * 1000),
        "message": {
            "sender": {"user_id": actor, "is_bot": False},
            "recipient": {"chat_id": int(chat), "chat_type": "chat"},
            "body": {"mid": f"mid.load-{uuid4().hex}", "text": line},
        },
    }
    started = time.perf_counter()
    try:
        response = await client.post(
            "/max/webhook", json=payload, headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}
        )
        if response.status_code != 200:
            samples.webhook_errors += 1
    except httpx.HTTPError:
        samples.webhook_errors += 1
        return
    samples.webhook_ms.append((time.perf_counter() - started) * 1000)


async def traffic(
    base_url: str, chat_ids: list[str], args: argparse.Namespace, samples: Samples
) -> None:
    rng = random.Random(args.seed)
    events: list[tuple[float, str, int, str]] = []
    for index, chat in enumerate(chat_ids):
        lines = script_for_chat(index, args.lines, rng, args.danger_every)
        at = rng.uniform(0, args.duration * 0.25)
        for line in lines:
            events.append((at, chat, 800000 + rng.randrange(40), line))
            at += rng.uniform(1, args.duration / max(args.lines, 1))
    events.sort()
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits) as client:
        start = time.monotonic()
        tasks = []
        for at, chat, actor, line in events:
            delay = at - (time.monotonic() - start)
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(send(client, chat, actor, line, samples)))
        await asyncio.gather(*tasks)


async def worker_loop(runner: Any, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            handled = await runner.run_once()
        except Exception as exc:  # noqa: BLE001 - прогон продолжает мерить
            print(f"worker error: {type(exc).__name__}", file=sys.stderr)
            handled = False
        if not handled:
            await asyncio.sleep(0.5)


async def sample_queues(database_url: str, samples: Samples, stop: asyncio.Event) -> None:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url)
    started = time.monotonic()
    try:
        while not stop.is_set():
            async with engine.connect() as db:
                row = (
                    await db.execute(
                        text(
                            "SELECT count(*) FILTER (WHERE kind LIKE 'ai.%') AS ai, "
                            "count(*) FILTER (WHERE kind NOT LIKE 'ai.%') AS operational "
                            "FROM jobs WHERE status = 'pending' AND next_attempt_at <= now()"
                        )
                    )
                ).one()
                open_windows = await db.scalar(
                    text("SELECT count(*) FROM conversation_windows WHERE state <> 'done'")
                )
            samples.queue.append(
                {
                    "t": round(time.monotonic() - started, 1),
                    "ai": int(row.ai),
                    "operational": int(row.operational),
                    "windows_not_done": int(open_windows or 0),
                }
            )
            await asyncio.sleep(1)
    finally:
        await engine.dispose()


async def settled(database_url: str) -> bool:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url)
    try:
        async with engine.connect() as db:
            pending = await db.scalar(
                text(
                    "SELECT (SELECT count(*) FROM conversation_windows WHERE state <> 'done') + "
                    "(SELECT count(*) FROM jobs WHERE status = 'pending' AND kind <> "
                    "'chat.buffer.purge' AND next_attempt_at <= now() + interval '5 seconds')"
                )
            )
        return int(pending or 0) == 0
    finally:
        await engine.dispose()


async def measure(database_url: str, since: datetime) -> dict[str, Any]:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url)
    try:
        async with engine.connect() as db:
            windows = (
                await db.execute(
                    text(
                        "SELECT extract(epoch FROM completed_at - closed_at) AS done, analyzed_by, "
                        "execution_state FROM conversation_windows WHERE created_at >= :s "
                        "AND closed_at IS NOT NULL AND completed_at IS NOT NULL"
                    ),
                    {"s": since},
                )
            ).all()
            to_signal = (
                await db.execute(
                    text(
                        "SELECT extract(epoch FROM min(s.created_at) - w.closed_at) AS s "
                        "FROM signals s JOIN conversation_windows w ON w.id = s.window_id "
                        "WHERE w.created_at >= :s GROUP BY w.id, w.closed_at"
                    ),
                    {"s": since},
                )
            ).all()
            operational_wait = (
                await db.execute(
                    text(
                        "SELECT kind, extract(epoch FROM completed_at - next_attempt_at) AS w "
                        "FROM jobs WHERE created_at >= :s AND status = 'succeeded' "
                        "AND kind NOT LIKE 'ai.%' AND completed_at IS NOT NULL"
                    ),
                    {"s": since},
                )
            ).all()
            ai_wait = (
                await db.execute(
                    text(
                        "SELECT extract(epoch FROM completed_at - next_attempt_at) AS w FROM jobs "
                        "WHERE created_at >= :s AND status = 'succeeded' AND kind LIKE 'ai.%'"
                    ),
                    {"s": since},
                )
            ).all()
            deliveries = (
                await db.execute(
                    text(
                        "SELECT purpose, status, extract(epoch FROM coalesce(accepted_at, "
                        "updated_at) - created_at) AS d FROM notification_deliveries "
                        "WHERE created_at >= :s"
                    ),
                    {"s": since},
                )
            ).all()
            counts = (
                await db.execute(
                    text(
                        "SELECT"
                        " (SELECT count(*) FROM chat_messages WHERE received_at >= :s) AS lines,"
                        " (SELECT count(*) FROM conversation_windows WHERE created_at >= :s)"
                        " AS windows,"
                        " (SELECT count(*) FROM signals WHERE created_at >= :s) AS signals"
                    ),
                    {"s": since},
                )
            ).one()
    finally:
        await engine.dispose()
    by_kind: dict[str, list[float]] = {}
    for row in operational_wait:
        by_kind.setdefault(row.kind, []).append(float(row.w))
    return {
        "stored": {"lines": counts.lines, "windows": counts.windows, "signals": counts.signals},
        "window_closed_to_analysis_done_s": summary([float(r.done) for r in windows]),
        "analyzed_by": {
            kind: sum(1 for r in windows if r.analyzed_by == kind) for kind in ("ai", "fallback")
        },
        "window_closed_to_first_signal_s": summary([float(r.s) for r in to_signal]),
        "ai_job_wait_s": summary([float(r.w) for r in ai_wait]),
        "operational_job_wait_s": {
            kind: summary(values) for kind, values in sorted(by_kind.items())
        },
        "chat_deliveries": {
            "by_status": {
                status: sum(1 for r in deliveries if r.status == status)
                for status in sorted({r.status for r in deliveries})
            },
            "created_to_accepted_s": summary(
                [float(r.d) for r in deliveries if r.status == "accepted"]
            ),
        },
    }


def start_api(port: int) -> subprocess.Popen[bytes]:
    """API отдельным процессом, как в установке (api отдельно от воркеров)."""
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "domsignal.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=os.environ,
    )


async def main_async(
    args: argparse.Namespace, database_url: str, chat_ids: list[str]
) -> dict[str, Any]:
    from domsignal.ai import WindowAnalyzer
    from domsignal.bootstrap import build_container
    from domsignal.logs import configure_logging
    from domsignal.settings import get_settings
    from domsignal.worker.pools import lease_seconds_for
    from domsignal.worker.runner import WorkerRunner
    from tests.fakes.max_chat import FakeMaxChatProvider

    since = datetime.now(UTC) - timedelta(seconds=5)
    base_url = f"http://127.0.0.1:{args.port}"
    get_settings.cache_clear()
    configure_logging()  # журналы воркеров с полями ошибок, как в установке
    container = build_container(get_settings())
    provider = SlowFakeProvider(args.latency_median, args.latency_sigma, args.seed)
    container.passive_analysis.analyzer = WindowAnalyzer(provider)  # type: ignore[arg-type]
    container.notifications.provider = unique_messaging()
    container.chat_connections.provider = FakeMaxChatProvider()
    stop = asyncio.Event()
    samples = Samples()
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=1) as probe:
            for _ in range(60):
                try:
                    if (await probe.get("/ready")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        runners = [
            WorkerRunner(
                session_factory=container.session_factory,
                handlers=container.worker_handlers.mapping,
                notifications=container.notifications,
                pool="operational",
            )
            for _ in range(args.operational_workers)
        ] + [
            WorkerRunner(
                session_factory=container.session_factory,
                handlers=container.worker_handlers.mapping,
                lease_seconds=lease_seconds_for(
                    "ai", ai_lease_seconds=120, model_timeout_seconds=30
                ),
                pool="ai",
            )
            for _ in range(args.ai_workers)
        ]
        loops = [asyncio.create_task(worker_loop(r, stop)) for r in runners]
        sampler = asyncio.create_task(sample_queues(database_url, samples, stop))
        started = time.monotonic()
        await traffic(base_url, chat_ids, args, samples)
        sent_in = time.monotonic() - started
        drain_deadline = time.monotonic() + args.drain_timeout
        while time.monotonic() < drain_deadline:
            await asyncio.sleep(2)
            if await settled(database_url):
                break
        drained_in = time.monotonic() - started
        stop.set()
        await asyncio.gather(*loops, sampler)
    finally:
        await container.aclose()
    measured = await measure(database_url, since)
    peak = {
        key: max((q[key] for q in samples.queue), default=0)
        for key in ("ai", "operational", "windows_not_done")
    }
    return {
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
        },
        "conditions": {
            "chats": args.chats,
            "lines_per_chat": args.lines,
            "send_window_s": args.duration,
            "window_silence_s": args.silence,
            "window_max_lines": 6,
            "model_latency_median_s": args.latency_median,
            "model_latency_sigma": args.latency_sigma,
            "operational_workers": args.operational_workers,
            "ai_workers": args.ai_workers,
            "api": "uvicorn, 1 процесс",
            "max_api": "не вызывается (записывающий двойник, недоступный адрес)",
        },
        "sent_in_s": round(sent_in, 1),
        "drained_in_s": round(drained_in, 1),
        "webhook_ms": summary(samples.webhook_ms),
        "webhook_errors": samples.webhook_errors,
        "model_calls": provider.calls,
        "queue_peak": peak,
        "queue_timeline_every_10s": samples.queue[::10],
        **measured,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chats", type=int, default=50)
    parser.add_argument("--lines", type=int, default=12)
    parser.add_argument("--duration", type=float, default=180, help="окно отправки, с")
    parser.add_argument("--silence", type=int, default=30, help="тишина окна, с (production 30)")
    parser.add_argument("--latency-median", type=float, default=5.0)
    parser.add_argument("--latency-sigma", type=float, default=0.35)
    parser.add_argument("--ai-workers", type=int, default=1)
    parser.add_argument("--operational-workers", type=int, default=1)
    parser.add_argument("--drain-timeout", type=float, default=900)
    parser.add_argument("--port", type=int, default=8047)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--danger-every", type=int, default=10, help="опасность в каждом N-м чате")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--i-own-this-database", action="store_true", required=True)
    args = parser.parse_args()
    if os.environ.get("APP_ENV") == "production" or "prod" in os.environ.get("DATABASE_URL", ""):
        print("Нагрузочный прогон только на своей тестовой БД", file=sys.stderr)
        return 2
    database_url = os.environ.get("DATABASE_URL", "")
    os.environ.update(settings_env(database_url, args))
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True, env=os.environ
    )
    chat_ids = asyncio.run(prepare(database_url, args.chats))
    api = start_api(args.port)
    try:
        result = asyncio.run(main_async(args, database_url, chat_ids))
    finally:
        api.terminate()
        api.wait(timeout=10)
    text_out = json.dumps(result, ensure_ascii=False, indent=2)
    print(text_out)
    if args.out:
        args.out.write_text(text_out + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
