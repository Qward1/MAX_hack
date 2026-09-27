"""D5 §1: параллельные циклы воркера, пул соединений, готовность справочника."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from domsignal.services.queue_health import directory_readiness
from domsignal.services.routing import load_directory_or_none
from domsignal.settings import Settings
from domsignal.worker.main import concurrency_for
from domsignal.worker.runner import run_loops


def settings(**changes: object) -> Settings:
    return Settings(_env_file=None, **changes)  # type: ignore[arg-type]


def test_defaults_keep_one_loop_and_the_previous_pool() -> None:
    config = settings()
    assert (config.ai_worker_concurrency, config.operational_worker_concurrency) == (1, 1)
    assert (config.db_pool_size, config.db_max_overflow) == (5, 10)
    assert concurrency_for("ai", settings(ai_worker_concurrency=3)) == 3
    assert concurrency_for("operational", settings(operational_worker_concurrency=2)) == 2


def test_loops_cannot_outnumber_connections_or_the_model_semaphore() -> None:
    with pytest.raises(ValidationError, match="DB_POOL_SIZE"):
        settings(ai_worker_concurrency=8, db_pool_size=4, db_max_overflow=0)
    with pytest.raises(ValidationError, match="LLM_MAX_CONCURRENCY"):
        settings(
            llm_provider="openai_compatible",
            llm_api_key="synthetic-key",
            llm_model="Qwen/Qwen3-30B-A3B",
            llm_max_concurrency=2,
            ai_worker_concurrency=4,
        )
    # Правила без модели: семафора нет, ограничение только соединениями.
    assert settings(ai_worker_concurrency=8).ai_worker_concurrency == 8


class FakeRunner:
    def __init__(self, jobs: int) -> None:
        self.jobs = jobs
        self.active = 0
        self.peak = 0
        self.done = 0
        self.all_done = asyncio.Event()

    async def run_once(self) -> bool:
        if self.jobs == 0:
            return False
        self.jobs -= 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        self.done += 1
        if self.jobs == 0 and self.active == 0:
            self.all_done.set()
        return True


async def test_loops_run_in_parallel_and_stop_after_the_current_step() -> None:
    runner = FakeRunner(jobs=20)
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_loops(runner, concurrency=4, stop=stop, idle_seconds=0.01)  # type: ignore[arg-type]
    )
    await asyncio.wait_for(runner.all_done.wait(), timeout=2)
    stop.set()
    await asyncio.wait_for(task, timeout=2)
    assert runner.peak == 4 and runner.done == 20


async def test_zero_loops_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await run_loops(FakeRunner(0), concurrency=0, stop=asyncio.Event())  # type: ignore[arg-type]


def test_directory_readiness_covers_every_pack() -> None:
    directory = load_directory_or_none(Path("regions"))
    assert directory is not None
    rows = {row.pack: row for row in directory_readiness(directory, today=date(2026, 9, 27))}
    assert set(rows) == {"_federal", *directory.regions}
    assert rows["RU-PSK"].needs_verification >= 2, "Минрегконтроль и его бот ждут сверки"
    assert rows["RU-MOW"].unavailable_channels
    assert all(row.stale == 0 for row in rows.values()), "на 27.09 свежие"
    later = {row.pack: row for row in directory_readiness(directory, today=date(2027, 9, 1))}
    assert later["RU-TA"].stale == later["RU-TA"].verified > 0
