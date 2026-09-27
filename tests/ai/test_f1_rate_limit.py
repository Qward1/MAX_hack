"""F1 (LLM-RATE-2026-09-29): ответ 429 — не отказ провайдера.

Записанные ответы, сети нет. 429 даёт `ProviderRateLimited` с Retry-After,
предохранитель от серии 429 не размыкается, фасад отдаёт результат правил с
состоянием `fallback_rate_limited` и сроком повтора.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from domsignal.ai import WindowAnalyzer
from domsignal.ai.providers.base import ProviderRateLimited, build_request
from domsignal.ai.resilience import CircuitBreaker, ResilientProvider
from tests.ai.helpers import single
from tests.ai.test_provider_http import VALID_ANSWER, cloudru_completion, provider_for


def too_many(headers: dict[str, str] | None = None) -> object:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers=headers or {},
            json={"error": {"code": "ModelArts.81114", "message": "Too many tokens per minute"}},
        )

    return handler


async def test_429_with_retry_after_seconds_is_a_rate_limit() -> None:
    provider = provider_for(too_many({"Retry-After": "7"}))
    request, _ = build_request(single("Лифт не работает"))
    with pytest.raises(ProviderRateLimited) as raised:
        await provider.analyze_window(request)
    assert raised.value.retry_after == 7.0
    assert not raised.value.local


async def test_429_with_an_http_date_and_without_a_header() -> None:
    later = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    request, _ = build_request(single("Лифт не работает"))
    with pytest.raises(ProviderRateLimited) as dated:
        await provider_for(too_many({"Retry-After": later})).analyze_window(request)
    assert dated.value.retry_after is not None and 20 < dated.value.retry_after <= 30
    with pytest.raises(ProviderRateLimited) as bare:
        await provider_for(too_many()).analyze_window(request)
    assert bare.value.retry_after is None


async def test_a_series_of_429_does_not_open_the_breaker() -> None:
    breaker = CircuitBreaker(failure_threshold=3)
    provider = ResilientProvider(provider_for(too_many({"Retry-After": "2"})), breaker=breaker)
    request, _ = build_request(single("Лифт не работает"))
    for _ in range(10):
        with pytest.raises(ProviderRateLimited):
            await provider.analyze_window(request)
    assert not breaker.is_open
    assert breaker.rate_limited == 10
    assert breaker.allow()


async def test_the_facade_falls_back_to_rules_with_an_honest_state() -> None:
    analyzer = WindowAnalyzer(provider_for(too_many({"Retry-After": "4"})))
    analysis = await analyzer.analyze(single("Лифт во втором подъезде не работает"))
    assert analysis.execution.state == "fallback_rate_limited"
    assert analysis.execution.retry_after_s == 4.0
    assert analysis.execution.provider_called
    assert analysis.mode in {"rules", "manual"}
    assert analysis.signals, "окно не потеряно — сигнал правил на месте"


async def test_after_the_limit_passes_the_model_answers_again() -> None:
    answers = iter([too_many({"Retry-After": "1"}), None])
    content = json.dumps(VALID_ANSWER, ensure_ascii=False)

    def handler(request: httpx.Request) -> httpx.Response:
        current = next(answers)
        if current is not None:
            return current(request)  # type: ignore[operator]
        return httpx.Response(200, json=cloudru_completion(content))

    analyzer = WindowAnalyzer(ResilientProvider(provider_for(handler)))
    first = await analyzer.analyze(single("Лифт не работает"))
    second = await analyzer.analyze(single("Лифт не работает"))
    assert first.execution.state == "fallback_rate_limited"
    assert second.execution.state == "ok" and second.mode == "model"
