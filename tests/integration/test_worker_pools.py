"""Изоляция нагрузки LLM: пул забирает только свои виды задач.

Смысл проверки в том, что деградация AI не касается доставки уведомлений и
жизненного цикла Ticket: они в другом пуле и другом процессе.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import Job
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.settings import Settings
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
