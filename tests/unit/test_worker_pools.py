"""Пулы воркеров: нагрузка LLM изолирована от операционных задач.

Пул определяется видом задачи, а не составом обработчиков: неизвестный вид
всё равно кто-то забирает и честно проваливает, иначе он останется навсегда.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domsignal.settings import Settings
from domsignal.worker.pools import (
    AI_JOB_KINDS,
    AI_LEASE_MARGIN_SECONDS,
    OPERATIONAL_LEASE_SECONDS,
    POOLS,
    claims_kind,
    lease_seconds_for,
    pool_for,
)


def test_ai_report_analysis_belongs_to_the_ai_pool() -> None:
    assert pool_for("ai.report.analyze") == "ai"


def test_operational_is_the_default_pool() -> None:
    assert pool_for("report.fallback") == "operational"
    assert pool_for("max.group.report") == "operational"
    assert pool_for("max.ticket.answer") == "operational"
    assert pool_for("diagnostic.record") == "operational"


def test_every_known_ai_kind_uses_the_ai_prefix() -> None:
    assert AI_JOB_KINDS
    assert all(kind.startswith("ai.") for kind in AI_JOB_KINDS)
    assert all(pool_for(kind) == "ai" for kind in AI_JOB_KINDS)


def test_pools_are_exactly_operational_and_ai() -> None:
    assert POOLS == ("operational", "ai")


def test_operational_pool_never_claims_ai_work() -> None:
    assert not claims_kind("operational", "ai.report.analyze")
    assert claims_kind("operational", "report.fallback")


def test_ai_pool_claims_only_ai_work() -> None:
    assert claims_kind("ai", "ai.report.analyze")
    assert not claims_kind("ai", "max.ticket.answer")


def test_unknown_kind_is_still_claimed_by_exactly_one_pool() -> None:
    for kind in ("totally.unknown", "ai.unknown.future"):
        assert sum(claims_kind(pool, kind) for pool in POOLS) == 1


# ---------------------------------------------------------- аренда задачи пула (P7a)


def test_operational_lease_stays_thirty_seconds() -> None:
    assert OPERATIONAL_LEASE_SECONDS == 30
    # Настройка AI-пула и таймаут модели операционный пул не меняют.
    assert lease_seconds_for("operational", ai_lease_seconds=600, model_timeout_seconds=55) == 30


def test_ai_lease_comes_from_the_setting() -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_worker_lease_seconds == 60
    assert (
        lease_seconds_for(
            "ai", ai_lease_seconds=settings.ai_worker_lease_seconds, model_timeout_seconds=25
        )
        == 60
    )
    assert lease_seconds_for("ai", ai_lease_seconds=90, model_timeout_seconds=None) == 90


def test_ai_lease_shorter_than_the_model_call_refuses_to_start() -> None:
    assert AI_LEASE_MARGIN_SECONDS == 20
    assert lease_seconds_for("ai", ai_lease_seconds=45, model_timeout_seconds=25) == 45
    with pytest.raises(ValueError, match="AI_WORKER_LEASE_SECONDS"):
        lease_seconds_for("ai", ai_lease_seconds=44, model_timeout_seconds=25)
    # Прежняя аренда 30 с не покрывает таймаут production 25 с.
    with pytest.raises(ValueError, match="AI_WORKER_LEASE_SECONDS"):
        lease_seconds_for("ai", ai_lease_seconds=30, model_timeout_seconds=25)
    # Production: таймаут 60 с требует аренды не меньше 80 с.
    assert lease_seconds_for("ai", ai_lease_seconds=80, model_timeout_seconds=60) == 80
    with pytest.raises(ValueError, match="AI_WORKER_LEASE_SECONDS"):
        lease_seconds_for("ai", ai_lease_seconds=79, model_timeout_seconds=60)


def test_ai_lease_setting_rejects_impossible_values() -> None:
    for value in (0, 29, 601):
        with pytest.raises(ValidationError):
            Settings(ai_worker_lease_seconds=value, _env_file=None)
