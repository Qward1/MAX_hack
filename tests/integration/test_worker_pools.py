"""Изоляция нагрузки LLM: пул забирает только свои виды задач.

Смысл проверки в том, что деградация AI не касается доставки уведомлений и
жизненного цикла Ticket: они в другом пуле и другом процессе.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import Job
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.settings import Settings
from domsignal.worker.pools import lease_seconds_for
from domsignal.worker.runner import WorkerRunner


async def _enqueue(container: object, kinds: list[str]) -> None:
    factory = container.session_factory  # type: ignore[attr-defined]
    async with factory() as session, session.begin():
        repo = ReliabilityRepository(session)
        for kind in kinds:
            await repo.add_job(kind=kind, payload={}, priority=10)


@pytest.mark.integration
async def test_operational_pool_never_claims_ai_jobs(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    await _enqueue(container, ["ai.report.analyze"])
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        pool="operational",
    )
    assert await runner.claim() is None
    async with container.session_factory() as session:
        job = await session.scalar(select(Job))
        assert job is not None
        assert job.status == "pending" and job.attempts == 0
    await container.engine.dispose()


@pytest.mark.integration
async def test_ai_pool_claims_only_ai_jobs(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    await _enqueue(container, ["max.ticket.answer", "ai.report.analyze"])
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        pool="ai",
    )
    claimed = await runner.claim()
    assert claimed is not None and claimed.kind == "ai.report.analyze"
    # Больше в AI-пуле работы нет: операционная задача осталась нетронутой.
    assert await runner.claim() is None
    await container.engine.dispose()


@pytest.mark.integration
async def test_ai_pool_does_not_deliver_notifications(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    calls: list[str] = []

    async def consume() -> bool:
        calls.append("consume")
        return False

    async def deliver(*, now: datetime | None = None) -> bool:
        calls.append("deliver")
        return False

    container.notifications.consume_once = consume  # type: ignore[method-assign]
    container.notifications.deliver_once = deliver  # type: ignore[method-assign]

    ai_runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        notifications=container.notifications,
        pool="ai",
    )
    assert await ai_runner.run_once() is False
    assert calls == []

    operational = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        notifications=container.notifications,
        pool="operational",
    )
    await operational.run_once()
    assert calls == ["consume", "deliver"]
    await container.engine.dispose()


@pytest.mark.integration
async def test_unknown_kind_is_still_claimed_and_failed_by_its_pool(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    await _enqueue(container, ["totally.unknown"])
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        max_attempts=1,
        pool="operational",
    )
    assert await runner.run_once()
    async with container.session_factory() as session:
        job = await session.scalar(select(Job))
        assert job is not None
        assert job.status == "failed"
        assert job.last_error_code == "LookupError"
    await container.engine.dispose()


@pytest.mark.integration
async def test_default_pool_is_operational(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    await _enqueue(container, ["ai.report.analyze"])
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
    )
    assert runner.pool == "operational"
    assert await runner.claim() is None
    await container.engine.dispose()


@pytest.mark.integration
async def test_claim_job_without_a_pool_still_sees_every_kind(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    await _enqueue(container, ["ai.report.analyze"])
    async with container.session_factory() as session, session.begin():
        job = await ReliabilityRepository(session).claim_job(
            now=datetime.now(UTC), lease_seconds=5
        )
        assert job is not None and job.kind == "ai.report.analyze"
    await container.engine.dispose()


# ------------------------------------------------ аренда AI-пула и долгий вызов (P7a)

#: Таймаут модели в production и запас фасада анализатора сверх него.
PRODUCTION_MODEL_TIMEOUT = 25
ANALYZER_MARGIN = 2


class _LongProviderCall:
    """Обработчик `ai.window.analyze`, чей вызов провайдера длится, пока его держат."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def __call__(self, payload: dict[str, Any]) -> None:
        self.calls += 1
        self.started.set()
        await self.release.wait()


async def _race(container: Any, lease_seconds: int, second_claim_after: int) -> tuple[Any, bool]:
    """Первый воркер держит задачу в вызове модели, второй пытается её взять."""
    await _enqueue(container, ["ai.window.analyze"])
    call = _LongProviderCall()
    handlers = {"ai.window.analyze": call}
    first, second = (
        WorkerRunner(
            session_factory=container.session_factory,
            handlers=handlers,
            lease_seconds=lease_seconds,
            pool="ai",
        )
        for _ in range(2)
    )
    started_at = datetime.now(UTC)
    claimed = await first.claim(now=started_at)
    assert claimed is not None
    processing = asyncio.create_task(first.process(claimed))
    await call.started.wait()
    taken = await second.claim(now=started_at + timedelta(seconds=second_claim_after))
    call.release.set()
    completed = await processing
    assert call.calls == 1
    return taken, completed


@pytest.mark.integration
async def test_ai_job_is_not_taken_over_mid_call_with_the_configured_lease(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    lease = lease_seconds_for(
        "ai",
        ai_lease_seconds=integration_settings.ai_worker_lease_seconds,
        model_timeout_seconds=PRODUCTION_MODEL_TIMEOUT,
    )
    assert lease == 60
    # Вызов модели оборвётся не позже таймаута и запаса фасада; сверх того
    # воркер ещё пишет результат — второй воркер задачу не получает.
    taken, completed = await _race(
        container, lease, second_claim_after=PRODUCTION_MODEL_TIMEOUT + ANALYZER_MARGIN + 18
    )
    assert taken is None
    assert completed is True
    async with container.session_factory() as session:
        job = await session.scalar(select(Job))
        assert job is not None
        assert job.status == "succeeded" and job.attempts == 1
    await container.engine.dispose()


@pytest.mark.integration
async def test_the_old_thirty_second_lease_would_hand_the_call_to_a_second_worker(
    integration_settings: Settings,
) -> None:
    """Контрольный случай: без настройки аренды тот же вызов перехватывался."""
    container = build_container(integration_settings)
    taken, completed = await _race(
        container, 30, second_claim_after=PRODUCTION_MODEL_TIMEOUT + ANALYZER_MARGIN + 4
    )
    assert taken is not None and taken.attempts == 2
    # Первый воркер закончил вызов, но его аренда уже чужая: результат не засчитан.
    assert completed is False
    await container.engine.dispose()
