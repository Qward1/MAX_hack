"""Приём `/report <свободный текст>`: запись приёма и две задачи.

Смысл двух задач — страховка. Разбор моделью и сторожевой разбор правилами
борются за одну и ту же запись; кто захватил, тот и обрабатывает. Поэтому
остановленный AI-пул задерживает результат максимум на задержку сторожа, а не
отменяет его.

Старый `/report <код категории> <текст>` обязан работать как раньше.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select

from domsignal.db.models import ExplicitIntake, InboxReceipt, Job
from tests.integration.explicit_harness import ex  # noqa: F401

FREE_TEXT = "опять лифт во втором подъезде стоит"

#: Задачи явного пути. Подключение чата оставляет свои задачи в той же таблице,
#: и они остаются там после успешного выполнения, поэтому виды перечислены.
INTAKE_KINDS = ["ai.report.analyze", "report.fallback", "max.group.report"]


def _intake_jobs() -> Any:
    return select(Job).where(Job.kind.in_(INTAKE_KINDS))


@pytest.mark.integration
async def test_free_text_report_records_an_intake_and_two_jobs(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {FREE_TEXT}")

    intake = await ex.scalar(select(ExplicitIntake))
    assert intake is not None
    assert intake.text == FREE_TEXT
    assert intake.state == "pending" and intake.claimed_at is None
    assert intake.chat_id == "-501" and intake.external_user_id == "502"
    assert intake.binding_version == 1 and intake.result_kind is None

    jobs = {job.kind: job for job in await ex.all(_intake_jobs())}
    assert set(jobs) == {"ai.report.analyze", "report.fallback"}
    assert all(job.payload == {"event_id": intake.event_id} for job in jobs.values())
    # Разбор моделью идёт раньше обычных задач, сторож ждёт 30 секунд.
    assert jobs["ai.report.analyze"].priority < jobs["report.fallback"].priority
    delay = jobs["report.fallback"].next_attempt_at - datetime.now(UTC)
    assert 20 <= delay.total_seconds() <= 31
    assert jobs["ai.report.analyze"].next_attempt_at <= datetime.now(UTC)


@pytest.mark.integration
async def test_the_two_jobs_land_in_different_pools(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {FREE_TEXT}")
    ai_claim = await ex.runner("ai").claim()
    assert ai_claim is not None and ai_claim.kind == "ai.report.analyze"
    # Сторож живёт в операционном пуле, но его время ещё не пришло.
    assert await ex.runner("operational").claim() is None


@pytest.mark.integration
async def test_category_code_keeps_the_previous_path(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report("/report water в подвале вода")
    assert await ex.scalar(select(func.count()).select_from(ExplicitIntake)) == 0
    kinds = [job.kind for job in await ex.all(_intake_jobs())]
    assert kinds == ["max.group.report"]


@pytest.mark.integration
async def test_repeated_webhook_delivery_creates_no_second_intake(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {FREE_TEXT}", mid="same")
    await ex.report(f"/report {FREE_TEXT}", mid="same")
    assert await ex.scalar(select(func.count()).select_from(ExplicitIntake)) == 1
    assert len(await ex.all(_intake_jobs())) == 2


@pytest.mark.integration
async def test_unbound_chat_records_no_intake(ex) -> None:  # noqa: F811
    # Чат не подключён: приём не создаёт ни записи, ни задач.
    await ex.report(f"/report {FREE_TEXT}")
    assert await ex.scalar(select(func.count()).select_from(ExplicitIntake)) == 0
    assert await ex.all(_intake_jobs()) == []


@pytest.mark.integration
async def test_intake_receipt_still_keeps_no_message_text(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {FREE_TEXT}")
    receipt = await ex.scalar(
        select(InboxReceipt).where(InboxReceipt.event_type == "message_created")
    )
    assert receipt.payload == {"chat_id": "-501"}


@pytest.mark.integration
@pytest.mark.parametrize("text", ["/report ", "/report    ", "/report дым"])
async def test_too_short_free_text_is_ignored_like_a_malformed_command(ex, text) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(text)
    assert await ex.scalar(select(func.count()).select_from(ExplicitIntake)) == 0
    assert await ex.all(_intake_jobs()) == []
