"""Нагрузочный прогон приёма и разбора (D2, D5; docs/SCALING.md).

Что делает:

* поднимает API отдельным процессом uvicorn (как в установке) на своей БД;
* создаёт K домов одной УК и K активных привязок чатов с включённым чтением;
* шлёт поток `message_created` через `/max/webhook` с секретом —
  синтетические фразы (поломки, бытовые реплики, опасность в известных чатах);
  ритм — сценарий D2 (`--lines`) или профиль реальных чатов (`--profile`,
  только распределения из `evaluation/d5_realdata.py`) со средним темпом
  `--rate` сообщений в секунду и всплесками по профилю;
* запускает воркеры отдельными процессами, как в Compose:
  `--ai-processes P --ai-concurrency C` — P процессов AI-пула по C циклов
  (`scripts/load_worker.py`), так же операционный пул; модель — фейк с
  задержкой P6 (p50 5,2 с, p95 7,5 с, хвост до 12 с), MAX — записывающий
  двойник, адрес MAX API недоступен: внешние сервисы не вызываются;
* `--broadcast` (прогон В): рассылка УК во все чаты, в середине — опасность;
* меряет: приём вебхука, окна (модель / правила), «окно закрыто → сигнал»,
  очереди раз в секунду, ожидание операционных задач, памятки, рост БД.

Запуск (своя PostgreSQL, не рабочая):

    DATABASE_URL=postgresql+asyncpg://.../domsignal_load \\
      uv run python scripts/load_ingest.py --chats 300 --profile <профиль.json> \\
      --rate 8 --duration 300 --ai-processes 2 --ai-concurrency 4 --i-own-this-database

Результат — JSON в stdout и `--out`. Скрипт отказывается работать с
APP_ENV=production и без явного `--i-own-this-database`.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import math
import os
import platform
import random
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
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
    "Согласен",
    "Кто сегодня дома, примите посылку, пожалуйста",
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
    sent: int = 0
    danger_sent_at: dict[str, float] = field(default_factory=dict)


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
        "PASSIVE_ANALYSIS_FALLBACK_SECONDS": "90",
        "LLM_DAILY_CALL_BUDGET": "100000",
        "LLM_CHAT_DAILY_SHARE": "1.0",
        "STATIC_DIR": "missing",
        "LLM_PROVIDER": "rules",
        "BROADCAST_DM_QUIET_HOURS": "",
        "DB_POOL_SIZE": str(args.db_pool_size),
        "DB_MAX_OVERFLOW": str(args.db_max_overflow),
        "AI_WORKER_CONCURRENCY": str(args.ai_concurrency),
        "OPERATIONAL_WORKER_CONCURRENCY": str(args.operational_concurrency),
    }


async def prepare(database_url: str, chats: int) -> tuple[list[str], dict[str, Any]]:
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
        await db.execute(
            text(
                "INSERT INTO organization_memberships (id, user_id, tenant_id, role, status) "
                "VALUES (:id, :u, :t, 'company_admin', 'active')"
            ),
            {"id": uuid4(), "u": admin, "t": tenant},
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
            # Тихие часы выключены: прогон идёт и ночью, а мерим очередь, не расписание.
            await db.execute(
                text(
                    "INSERT INTO chat_bindings (id, max_chat_id, connection_request_id, house_id, "
                    "management_id, scope_type, status, verified_at, verified_by_user_id, "
                    "binding_version, activated_at, passive_capture_enabled, "
                    "quiet_start_minute, quiet_end_minute) VALUES (:id, :c, :r, "
                    ":h, :m, 'house', 'active', :at, :u, 1, :act, true, 0, 0)"
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
    return chat_ids, {"tenant": tenant, "admin": admin}


# ------------------------------------------------------------------ поток


Event = tuple[float, str, int, str]


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


def scripted_events(chat_ids: list[str], args: argparse.Namespace) -> list[Event]:
    """Сценарий D2: у каждого чата `--lines` реплик за окно отправки."""
    rng = random.Random(args.seed)
    events: list[Event] = []
    for index, chat in enumerate(chat_ids):
        lines = script_for_chat(index, args.lines, rng, args.danger_every)
        at = rng.uniform(0, args.duration * 0.25)
        for line in lines:
            events.append((at, chat, 800000 + rng.randrange(40), line))
            at += rng.uniform(1, args.duration / max(args.lines, 1))
    return sorted(events)


class Quantile:
    """Обратная функция распределения по квантилям профиля (кусочно-линейная)."""

    def __init__(self, points: dict[str, float], low: float, high: float) -> None:
        pairs = sorted((float(key[1:]) / 100, float(value)) for key, value in points.items())
        self.shares = [0.0, *(share for share, _ in pairs), 1.0]
        self.values = [low, *(value for _, value in pairs), max(high, pairs[-1][1])]

    def sample(self, rng: random.Random) -> float:
        u = rng.random()
        index = max(1, bisect.bisect_left(self.shares, u))
        s0, s1 = self.shares[index - 1], self.shares[index]
        v0, v1 = self.values[index - 1], self.values[index]
        return v0 + (v1 - v0) * ((u - s0) / (s1 - s0) if s1 > s0 else 0)


def profile_events(chat_ids: list[str], args: argparse.Namespace) -> list[Event]:
    """Поток по профилю реальных чатов: окна-разговоры, всплески по минутам.

    Разговор (окно) начинается в случайном чате; число реплик — распределение
    «реплик в окне», паузы внутри — интервалы внутри окна (≤ тишины). Темп
    начала разговоров модулируется по минутам множителем из распределения
    сообщений в минуту (всплески). Средний темп — `--rate` сообщений в секунду.
    """
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    rng = random.Random(args.seed)
    sizes = {int(k): v for k, v in profile["lines_per_window_share"].items()}
    size_values = sorted(sizes)
    size_weights = [sizes[k] for k in size_values]
    mean_size = sum(k * w for k, w in zip(size_values, size_weights, strict=True)) / sum(
        size_weights
    )
    gaps = Quantile(profile["intervals_s"]["within_window"], 1.0, float(args.silence))
    per_minute = profile["bursts"]["per_minute_active"]
    burst = Quantile(per_minute, 1.0, float(profile["bursts"]["per_minute_max"]))
    burst_mean = statistics.fmean(burst.sample(random.Random(1)) for _ in range(5000))
    windows_per_second = args.rate / mean_size
    events: list[Event] = []
    t = 0.0
    minute_multiplier: dict[int, float] = {}
    danger_chats = {
        chat
        for index, chat in enumerate(chat_ids)
        if args.danger_every and index % args.danger_every == 0
    }
    danger_done: set[str] = set()
    while t < args.duration:
        minute = int(t // 60)
        if minute not in minute_multiplier:
            minute_multiplier[minute] = min(6.0, burst.sample(rng) / burst_mean)
        rate = windows_per_second * minute_multiplier[minute]
        t += rng.expovariate(rate)
        if t >= args.duration:
            break
        chat = rng.choice(chat_ids)
        size = rng.choices(size_values, size_weights)[0]
        problem = PROBLEMS[rng.randrange(len(PROBLEMS))]
        pool = [*problem, *rng.sample(CHATTER, 3)]
        at = t
        for position in range(size):
            line = pool[position % len(pool)]
            if (
                chat in danger_chats
                and chat not in danger_done
                and position == size // 2
                and t > args.duration * 0.1
            ):
                line = DANGER
                danger_done.add(chat)
            events.append((at, chat, 800000 + rng.randrange(40), line))
            at += gaps.sample(rng)
    # Опасность, которой не нашлось места в разговорах, — отдельной репликой.
    for chat in sorted(danger_chats - danger_done):
        events.append((rng.uniform(args.duration * 0.1, args.duration * 0.7), chat, 800001, DANGER))
    return sorted(events)


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
    if line == DANGER:
        samples.danger_sent_at.setdefault(chat, time.time())
    try:
        response = await client.post(
            "/max/webhook", json=payload, headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}
        )
        if response.status_code != 200:
            samples.webhook_errors += 1
    except httpx.HTTPError:
        samples.webhook_errors += 1
        return
    samples.sent += 1
    samples.webhook_ms.append((time.perf_counter() - started) * 1000)


async def traffic(base_url: str, events: list[Event], samples: Samples) -> None:
    limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
    async with httpx.AsyncClient(base_url=base_url, timeout=30, limits=limits) as client:
        start = time.monotonic()
        tasks = []
        for at, chat, actor, line in events:
            delay = at - (time.monotonic() - start)
            if delay > 0:
                await asyncio.sleep(delay)
            tasks.append(asyncio.create_task(send(client, chat, actor, line, samples)))
        await asyncio.gather(*tasks)


# -------------------------------------------------------------- измерения


async def sample_queues(database_url: str, samples: Samples, stop: asyncio.Event) -> None:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    started = time.monotonic()
    try:
        while not stop.is_set():
            async with engine.connect() as db:
                row = (
                    await db.execute(
                        text(
                            "SELECT count(*) FILTER (WHERE starts_with(kind, 'ai.')) AS ai, "
                            "count(*) FILTER (WHERE NOT starts_with(kind, 'ai.')) AS operational "
                            "FROM jobs WHERE status = 'pending' AND next_attempt_at <= now()"
                        )
                    )
                ).one()
                open_windows = await db.scalar(
                    text("SELECT count(*) FROM conversation_windows WHERE state <> 'done'")
                )
                deliveries = await db.scalar(
                    text(
                        "SELECT count(*) FROM notification_deliveries "
                        "WHERE status IN ('pending', 'retry_wait', 'processing')"
                    )
                )
            samples.queue.append(
                {
                    "t": round(time.monotonic() - started, 1),
                    "ai": int(row.ai),
                    "operational": int(row.operational),
                    "windows_not_done": int(open_windows or 0),
                    "deliveries_open": int(deliveries or 0),
                }
            )
            await asyncio.sleep(1)
    finally:
        await engine.dispose()


async def settled(database_url: str) -> bool:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as db:
            pending = await db.scalar(
                text(
                    "SELECT (SELECT count(*) FROM conversation_windows WHERE state <> 'done') + "
                    "(SELECT count(*) FROM jobs WHERE status IN ('pending', 'leased') AND kind "
                    "NOT IN ('chat.buffer.purge', 'jobs.cleanup', 'appeal.followup.tick', "
                    "'staff.digest.tick', 'reception.tick') "
                    "AND next_attempt_at <= now() + interval '5 seconds') + "
                    "(SELECT count(*) FROM notification_deliveries "
                    " WHERE status IN ('pending', 'retry_wait', 'processing'))"
                )
            )
        return int(pending or 0) == 0
    finally:
        await engine.dispose()


async def db_size(database_url: str) -> dict[str, int]:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as db:
            total = await db.scalar(text("SELECT pg_database_size(current_database())"))
            tables = {
                row.name: int(row.size)
                for row in await db.execute(
                    text(
                        "SELECT relname AS name, pg_total_relation_size(relid) AS size "
                        "FROM pg_catalog.pg_statio_user_tables"
                    )
                )
            }
        return {"_database": int(total or 0), **tables}
    finally:
        await engine.dispose()


async def measure(database_url: str, since: datetime) -> dict[str, Any]:
    from domsignal.db.session import create_engine

    engine = create_engine(database_url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as db:
            windows = (
                await db.execute(
                    text(
                        "SELECT extract(epoch FROM completed_at - closed_at) AS done, analyzed_by, "
                        "execution_state, completed_at, closed_at FROM conversation_windows "
                        "WHERE created_at >= :s AND closed_at IS NOT NULL "
                        "AND completed_at IS NOT NULL"
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
                        "AND NOT starts_with(kind, 'ai.') AND completed_at IS NOT NULL"
                    ),
                    {"s": since},
                )
            ).all()
            ai_wait = (
                await db.execute(
                    text(
                        "SELECT extract(epoch FROM completed_at - next_attempt_at) AS w FROM jobs "
                        "WHERE created_at >= :s AND status = 'succeeded' "
                        "AND starts_with(kind, 'ai.')"
                    ),
                    {"s": since},
                )
            ).all()
            deliveries = (
                await db.execute(
                    text(
                        "SELECT purpose, status, created_at, accepted_at, extract(epoch FROM "
                        "coalesce(accepted_at, updated_at) - created_at) AS d "
                        "FROM notification_deliveries WHERE created_at >= :s"
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
                        " (SELECT count(*) FROM signals WHERE created_at >= :s) AS signals,"
                        " (SELECT count(*) FROM signals WHERE created_at >= :s"
                        "  AND strength = 'critical') AS critical"
                    ),
                    {"s": since},
                )
            ).one()
    finally:
        await engine.dispose()
    by_kind: dict[str, list[float]] = {}
    for row in operational_wait:
        by_kind.setdefault(row.kind, []).append(float(row.w))
    model_ok = [r for r in windows if r.analyzed_by == "ai" and r.execution_state == "ok"]
    rules = [
        r
        for r in windows
        if r.analyzed_by == "fallback" or (r.execution_state or "").startswith("fallback")
    ]
    throughput = None
    if len(model_ok) >= 2:
        span = (
            max(r.completed_at for r in model_ok) - min(r.closed_at for r in model_ok)
        ).total_seconds()
        throughput = round(len(model_ok) / span * 3600, 1) if span > 0 else None
    memos = [r for r in deliveries if r.purpose == "chat_safety_memo"]
    broadcast = [r for r in deliveries if r.purpose == "broadcast_chat"]
    all_operational = [value for values in by_kind.values() for value in values]
    return {
        "stored": {
            "lines": counts.lines,
            "windows": counts.windows,
            "signals": counts.signals,
            "critical_signals": counts.critical,
        },
        "window_closed_to_analysis_done_s": summary([float(r.done) for r in windows]),
        "analyzed_by": {
            kind: sum(1 for r in windows if r.analyzed_by == kind) for kind in ("ai", "fallback")
        },
        "windows_by_model_ok": len(model_ok),
        "windows_by_rules": len(rules),
        "rules_share": round(len(rules) / len(windows), 4) if windows else None,
        "model_windows_per_hour": throughput,
        "window_closed_to_first_signal_s": summary([float(r.s) for r in to_signal]),
        "ai_job_wait_s": summary([float(r.w) for r in ai_wait]),
        "operational_job_wait_s": {
            "all": summary(all_operational),
            **{kind: summary(values) for kind, values in sorted(by_kind.items())},
        },
        "chat_deliveries": {
            "by_purpose_status": {
                f"{purpose}:{status}": sum(
                    1 for r in deliveries if r.purpose == purpose and r.status == status
                )
                for purpose, status in sorted({(r.purpose, r.status) for r in deliveries})
            },
            "memo_created_to_accepted_s": summary(
                [float(r.d) for r in memos if r.status == "accepted"]
            ),
            "broadcast_first_to_last_accepted_s": (
                round(
                    (
                        max(r.accepted_at for r in broadcast if r.accepted_at)
                        - min(r.accepted_at for r in broadcast if r.accepted_at)
                    ).total_seconds(),
                    1,
                )
                if any(r.accepted_at for r in broadcast)
                else None
            ),
            "_memo_accepted": [r.accepted_at for r in memos if r.accepted_at],
            "_broadcast_accepted": [r.accepted_at for r in broadcast if r.accepted_at],
        },
    }


# ------------------------------------------------------------- процессы


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


def start_workers(args: argparse.Namespace, workdir: Path) -> list[subprocess.Popen[bytes]]:
    processes: list[subprocess.Popen[bytes]] = []
    plan = [("operational", args.operational_processes, args.operational_concurrency)] + [
        ("ai", args.ai_processes, args.ai_concurrency)
    ]
    for pool, count, concurrency in plan:
        for number in range(count):
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "load_worker.py"),
                        "--pool",
                        pool,
                        "--concurrency",
                        str(concurrency),
                        "--seed",
                        str(args.seed * 100 + number),
                        "--stop-file",
                        str(workdir / "stop"),
                        "--report",
                        str(workdir / f"{pool}-{number}.json"),
                    ],
                    cwd=ROOT,
                    env={**os.environ, "LOG_LEVEL": "WARNING"},
                    stdout=subprocess.DEVNULL,
                    stderr=open(workdir / f"{pool}-{number}.err", "wb"),  # noqa: SIM115
                )
            )
    return processes


def proc_cpu_seconds(pid: int) -> float | None:
    """CPU процесса (Linux, /proc) — для отчёта о ресурсах."""
    stat = Path(f"/proc/{pid}/stat")
    if not stat.exists():
        return None
    fields = stat.read_text().rsplit(")", 1)[1].split()
    ticks = os.sysconf("SC_CLK_TCK")
    return (int(fields[11]) + int(fields[12])) / ticks


def proc_rss_mb(pid: int) -> float | None:
    status = Path(f"/proc/{pid}/status")
    if not status.exists():
        return None
    for line in status.read_text().splitlines():
        if line.startswith("VmHWM:"):
            return round(int(line.split()[1]) / 1024, 1)
    return None


async def broadcast_all(database_url: str, ids: dict[str, Any]) -> str:
    """Рассылка УК во все чаты через сервис продукта (как кнопка «Отправить»)."""
    from domsignal.bootstrap import build_container
    from domsignal.contracts.community import BroadcastConfirm, BroadcastCreate
    from domsignal.settings import get_settings

    get_settings.cache_clear()
    container = build_container(get_settings())
    try:
        async with container.session_factory() as session, session.begin():
            draft = await container.broadcasts.create(
                session,
                actor_id=ids["admin"],
                company_id=ids["tenant"],
                payload=BroadcastCreate(
                    kind="announcement",
                    topic="works",
                    title="Плановые работы (нагрузочный прогон)",
                    body="Синтетическое объявление для замера рассылки.",
                    channels=["chat"],
                ),
                idempotency_key=f"load-{uuid4().hex}",
            )
            await container.broadcasts.confirm(
                session,
                actor_id=ids["admin"],
                broadcast_id=draft.id,
                payload=BroadcastConfirm(expected_version=draft.version, service_only=True),
            )
        return str(draft.id)
    finally:
        await container.aclose()


def collect_reports(workdir: Path) -> tuple[list[dict[str, Any]], int]:
    """Отчёты воркеров (число вызовов модели) и число процессов с трассировкой ошибки."""
    reports = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(workdir.glob("*.json"))
    ]
    errors = sum(
        "Traceback" in path.read_text(encoding="utf-8", errors="replace")
        for path in workdir.glob("*.err")
    )
    shutil.rmtree(workdir, ignore_errors=True)
    return reports, errors


async def main_async(
    args: argparse.Namespace, database_url: str, chat_ids: list[str], ids: dict[str, Any]
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(seconds=5)
    base_url = f"http://127.0.0.1:{args.port}"
    workdir = Path(tempfile.mkdtemp(prefix="domsignal-load-"))
    size_before = await db_size(database_url)
    stop = asyncio.Event()
    samples = Samples()
    workers = start_workers(args, workdir)
    started = time.monotonic()
    broadcast_id = None
    danger_at_broadcast = None
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=1) as probe:
            for _ in range(60):
                try:
                    if (await probe.get("/ready")).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        sampler = asyncio.create_task(sample_queues(database_url, samples, stop))
        if args.broadcast:
            broadcast_id = await broadcast_all(database_url, ids)
            await asyncio.sleep(args.broadcast_danger_after)
            danger_at_broadcast = datetime.now(UTC)
            await traffic(base_url, [(0.0, chat_ids[len(chat_ids) // 2], 800001, DANGER)], samples)
        else:
            events = (
                profile_events(chat_ids, args) if args.profile else scripted_events(chat_ids, args)
            )
            await traffic(base_url, events, samples)
        sent_in = time.monotonic() - started
        drain_deadline = time.monotonic() + args.drain_timeout
        while time.monotonic() < drain_deadline:
            await asyncio.sleep(2)
            if await settled(database_url):
                break
        drained_in = time.monotonic() - started
        stop.set()
        await sampler
    finally:
        (workdir / "stop").write_text("stop")
        for process in workers:
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                process.kill()
    reports, errors = collect_reports(workdir)
    measured = await measure(database_url, since)
    size_after = await db_size(database_url)
    peak = {
        key: max((q[key] for q in samples.queue), default=0)
        for key in ("ai", "operational", "windows_not_done", "deliveries_open")
    }
    deliveries = measured["chat_deliveries"]
    memo_times = deliveries.pop("_memo_accepted")
    broadcast_times = deliveries.pop("_broadcast_accepted")
    broadcast_view = None
    if args.broadcast and danger_at_broadcast is not None:
        first_memo = min(memo_times) if memo_times else None
        broadcast_view = {
            "broadcast_id": broadcast_id,
            "chats": len(chat_ids),
            "danger_after_s": args.broadcast_danger_after,
            "broadcast_posts_accepted": len(broadcast_times),
            "broadcast_posts_before_danger": sum(t < danger_at_broadcast for t in broadcast_times),
            "broadcast_posts_between_danger_and_memo": (
                sum(danger_at_broadcast <= t < first_memo for t in broadcast_times)
                if first_memo
                else None
            ),
            "memo_accepted_after_danger_s": (
                round((first_memo - danger_at_broadcast).total_seconds(), 2) if first_memo else None
            ),
        }
    lines = measured["stored"]["lines"] or 1
    growth = size_after["_database"] - size_before["_database"]
    tables = sorted(
        (
            (name, size_after.get(name, 0) - size_before.get(name, 0))
            for name in size_after
            if not name.startswith("_")
        ),
        key=lambda item: -item[1],
    )[:8]
    danger_expected = len(samples.danger_sent_at)
    memos_ok = deliveries["by_purpose_status"].get("chat_safety_memo:accepted", 0)
    return {
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
        },
        "conditions": {
            "chats": args.chats,
            "mode": "broadcast" if args.broadcast else ("profile" if args.profile else "scripted"),
            "profile": Path(args.profile).name if args.profile else None,
            "rate_msgs_per_s": args.rate if args.profile else None,
            "lines_per_chat": None if args.profile else args.lines,
            "send_window_s": args.duration,
            "window_silence_s": args.silence,
            "window_max_lines": 6,
            "model_latency": "p50 5,2 с, p95 7,5 с, 2 % хвост 8–12 с (P6)",
            "operational": f"{args.operational_processes}×{args.operational_concurrency}",
            "ai": f"{args.ai_processes}×{args.ai_concurrency}",
            "db_pool": f"{args.db_pool_size}+{args.db_max_overflow}",
            "api": "uvicorn, 1 процесс",
            "max_api": "не вызывается (записывающий двойник, недоступный адрес)",
        },
        "sent": samples.sent,
        "sent_in_s": round(sent_in, 1),
        "mean_rate_msgs_per_s": round(samples.sent / sent_in, 2) if sent_in else None,
        "drained_in_s": round(drained_in, 1),
        "webhook_ms": summary(samples.webhook_ms),
        "webhook_errors": samples.webhook_errors,
        "worker_reports": reports,
        "worker_processes_with_traceback": errors,
        "model_calls": sum(r.get("model_calls", 0) for r in reports if r.get("pool") == "ai"),
        "queue_peak": peak,
        "queue_timeline_every_10s": samples.queue[::10],
        "danger": {
            "chats_with_danger": danger_expected,
            "memos_accepted": memos_ok,
            "memo_delivery_share": round(memos_ok / danger_expected, 4)
            if danger_expected
            else None,
        },
        "db_growth": {
            "bytes": growth,
            "bytes_per_message": round(growth / lines),
            "top_tables_bytes": dict(tables),
        },
        "broadcast": broadcast_view,
        **measured,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--chats", type=int, default=50)
    parser.add_argument("--lines", type=int, default=12)
    parser.add_argument("--duration", type=float, default=180, help="окно отправки, с")
    parser.add_argument("--silence", type=int, default=30, help="тишина окна, с (production 30)")
    parser.add_argument("--profile", default=None, help="профиль реальных чатов (JSON)")
    parser.add_argument("--rate", type=float, default=1.7, help="средний темп, сообщений/с")
    parser.add_argument("--ai-processes", type=int, default=1)
    parser.add_argument("--ai-concurrency", type=int, default=1)
    parser.add_argument("--operational-processes", type=int, default=1)
    parser.add_argument("--operational-concurrency", type=int, default=1)
    parser.add_argument("--db-pool-size", type=int, default=5)
    parser.add_argument("--db-max-overflow", type=int, default=10)
    parser.add_argument("--broadcast", action="store_true", help="прогон В: рассылка и опасность")
    parser.add_argument("--broadcast-danger-after", type=float, default=20.0)
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
    chat_ids, ids = asyncio.run(prepare(database_url, args.chats))
    api = start_api(args.port)
    try:
        result = asyncio.run(main_async(args, database_url, chat_ids, ids))
    finally:
        api_cpu = proc_cpu_seconds(api.pid)
        api_rss = proc_rss_mb(api.pid)
        api.terminate()
        api.wait(timeout=10)
    result["api_process"] = {"cpu_seconds": api_cpu, "peak_rss_mb": api_rss}
    text_out = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(text_out)
    if args.out:
        args.out.write_text(text_out + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
