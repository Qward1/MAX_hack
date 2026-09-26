"""D5 §1: параллельный разбор, очистка очереди, приоритет опасности, здоровье очереди.

Данные синтетические. Гонка claim — два «процесса» (два движка БД) по четыре
цикла забирают одну очередь: каждая задача выполнена ровно один раз.
"""

from __future__ import annotations

import asyncio
import random
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update

from domsignal.bootstrap import build_container
from domsignal.db.models import Job, User
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.dashboards import DashboardService
from domsignal.services.job_cleanup import JobCleanup
from domsignal.settings import Settings
from domsignal.worker.runner import WorkerRunner, run_loops
from tests.integration.d3_harness import announcement, chat, confirm, create, d3
from tests.integration.passive_harness import MEMO_LEAD

pytestmark = pytest.mark.integration

__all__ = ["d3"]

DANGER = "В подъезде сильно пахнет газом"


# ------------------------------------------------------------ гонка claim


async def test_parallel_loops_of_two_processes_process_each_job_once(
    integration_settings: Settings,
) -> None:
    containers = [build_container(integration_settings) for _ in range(2)]
    processed: list[str] = []
    all_done = asyncio.Event()
    in_flight = 0
    peak = 0

    async def handler(payload: dict[str, Any]) -> None:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(random.uniform(0, 0.01))
        processed.append(payload["n"])
        in_flight -= 1
        if len(processed) >= 120:
            all_done.set()

    async with containers[0].session_factory() as session, session.begin():
        repo = ReliabilityRepository(session)
        for number in range(120):
            await repo.add_job(kind="test.race", payload={"n": str(number)}, priority=10)
    stop = asyncio.Event()
    runners = [
        WorkerRunner(
            session_factory=container.session_factory,
            handlers={"test.race": handler},
            pool="operational",
        )
        for container in containers
    ]

    async def until_done() -> None:
        await all_done.wait()
        stop.set()

    try:
        await asyncio.wait_for(
            asyncio.gather(
                *(
                    run_loops(runner, concurrency=4, stop=stop, idle_seconds=0.05)
                    for runner in runners
                ),
                until_done(),
            ),
            timeout=60,
        )
        assert sorted(processed, key=int) == [str(n) for n in range(120)]
        assert len(set(processed)) == 120, "ни одна задача не выполнена дважды"
        assert peak > 1, "циклы действительно работали параллельно"
        async with containers[0].session_factory() as session:
            statuses = list(
                await session.scalars(select(Job.status).where(Job.kind == "test.race"))
            )
            attempts = list(
                await session.scalars(select(Job.attempts).where(Job.kind == "test.race"))
            )
        assert set(statuses) == {"succeeded"} and set(attempts) == {1}
    finally:
        for container in containers:
            await container.aclose()


