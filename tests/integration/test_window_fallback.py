"""Доделки P4 в P5: сторож разбора окна, настройки вместо констант, маршрут опасности."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from domsignal.db.models import ConversationWindow, Job, RouteOutcome, Signal, SignalEvent
from domsignal.services.errors import RescheduleJob
from domsignal.worker.pools import pool_for
from tests.integration.passive_harness import pv  # noqa: F401
from tests.integration.test_passive_signals import LIFT_FIRST, ago, conversation

GAS = "Пахнет газом в третьем подъезде"
FLOOD = "Затопило подвал, вода хлещет"
FIRE = "В подъезде сильный дым, горит мусоропровод"


# ------------------------------------------------------------------ сторож окна


async def test_a_stopped_ai_pool_is_covered_by_the_rules_watchdog(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.drain("operational")  # тишина закрывает окно; AI-пул остановлен
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed"
    fallback = (await pv.jobs("chat.window.fallback"))[0]
    assert pool_for(fallback.kind) == "operational"
    assert fallback.payload == {"window_id": str(window.id)}
    delay = (fallback.next_attempt_at - window.closed_at).total_seconds()
    assert 89 <= delay <= 91, "сторож ставится на PASSIVE_ANALYSIS_FALLBACK_SECONDS"

    await pv.drain("operational")
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0, "раньше срока — нет"
    await pv.drain("operational", now=datetime.now(UTC) + timedelta(seconds=91))
    signal = await pv.scalar(select(Signal))
    assert signal is not None and signal.subtype == "elevator.stopped"
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.analyzed_by == "fallback"
    assert window.analysis_mode == "rules" and window.analysis["provider_called"] is False

    # Вернувшийся AI-пул уже разобранное окно не трогает.
    await pv.drain("ai")
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1
    assert await pv.scalar(select(func.count()).select_from(RouteOutcome)) == 1
    window = await pv.scalar(select(ConversationWindow))
    assert window.analyzed_by == "fallback"
    analyze = (await pv.jobs("ai.window.analyze"))[0]
    assert analyze.status == "succeeded"


async def test_the_ai_pool_first_leaves_the_watchdog_nothing_to_do(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.drain("operational")
    await pv.drain_all()
    window = await pv.scalar(select(ConversationWindow))
    assert window.analyzed_by == "ai"
    await pv.drain("operational", now=datetime.now(UTC) + timedelta(seconds=91))
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1
    fallback = (await pv.jobs("chat.window.fallback"))[0]
    assert fallback.status == "succeeded", "второй тихо выходит"


async def test_the_watchdog_and_the_ai_pool_racing_give_one_set_of_signals(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.drain("operational")
    window = await pv.scalar(select(ConversationWindow))
    payload = {"window_id": str(window.id)}
    analysis = pv.container.passive_analysis
    results = await asyncio.gather(
        analysis.analyze_window(payload),
        analysis.analyze_with_rules(payload),
        return_exceptions=True,
    )
    # Проигравший сторож может застать окно в разборе и перенести себя —
    # это сигнал воркеру, а не ошибка; второй прогон тихо выходит.
    assert all(item is None or isinstance(item, RescheduleJob) for item in results)
    await analysis.analyze_with_rules(payload)
    await analysis.analyze_window(payload)
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1
    assert await pv.scalar(select(func.count()).select_from(RouteOutcome)) == 1
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.analyzed_by in {"ai", "fallback"}


async def test_the_watchdog_waits_while_the_window_is_being_analyzed(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.drain("operational")
    window = await pv.scalar(select(ConversationWindow))
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ConversationWindow)
            .where(ConversationWindow.id == window.id)
            .values(state="analyzing", claimed_at=datetime.now(UTC), claimed_by="ai.window:x")
        )
    with pytest.raises(RescheduleJob):
        await pv.container.passive_analysis.analyze_with_rules({"window_id": str(window.id)})
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0


# -------------------------------------------------------- настройки вместо констант


async def test_danger_grouping_follows_the_setting(pv) -> None:  # noqa: F811
    await pv.bind()
    pv.configure(danger_group_minutes=1, memo_pause_minutes=1)
    await pv.say(GAS, at=ago(300))
    await pv.say("Опять пахнет газом в подъезде", at=ago(30))
    signals = await pv.all(select(Signal).where(Signal.strength == "critical"))
    assert len(signals) == 2, "за пределами PASSIVE_DANGER_GROUP_MINUTES — новый сигнал"
    pv.configure(danger_group_minutes=30)
    await pv.say("И сейчас пахнет газом в подъезде", at=ago(10))
    assert len(await pv.all(select(Signal).where(Signal.strength == "critical"))) == 2
    grouped = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "danger_grouped"))
    assert grouped is not None


# ------------------------------------------------------ маршрут опасности до окна


async def test_gas_before_the_window_verdict_routes_to_the_emergency_service(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(GAS, at=ago(30))
    signal = await pv.scalar(select(Signal))
    assert signal.subtype == "other.unspecified" and "preliminary" in signal.flags
    outcome = await pv.scalar(
        select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id)
    )
    assert outcome.route_type == "emergency_service" and outcome.decision == "external"
    assert outcome.channel_id == "emergency_112"
    event = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "route_assigned"))
    assert event.details == "emergency_service (rule)"


async def test_smoke_fire_before_the_window_verdict_routes_to_the_emergency_service(pv) -> None:  # noqa: F811
    """P7a: дым или огонь — в 112 по п. 21 «а» Правил ПП РФ № 2071, до разбора окна."""
    await pv.bind()
    await pv.say(FIRE, at=ago(30))
    signal = await pv.scalar(select(Signal))
    assert signal.subtype == "other.unspecified" and "preliminary" in signal.flags
    assert signal.emergency["kinds"] == ["smoke_fire"]
    outcome = await pv.scalar(
        select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id)
    )
    assert outcome.route_type == "emergency_service" and outcome.decision == "external"
    # Газа нет: в 112 ведёт только правило дыма/огня (его id проверяет unit-тест).
    assert outcome.channel_id == "emergency_112"
    event = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "route_assigned"))
    assert event.details == "emergency_service (rule)"
    assert (
        await pv.scalar(select(func.count()).select_from(Job).where(Job.kind == "signal.alert"))
        == 1
    )
    # Вердикт окна (здесь — правила) маршрут в экстренную службу не снимает.
    await pv.drain_all()
    signal = await pv.scalar(select(Signal))
    final = await pv.scalar(select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id))
    assert final.route_type == "emergency_service" and final.channel_id == "emergency_112"


async def test_flooding_before_the_verdict_is_not_routed_to_112(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(FLOOD, at=ago(30))
    signal = await pv.scalar(select(Signal))
    assert signal is not None and signal.emergency["kinds"] == ["flooding"]
    outcome = await pv.scalar(
        select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id)
    )
    assert outcome.route_type != "emergency_service"
    assert outcome.channel_id is None


async def test_the_preliminary_route_is_replaced_by_the_final_one_with_an_event(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(GAS, at=ago(30))
    signal = await pv.scalar(select(Signal))
    preliminary_outcome = signal.route_outcome_id
    await pv.drain_all()
    signal = await pv.scalar(select(Signal))
    assert signal.subtype == "gas.smell" and "reconciled" in signal.flags
    assert signal.route_outcome_id != preliminary_outcome
    final = await pv.scalar(select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id))
    assert final.route_type == "emergency_service" and final.subtype == "gas.smell"
    events = await pv.all(
        select(SignalEvent.details)
        .where(SignalEvent.kind == "route_assigned", SignalEvent.signal_id == signal.id)
        .order_by(SignalEvent.created_at)
    )
    assert len(events) == 2
    assert (
        await pv.scalar(select(func.count()).select_from(Job).where(Job.kind == "signal.alert"))
        == 1
    )
