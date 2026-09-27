"""F1 (LLM-RATE-2026-09-29): 429 и ограничитель токенов на настоящей PostgreSQL.

Ограничитель `LLM_TOKENS_PER_MINUTE` — общий счёт процессов по минутам; его
отказ — как 429: дневной бюджет не тратится, предохранитель цел. Пассивное
окно после 429 откладывается и не теряется: позже его разбирают правила с
честной пометкой `fallback_rate_limited`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, text, update

from domsignal.ai import WindowAnalyzer
from domsignal.ai.providers.base import ProviderRateLimited, ProviderRequest, ProviderResult
from domsignal.db.models import AiCallBudget, AiTokenMinute, ConversationWindow, Job, Signal
from domsignal.services.ai_budget import PostgresBudgetGuard, estimate_tokens
from tests.integration.passive_harness import pv  # noqa: F401
from tests.integration.test_passive_signals import ago, settle


class Limited:
    """Провайдер, который всегда отвечает 429 с Retry-After."""

    prompt_version = "window.v3"

    def __init__(self) -> None:
        self.calls = 0

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        del request
        self.calls += 1
        raise ProviderRateLimited("llm rate limit: HTTP 429", retry_after=25)


async def test_the_token_limiter_is_shared_and_spends_no_daily_call(pv) -> None:  # noqa: F811
    guard = PostgresBudgetGuard(
        pv.container.session_factory, daily_calls=100, tokens_per_minute=15000
    )
    async with guard.reserve("chat-a", tokens=8000) as first:
        assert first.allowed and guard.try_acquire("chat-a")
    async with guard.reserve("chat-b", tokens=8000) as second:
        assert second.rate_limited and not second.allowed
        with pytest.raises(ProviderRateLimited) as raised:
            guard.try_acquire("chat-b")
        assert raised.value.local and 0 < (raised.value.retry_after or 0) <= 60
    tokens = await pv.scalar(select(func.sum(AiTokenMinute.tokens)))
    assert tokens == 8000
    calls = await pv.scalar(select(AiCallBudget.calls).where(AiCallBudget.scope_key == ""))
    assert calls == 1, "отказ ограничителя не тратит дневной бюджет"


def test_estimate_covers_the_prompt() -> None:
    assert estimate_tokens(["лифт не работает"]) > 7000


async def test_a_passive_window_waits_after_429_and_then_falls_back_to_rules(
    pv,  # noqa: F811
) -> None:
    await pv.bind()
    provider = Limited()
    pv.container.passive_analysis.analyzer = WindowAnalyzer(provider)
    for index, line in enumerate(("Лифт во втором подъезде не работает", "Да, лифт стоит с утра")):
        await pv.say(line, at=ago(80 - 5 * index))
    await settle(pv)
    assert provider.calls >= 1
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed", "окно отложено, а не разобрано правилами сразу"
    job: Any = await pv.scalar(select(Job).where(Job.kind == "ai.window.analyze"))
    assert job.status == "pending"
    assert job.next_attempt_at > datetime.now(UTC) + timedelta(seconds=15)
    # Окно старше срока ожидания: следующий 429 уже не откладывает, а правила
    # разбирают окно — оно не потеряно.
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ConversationWindow).values(closed_at=datetime.now(UTC) - timedelta(seconds=200))
        )
        await session.execute(
            update(Job).where(Job.id == job.id).values(next_attempt_at=text("now()"))
        )
    await pv.drain("ai")
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.execution_state == "fallback_rate_limited"
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1
