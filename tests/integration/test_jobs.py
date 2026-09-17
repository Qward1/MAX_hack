from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from domsignal.bootstrap import build_container
from domsignal.bot.ingress import InboundService
from domsignal.bot.transport import RecordingTransport
from domsignal.contracts.jobs import NormalizedInboundEvent
from domsignal.db.models import InboxReceipt, Job, Report
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.settings import Settings
from domsignal.tools.seed_demo import DEMO_HOUSE_ID
from domsignal.worker.runner import WorkerRunner


@pytest.mark.integration
async def test_replay_is_deduplicated_and_processed_by_real_service(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    event = NormalizedInboundEvent(
        event_id="test-event-1",
        event_type="diagnostic.report",
        external_user_id="demo-max-user",
        house_id=DEMO_HOUSE_ID,
        category="water",
        description="В подвале тестового дома появилась вода",
        occurred_at=datetime.now(UTC),
    )
    async with container.session_factory() as session:
        first = await InboundService().accept(session, event=event)
    async with container.session_factory() as session:
        duplicate = await InboundService().accept(session, event=event)
    assert first.job_id is not None
    assert duplicate.duplicate and duplicate.job_id is None

    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        lease_seconds=5,
    )
    assert await runner.run_once()
    assert isinstance(container.transport, RecordingTransport)
    assert len(container.transport.sent) == 1
    async with container.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Report)) == 1
    await container.engine.dispose()


@pytest.mark.integration
async def test_expired_lease_recovers_and_stale_worker_cannot_complete(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    async with container.session_factory() as session, session.begin():
        await ReliabilityRepository(session).add_job(
            kind="diagnostic.record",
            payload={"destination": "test", "text": "lease"},
        )
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        lease_seconds=5,
    )
    started = datetime.now(UTC)
    first = await runner.claim(now=started)
    assert first is not None
    assert await runner.claim(now=started + timedelta(seconds=1)) is None
    recovered = await runner.claim(now=started + timedelta(seconds=6))
    assert recovered is not None and recovered.id == first.id
    assert recovered.lease_token != first.lease_token

    async with container.session_factory() as session, session.begin():
        stale = await ReliabilityRepository(session).complete_job(
            job_id=first.id,
            lease_token=first.lease_token,
            now=started + timedelta(seconds=7),
        )
    assert not stale
    assert await runner.process(recovered)
    await container.engine.dispose()


@pytest.mark.integration
async def test_failed_transaction_never_records_inbox_success(
    integration_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = build_container(integration_settings)
    original = ReliabilityRepository.add_inbox_and_job

    async def fail_after_write(self: ReliabilityRepository, **kwargs: object) -> Job:
        await original(self, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("simulated database failure before commit")

    monkeypatch.setattr(ReliabilityRepository, "add_inbox_and_job", fail_after_write)
    event = NormalizedInboundEvent(
        event_id="rollback-event",
        event_type="diagnostic.report",
        external_user_id="demo-max-user",
        house_id=DEMO_HOUSE_ID,
        category="other",
        description="Проверка отката транзакции inbox",
        occurred_at=datetime.now(UTC),
    )
    async with container.session_factory() as session:
        with pytest.raises(RuntimeError, match="before commit"):
            await InboundService().accept(session, event=event)
    async with container.session_factory() as session:
        assert await session.get(InboxReceipt, "rollback-event") is None
    await container.engine.dispose()
