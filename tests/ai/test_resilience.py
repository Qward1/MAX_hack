"""Предохранитель, ограничитель конкурентности и бюджет вызовов.

Каждое ограничение проверяется дважды: как исключение провайдера и как
состояние `execution.state`, которое получает продукт.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from domsignal.ai import WindowAnalyzer
from domsignal.ai.providers.base import (
    ProviderBudgetExceeded,
    ProviderCircuitOpen,
    ProviderOverloaded,
    ProviderRequest,
    ProviderResult,
    ProviderUnavailable,
    build_request,
)
from domsignal.ai.providers.fake import FakeProvider
from domsignal.ai.resilience import (
    BudgetOutcome,
    CircuitBreaker,
    ConcurrencyLimiter,
    InMemoryBudgetGuard,
    ResilientProvider,
    budget_scope,
    current_budget_scope,
)
from tests.ai.helpers import single


class Clock:
    """Управляемые часы: тест не спит."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CountingProvider:
    """Провайдер, который считает вызовы и отвечает по сценарию."""

    prompt_version = "window.v1"

    def __init__(self, *, failures: int = 0, delay: float = 0.0) -> None:
        self.calls = 0
        self.failures = failures
        self.delay = delay

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failures > 0:
            self.failures -= 1
            raise ProviderUnavailable("recorded failure")
        return ProviderResult(content='{"messages": [], "signals": []}', model="test/model")


def request_for(text: str = "Лифт не работает") -> ProviderRequest:
    request, _mapping = build_request(single(text))
    return request


# ------------------------------------------------------------ предохранитель


def test_breaker_opens_after_three_failures_and_allows_one_probe() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=3, reset_seconds=60.0, clock=clock)
    for _ in range(2):
        assert breaker.allow()
        breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()

    assert breaker.is_open
    assert not breaker.allow()
    clock.advance(59.0)
    assert not breaker.allow()

    clock.advance(2.0)
    assert breaker.allow(), "после паузы пропускается одна пробная попытка"
    assert not breaker.allow(), "вторую попытку до вердикта пробы не пропускаем"

    breaker.record_success()
    assert not breaker.is_open
    assert breaker.allow()


def test_failed_probe_opens_the_breaker_again() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=30.0, clock=clock)
    breaker.record_failure()
    breaker.record_failure()
    clock.advance(31.0)
    assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()
    clock.advance(31.0)
    assert breaker.allow()


def test_unusable_output_does_not_open_the_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record_unusable_output()
    breaker.record_unusable_output()
    breaker.record_unusable_output()
    assert not breaker.is_open


async def test_open_circuit_gives_fallback_circuit_open_without_calling_the_provider() -> None:
    clock = Clock()
    inner = CountingProvider(failures=3)
    provider = ResilientProvider(
        inner, breaker=CircuitBreaker(failure_threshold=3, reset_seconds=60.0, clock=clock)
    )
    analyzer = WindowAnalyzer(provider)
    for _ in range(3):
        analysis = await analyzer.analyze(single("Лифт не работает"))
        assert analysis.execution.state == "fallback_provider_error"
    assert inner.calls == 3

    analysis = await analyzer.analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_circuit_open"
    assert not analysis.execution.provider_called
    assert inner.calls == 3, "при разомкнутом предохранителе вызова нет"

    clock.advance(61.0)
    analysis = await analyzer.analyze(single("Лифт не работает"))
    assert analysis.execution.state == "ok"
    assert inner.calls == 4


async def test_circuit_open_is_raised_by_the_provider_itself() -> None:
    breaker = CircuitBreaker(failure_threshold=1, clock=Clock())
    provider = ResilientProvider(CountingProvider(failures=1), breaker=breaker)
    with pytest.raises(ProviderUnavailable):
        await provider.analyze_window(request_for())
    with pytest.raises(ProviderCircuitOpen):
        await provider.analyze_window(request_for())


# ------------------------------------------------------------- ограничитель


async def test_overload_gives_fallback_overloaded() -> None:
    inner = CountingProvider(delay=0.2)
    limiter = ConcurrencyLimiter(1, wait_seconds=0.01)
    provider = ResilientProvider(inner, limiter=limiter)
    analyzer = WindowAnalyzer(provider)

    slow = asyncio.create_task(analyzer.analyze(single("Лифт не работает")))
    await asyncio.sleep(0.02)
    analysis = await analyzer.analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_overloaded"
    assert not analysis.execution.provider_called

    assert (await slow).execution.state == "ok"
    assert inner.calls == 1


