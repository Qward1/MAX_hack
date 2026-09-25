"""Дневной бюджет вызовов модели в PostgreSQL.

Счётчик общий для всех реплик воркера, поэтому проверка и списание обязаны
быть атомарными. Отказ означает «вызова не будет» и не тратит единицу общего
дневного лимита: иначе отказ одной области дренировал бы бюджет всего дома.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from domsignal.ai import BudgetOutcome
from domsignal.bootstrap import build_container
from domsignal.db.models import AiCallBudget
from domsignal.services.ai_budget import GLOBAL_BUDGET_SCOPE, PostgresBudgetGuard
from domsignal.settings import Settings


def _guard(
    container_factory: object, *, daily: int, share: float = 0.2, day: date | None = None
) -> PostgresBudgetGuard:
    moment = datetime(2026, 9, 20, 12, 0, tzinfo=UTC) if day is None else datetime(
        day.year, day.month, day.day, 12, 0, tzinfo=UTC
    )
    return PostgresBudgetGuard(
        container_factory,  # type: ignore[arg-type]
        daily_calls=daily,
        chat_share=share,
        clock=lambda: moment,
    )


@pytest.mark.integration
async def test_daily_limit_is_enforced_atomically(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=3, share=1.0)
    allowed = []
    for _ in range(4):
        async with guard.reserve("chat-1") as reservation:
            allowed.append(reservation.allowed)
    assert allowed == [True, True, True, False]
    async with container.session_factory() as session:
        rows = {
            row.scope_key: row.calls
            for row in await session.scalars(select(AiCallBudget))
        }
    assert rows[GLOBAL_BUDGET_SCOPE] == 3
    assert rows["chat-1"] == 3
    await container.engine.dispose()


@pytest.mark.integration
async def test_one_chat_cannot_spend_more_than_its_share(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    # 10 вызовов в сутки, доля чата 20 % → 2 вызова на чат.
    guard = _guard(container.session_factory, daily=10, share=0.2)
    assert guard.per_scope_limit == 2
    greedy = []
    for _ in range(3):
        async with guard.reserve("chat-greedy") as reservation:
            greedy.append(reservation.allowed)
    assert greedy == [True, True, False]
    # Другой чат по-прежнему имеет свою долю: лимит доли не общий.
    async with guard.reserve("chat-other") as reservation:
        assert reservation.allowed
    await container.engine.dispose()


@pytest.mark.integration
async def test_refused_scope_does_not_consume_the_daily_unit(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=10, share=0.1)
    assert guard.per_scope_limit == 1
    async with guard.reserve("chat-1") as first:
        assert first.allowed
    async with guard.reserve("chat-1") as second:
        assert not second.allowed
    async with container.session_factory() as session:
        rows = {
            row.scope_key: row.calls
            for row in await session.scalars(select(AiCallBudget))
        }
    # Отказ доли откатывается целиком: общий счёт остался равен одному вызову.
    assert rows[GLOBAL_BUDGET_SCOPE] == 1
    assert rows["chat-1"] == 1
    await container.engine.dispose()


@pytest.mark.integration
async def test_zero_budget_allows_nothing_and_writes_nothing(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=0)
    async with guard.reserve("chat-1") as reservation:
        assert not reservation.allowed
    async with container.session_factory() as session:
        assert list(await session.scalars(select(AiCallBudget))) == []
    await container.engine.dispose()


@pytest.mark.integration
async def test_try_acquire_reports_the_reservation_exactly_once(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=5, share=1.0)
    async with guard.reserve("chat-1"):
        assert guard.try_acquire("chat-1") is True
        # Одна единица — одна попытка: второй вызов в том же окне не разрешён.
        assert guard.try_acquire("chat-1") is False
    await container.engine.dispose()


@pytest.mark.integration
async def test_try_acquire_without_reservation_refuses(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=5)
    # Вне `reserve` решение не принималось, поэтому вызова быть не может.
    assert guard.try_acquire("chat-1") is False
    await container.engine.dispose()


@pytest.mark.integration
async def test_refused_reservation_still_refuses_try_acquire(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=0)
    async with guard.reserve("chat-1") as reservation:
        assert not reservation.allowed
        assert guard.try_acquire("chat-1") is False
    await container.engine.dispose()


@pytest.mark.integration
async def test_counters_are_per_day(integration_settings: Settings) -> None:
    container = build_container(integration_settings)
    today = _guard(container.session_factory, daily=1, share=1.0, day=date(2026, 9, 20))
    async with today.reserve("chat-1") as reservation:
        assert reservation.allowed
    async with today.reserve("chat-1") as reservation:
        assert not reservation.allowed
    tomorrow = _guard(container.session_factory, daily=1, share=1.0, day=date(2026, 9, 21))
    async with tomorrow.reserve("chat-1") as reservation:
        assert reservation.allowed
    async with container.session_factory() as session:
        days = sorted(
            {row.day for row in await session.scalars(select(AiCallBudget))}
        )
    assert days == [date(2026, 9, 20), date(2026, 9, 21)]
    await container.engine.dispose()


@pytest.mark.integration
async def test_recorded_cost_is_carried_on_the_reservation(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=5, share=1.0)
    async with guard.reserve("chat-1") as reservation:
        assert guard.try_acquire("chat-1") is True
        guard.record(BudgetOutcome(scope_key="chat-1", success=True, cost_rub=0.17, tokens_in=12))
        assert reservation.outcome is not None
        assert reservation.outcome.cost_rub == 0.17
    await container.engine.dispose()


@pytest.mark.integration
async def test_unscoped_reservation_charges_only_the_daily_counter(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    guard = _guard(container.session_factory, daily=2, share=0.5)
    async with guard.reserve(None) as reservation:
        assert reservation.allowed
    async with container.session_factory() as session:
        rows = {
            row.scope_key: row.calls
            for row in await session.scalars(select(AiCallBudget))
        }
    assert rows == {GLOBAL_BUDGET_SCOPE: 1}
    await container.engine.dispose()
