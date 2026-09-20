"""Пулы воркеров: нагрузка LLM изолирована от операционных задач.

Пул определяется видом задачи, а не составом обработчиков: неизвестный вид
всё равно кто-то забирает и честно проваливает, иначе он останется навсегда.
"""

from __future__ import annotations

from domsignal.worker.pools import AI_JOB_KINDS, POOLS, claims_kind, pool_for


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