async def test_stop_lets_the_started_job_finish(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    started = asyncio.Event()
    finished: list[str] = []
    stop = asyncio.Event()

    async def slow(payload: dict[str, Any]) -> None:
        started.set()
        await asyncio.sleep(0.3)
        finished.append(payload["n"])

    async with container.session_factory() as session, session.begin():
        repo = ReliabilityRepository(session)
        for number in range(3):
            await repo.add_job(kind="test.slow", payload={"n": str(number)}, priority=10)
    runner = WorkerRunner(session_factory=container.session_factory, handlers={"test.slow": slow})
    try:
        loops = asyncio.create_task(run_loops(runner, concurrency=1, stop=stop, idle_seconds=0.05))
        await started.wait()
        stop.set()
        await asyncio.wait_for(loops, timeout=5)
        assert finished == ["0"], "начатая задача дошла до конца, новые не взяты"
        async with container.session_factory() as session:
            rows = list(await session.scalars(select(Job).where(Job.kind == "test.slow")))
        assert sorted(job.status for job in rows) == ["pending", "pending", "succeeded"]
    finally:
        await container.aclose()


async def test_claim_uses_the_partial_pool_index(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    try:
        async with container.session_factory() as session:
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = "\n".join(
                row[0]
                for row in await session.execute(
                    text(
                        "EXPLAIN SELECT id FROM jobs WHERE jobs.status IN ('pending', 'leased') "
                        "AND next_attempt_at <= now() AND starts_with(jobs.kind, 'ai.') "
                        "ORDER BY priority, created_at LIMIT 1"
                    )
                )
            )
        assert "ix_jobs_claim_pool" in plan
    finally:
        await container.aclose()


# --------------------------------------------------------------- очистка


async def test_cleanup_removes_only_old_finished_jobs(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    now = datetime.now(UTC)
    rows = {
        "old_ok": ("succeeded", now - timedelta(days=15)),
        "fresh_ok": ("succeeded", now - timedelta(days=13)),
        "old_failed": ("failed", now - timedelta(days=31)),
        "fresh_failed": ("failed", now - timedelta(days=29)),
        "old_ok_2": ("succeeded", now - timedelta(days=40)),
        "old_ok_3": ("succeeded", now - timedelta(days=20)),
    }
    try:
        async with container.session_factory() as session, session.begin():
            for name, (status, completed) in rows.items():
                session.add(
                    Job(
                        kind="test.done",
                        payload={"name": name},
                        status=status,
                        completed_at=completed,
                        created_at=completed,
                    )
                )
            # Ожидающая и взятая задачи не удаляются, даже очень старые.
            session.add(
                Job(
                    kind="test.wait",
                    payload={"name": "pending"},
                    status="pending",
                    created_at=now - timedelta(days=90),
                )
            )
            session.add(
                Job(
                    kind="test.wait",
                    payload={"name": "leased"},
                    status="leased",
                    created_at=now - timedelta(days=90),
                    lease_until=now + timedelta(seconds=30),
                )
            )
        cleanup = JobCleanup(container.session_factory, batch_size=2)
        result = await cleanup.purge(now=now)
        assert (result.succeeded, result.failed) == (3, 1)
        assert result.batches >= 3, "удаление идёт пачками"
        async with container.session_factory() as session:
            left = sorted(row["name"] for row in await session.scalars(select(Job.payload)))
        assert left == ["fresh_failed", "fresh_ok", "leased", "pending"]
        # Повтор ничего не удаляет; задача переставляет себя на час.
        from domsignal.services.errors import RescheduleJob

        with pytest.raises(RescheduleJob) as moved:
            await cleanup.tick({}, now=now)
        assert moved.value.until == now + timedelta(hours=1)
    finally:
        await container.aclose()


# ----------------------------------------------- опасность раньше рассылки


async def add_chats(h: Any, count: int) -> None:
    """Ещё `count` домов УК t1 с активными чатами без тихих часов (как после A-07)."""
    now = datetime.now(UTC)
    async with h.container.session_factory() as session, session.begin():
        for index in range(count):
            house, management, request, binding = uuid4(), uuid4(), uuid4(), uuid4()
            chat_id = f"-9{index:06d}"
            await session.execute(
                text("INSERT INTO houses (id, name, address) VALUES (:id, :n, :a)"),
                {"id": house, "n": f"Дом {index}", "a": f"Синтетическая, {index + 10}"},
            )
            await session.execute(
                text(
                    "INSERT INTO house_managements (id, tenant_id, house_id, valid_from, status, "
                    "ticket_intake_enabled) VALUES (:id, :t, :h, :f, 'active', true)"
                ),
                {"id": management, "t": h.ids["t1"], "h": house, "f": now - timedelta(days=1)},
            )
            await session.execute(
                text(
                    "INSERT INTO max_chats (id, max_chat_id, type, title, is_channel, "
                    "bot_present, last_seen_at, binding_version) "
                    "VALUES (:id, :c, 'chat', :t, false, true, :at, 1)"
                ),
                {"id": uuid4(), "c": chat_id, "t": f"Чат {index}", "at": now},
            )
            await session.execute(
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
                    "u": h.ids["admin1"],
                    "tok": secrets.token_hex(32),
                    "exp": now + timedelta(minutes=15),
                    "c": chat_id,
                    "at": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO chat_bindings (id, max_chat_id, connection_request_id, house_id, "
                    "management_id, scope_type, status, verified_at, verified_by_user_id, "
                    "binding_version, activated_at, quiet_start_minute, quiet_end_minute) "
                    "VALUES (:id, :c, :r, :h, :m, 'house', 'active', :at, :u, 1, :act, 0, 0)"
                ),
                {
                    "id": binding,
                    "c": chat_id,
                    "r": request,
                    "h": house,
                    "m": management,
                    "at": now,
                    "u": h.ids["admin1"],
                    "act": now - timedelta(hours=1),
                },
            )


async def test_danger_goes_before_a_broadcast_to_a_thousand_chats(d3: Any) -> None:  # noqa: F811
    await chat(d3)
    await add_chats(d3, 999)
    async with d3.container.session_factory() as session, session.begin():
        # Оператор УК получает оповещения в личку: диалог с ботом начат.
        await session.execute(
            update(User).where(User.id == d3.ids["admin1"]).values(max_dialog_at=datetime.now(UTC))
        )
    order: list[str] = []
    messaging = d3.messaging
    send_chat, send_personal = messaging.send_chat_message, messaging.send_personal_message

    async def chat_post(chat_id: str, message: Any) -> Any:
        order.append("memo" if message.text.startswith(MEMO_LEAD) else "broadcast")
        return await send_chat(chat_id, message)

    async def personal(destination: str, message: Any) -> Any:
        order.append("personal")
        return await send_personal(destination, message)

    messaging.send_chat_message = chat_post
    messaging.send_personal_message = personal

    draft = await create(d3, announcement(channels=["chat"]))
    assert (await confirm(d3, draft)).status_code == 200
    # Рассылка запущена: задача раздала 1 000 постов, первые уже ушли.
    runner = d3.runner()
    at = datetime.now(UTC)
    for step in range(40):
        await runner.run_once(now=at + timedelta(milliseconds=200 * step))
    queued = await d3.scalar(
        text(
            "SELECT count(*) FROM notification_deliveries "
            "WHERE purpose = 'broadcast_chat' AND status = 'pending'"
        )
    )
    sent_before = order.count("broadcast")
    assert sent_before >= 1 and queued >= 900, (sent_before, queued)

    # Посреди рассылки в чате дома h1 — опасность.
    await d3.say(DANGER)
    after = len(order)
    later = at + timedelta(seconds=20)
    for step in range(6):
        await runner.run_once(now=later + timedelta(milliseconds=200 * step))
    tail = order[after:]
    assert tail[:2] == ["memo", "personal"] or tail[:2] == ["personal", "memo"], tail
    assert "broadcast" not in tail[:2]
    alert: UUID | None = await d3.scalar(
        text(
            "SELECT signal_id FROM notification_deliveries "
            "WHERE purpose = 'signal_alert' AND status = 'accepted'"
        )
    )
    assert alert is not None


# -------------------------------------------------------- здоровье очереди


async def test_queue_health_counts_pools_windows_and_budget(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    now = datetime.now(UTC)
    try:
        async with container.session_factory() as session, session.begin():
            repo = ReliabilityRepository(session)
            await repo.add_job(kind="ai.window.analyze", payload={}, priority=60)
            old = await repo.add_job(kind="signal.alert", payload={}, priority=10)
            old.next_attempt_at = now - timedelta(seconds=90)
            later = await repo.add_job(kind="jobs.cleanup", payload={}, priority=95)
            later.next_attempt_at = now + timedelta(hours=1)
            await session.execute(
                text("INSERT INTO ai_call_budget (day, scope_key, calls) VALUES (:d, '', 40)"),
                {"d": now.date()},
            )
        async with container.session_factory() as session, session.begin():
            dashboard = await DashboardService(
                100, container.zones, container.routing.directory
            ).platform(session, 7)
        queue = dashboard.queue
        assert queue is not None
        pools = {pool.pool: pool for pool in queue.pools}
        assert pools["ai"].due == 1 and pools["operational"].due == 1
        assert pools["operational"].scheduled == 1
        assert pools["operational"].oldest_due_seconds is not None
        assert pools["operational"].oldest_due_seconds >= 60
        assert queue.model_budget_today.used == 40 and queue.model_budget_today.share == 0.4
        assert (
            queue.windows_24h.total == 0
            and queue.windows_24h.share_rules_overload_or_budget is None
        )
        packs = {pack.pack: pack for pack in dashboard.directory}
        assert {"_federal", "RU-TA", "RU-MOW", "RU-PSK", "RU-PRI"} <= set(packs)
        assert packs["RU-PSK"].needs_verification >= 1
        assert packs["RU-MOW"].verified >= 1
        assert packs["RU-MOW"].unavailable_channels, "ПОС недоступен в Москве"
        assert not packs["RU-TA"].unavailable_channels
    finally:
        await container.aclose()