async def test_limiter_releases_the_slot_after_a_failure() -> None:
    limiter = ConcurrencyLimiter(1, wait_seconds=0.01)
    provider = ResilientProvider(CountingProvider(failures=1), limiter=limiter)
    with pytest.raises(ProviderUnavailable):
        await provider.analyze_window(request_for())
    result = await provider.analyze_window(request_for())
    assert result.model == "test/model"


async def test_overloaded_is_raised_by_the_provider_itself() -> None:
    limiter = ConcurrencyLimiter(1, wait_seconds=0.01)
    provider = ResilientProvider(CountingProvider(delay=0.2), limiter=limiter)
    busy = asyncio.create_task(provider.analyze_window(request_for()))
    await asyncio.sleep(0.02)
    with pytest.raises(ProviderOverloaded):
        await provider.analyze_window(request_for())
    await busy


# ------------------------------------------------------------------- бюджет


def test_budget_counts_the_day_and_the_share_of_one_scope() -> None:
    guard = InMemoryBudgetGuard(10, chat_share=0.3)
    assert guard.per_scope_limit == 3
    for _ in range(3):
        assert guard.try_acquire("chat-1")
    assert not guard.try_acquire("chat-1"), "доля одного чата исчерпана"
    assert guard.try_acquire("chat-2"), "другой чат не страдает"
    snapshot = guard.snapshot()
    assert snapshot.calls == 4
    assert snapshot.by_scope == {"chat-1": 3, "chat-2": 1}


def test_budget_stops_at_the_daily_limit_and_resets_next_day() -> None:
    moment = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    def clock() -> datetime:
        return moment

    guard = InMemoryBudgetGuard(2, chat_share=1.0, clock=clock)
    assert guard.try_acquire(None)
    assert guard.try_acquire(None)
    assert not guard.try_acquire(None)

    moment = moment + timedelta(days=1)
    assert guard.try_acquire(None)
    assert guard.snapshot().calls == 1


def test_budget_records_cost_and_failures() -> None:
    guard = InMemoryBudgetGuard(10)
    guard.try_acquire("chat-1")
    guard.record(BudgetOutcome(scope_key="chat-1", success=True, cost_rub=0.25))
    guard.try_acquire("chat-1")
    guard.record(BudgetOutcome(scope_key="chat-1", success=False))
    snapshot = guard.snapshot()
    assert snapshot.cost_rub == pytest.approx(0.25)
    assert snapshot.failures == 1
    assert snapshot.calls == 2, "отказ не возвращает списанную единицу"


def test_zero_budget_refuses_everything() -> None:
    guard = InMemoryBudgetGuard(0)
    assert not guard.try_acquire(None)


@pytest.mark.parametrize(
    ("daily", "share"), [(-1, 0.5), (10, 0.0), (10, 1.5)]
)
def test_budget_rejects_impossible_limits(daily: int, share: float) -> None:
    with pytest.raises(ValueError):
        InMemoryBudgetGuard(daily, chat_share=share)


async def test_spent_budget_gives_fallback_budget_without_an_http_call() -> None:
    inner = CountingProvider()
    provider = ResilientProvider(inner, budget=InMemoryBudgetGuard(1, chat_share=1.0))
    analyzer = WindowAnalyzer(provider)

    assert (await analyzer.analyze(single("Лифт не работает"))).execution.state == "ok"
    analysis = await analyzer.analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_budget"
    assert not analysis.execution.provider_called
    assert inner.calls == 1, "исчерпанный бюджет не пускает запрос в сеть"


async def test_budget_exceeded_is_raised_by_the_provider_itself() -> None:
    provider = ResilientProvider(CountingProvider(), budget=InMemoryBudgetGuard(0))
    with pytest.raises(ProviderBudgetExceeded):
        await provider.analyze_window(request_for())


async def test_scope_comes_from_the_context_not_from_the_window() -> None:
    guard = InMemoryBudgetGuard(10, chat_share=0.2)
    provider = ResilientProvider(CountingProvider(), budget=guard)
    assert current_budget_scope() is None
    with budget_scope("chat-77"):
        assert current_budget_scope() == "chat-77"
        await provider.analyze_window(request_for())
    assert current_budget_scope() is None
    assert guard.snapshot().by_scope == {"chat-77": 1}


async def test_resilient_provider_keeps_the_prompt_version_of_the_inner_one() -> None:
    provider = ResilientProvider(FakeProvider("ok", prompt_version="window.v1"))
    assert provider.prompt_version == "window.v1"
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.versions.prompt == "window.v1"
