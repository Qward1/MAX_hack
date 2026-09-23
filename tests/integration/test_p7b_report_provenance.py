"""P7b §1.4: провенанс разбора `/report` при любом исходе.

Живой прогон P7a: у явного пути с внешним маршрутом (заявки нет) и у вызова,
оборванного по таймауту, задержка и стоимость модели не сохранялись. Теперь
запись приёма хранит учёт вызова всегда: состояние, задержку, модель, токены
и ₽ — или `null` с причиной.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import func, select

from domsignal.ai.providers.fake import FakeProvider
from domsignal.db.models import ExplicitIntake, Report, RouteOutcome
from tests.integration.explicit_harness import ex  # noqa: F401
from tests.integration.test_explicit_reports import ELEVATOR, STREET_LIGHT, _past_due
from tests.integration.test_passive_signals import facet, model_signal, one_line_answer

EXECUTION_KEYS = {
    "mode",
    "state",
    "provider_called",
    "latency_ms",
    "model",
    "tokens_in",
    "tokens_out",
    "tokens_missing_reason",
    "cost_rub",
    "cost_missing_reason",
}

STREET_ANSWER = one_line_answer(
    model_signal(
        subtype="street_lighting.failure",
        obj="фонари",
        scope=("municipal_territory", "на улице у остановки", "m1"),
        facets={
            "current": facet("yes", "не горят фонари", "m1"),
            "local": facet("unclear"),
            "observed": facet("yes", "не горят фонари", "m1"),
        },
    )
)


async def _intake(harness: Any) -> ExplicitIntake:
    intake = await harness.scalar(select(ExplicitIntake))
    assert intake is not None and intake.state == "done"
    assert intake.analysis is not None
    assert EXECUTION_KEYS <= set(intake.analysis)
    assert STREET_LIGHT not in str(intake.analysis) and ELEVATOR not in str(intake.analysis)
    return intake


@pytest.mark.integration
async def test_external_route_with_the_model_keeps_latency_and_cost(ex) -> None:  # noqa: F811
    await ex.bind()
    provider = FakeProvider("ok", STREET_ANSWER, cost_rub=0.2345, delay_seconds=0.05)
    ex.container.explicit_reports.analyzer.provider = provider
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()

    assert provider.requests, "модель вызывалась"
    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.decision == "external" and outcome.report_id is None
    assert await ex.scalar(select(func.count()).select_from(Report)) == 0
    analysis = (await _intake(ex)).analysis
    assert analysis["state"] == "ok" and analysis["mode"] == "model"
    assert analysis["provider_called"] is True
    assert analysis["latency_ms"] >= 50
    assert analysis["model"] == "fake/deterministic"
    assert analysis["cost_rub"] == 0.2345 and analysis["cost_missing_reason"] is None
    # Фейковый провайдер токены не сообщает — это честный `null` с причиной.
    assert analysis["tokens_in"] is None
    assert analysis["tokens_missing_reason"] == "not_reported_by_provider"
    assert analysis["versions"]["input_sha256"]


@pytest.mark.integration
async def test_a_timeout_keeps_latency_and_names_why_the_cost_is_unknown(ex) -> None:  # noqa: F811
    await ex.bind()
    provider = FakeProvider("timeout")
    ex.container.explicit_reports.analyzer.provider = provider
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()

    assert provider.requests
    analysis = (await _intake(ex)).analysis
    assert analysis["state"] == "fallback_timeout" and analysis["mode"] == "rules"
    assert analysis["provider_called"] is True
    assert isinstance(analysis["latency_ms"], int)
    assert analysis["cost_rub"] is None and analysis["cost_missing_reason"] == "timeout"
    assert analysis["tokens_missing_reason"] == "timeout"


@pytest.mark.integration
async def test_the_rules_watchdog_records_that_no_call_was_made(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await _past_due(ex)
    await ex.drain("operational")

    intake = await _intake(ex)
    assert intake.claimed_by == "report.fallback"
    assert intake.analysis["provider_called"] is False
    assert intake.analysis["cost_missing_reason"] == "provider_not_called"
    report = await ex.scalar(select(Report))
    assert report is not None, "зона УК — заявка"
    assert report.analysis["cost_missing_reason"] == "provider_not_called"
    assert report.analysis["latency_ms"] == intake.analysis["latency_ms"]


@pytest.mark.integration
async def test_an_exhausted_budget_is_recorded_without_a_call(ex) -> None:  # noqa: F811
    from domsignal.ai import CircuitBreaker, ConcurrencyLimiter, ResilientProvider, WindowAnalyzer
    from domsignal.services.ai_budget import PostgresBudgetGuard

    await ex.bind()
    provider = FakeProvider("ok", STREET_ANSWER, cost_rub=0.3)
    budget = PostgresBudgetGuard(ex.container.session_factory, daily_calls=0)
    ex.container.explicit_reports.analyzer = WindowAnalyzer(
        ResilientProvider(
            provider, breaker=CircuitBreaker(), limiter=ConcurrencyLimiter(2), budget=budget
        )
    )
    ex.container.explicit_reports.budget = budget
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()

    assert provider.requests == []
    analysis = (await _intake(ex)).analysis
    assert analysis["state"] == "fallback_budget" and analysis["provider_called"] is False
    assert analysis["cost_missing_reason"] == "provider_not_called"
