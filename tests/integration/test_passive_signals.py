"""Разбор окна в AI-пуле, сигналы, склейка веток, маршрут, изоляция и хранение."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from domsignal.ai import (
    CircuitBreaker,
    ConcurrencyLimiter,
    ResilientProvider,
    WindowAnalyzer,
)
from domsignal.ai.providers.fake import FakeProvider
from domsignal.db.models import (
    ChatMessage,
    ConversationWindow,
    Job,
    NotificationDelivery,
    OutboxMessage,
    RouteOutcome,
    Signal,
    SignalEvent,
    SignalLine,
    SignalQuote,
)
from domsignal.services.ai_budget import PostgresBudgetGuard
from domsignal.services.chat_voice import CHAT_MESSAGE_INTENT_KIND
from domsignal.services.passive_analysis import PassiveWindowAnalysis
from domsignal.tools.signals_preview import preview
from tests.integration.passive_harness import CHAT_1, CHAT_2, NEIGHBOURS, pv  # noqa: F401

LIFT_FIRST = (
    "Лифт во втором подъезде опять не работает",
    "Да, лифт стоит с утра",
    "Подтверждаю, лифт во 2 подъезде не едет",
    "Кто-нибудь звонил в УК?",
)
LIFT_SECOND = (
    "Лифт во втором подъезде так и не работает",
    "С коляской невозможно подняться, лифт стоит",
    "Тоже вчера пешком шла, лифт не работает",
)
REFUTED_GAS = "Вчера вечером пахло газом в подъезде, но аварийка уже всё починила"


def ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


def facet(value: str, quote: str | None = None, msg: str | None = None) -> dict[str, Any]:
    return {"v": value, "quote": quote, "msg": msg}


def model_signal(
    *,
    subtype: str,
    obj: str,
    scope: tuple[str, str | None, str | None] = ("unknown", None, None),
    facets: dict[str, Any] | None = None,
    danger: list[dict[str, Any]] | None = None,
    refutation: dict[str, Any] | None = None,
    ref: str = "new:1",
) -> dict[str, Any]:
    return {
        "ref": ref,
        "subtype": subtype,
        "object": obj,
        "location_scope": {"value": scope[0], "quote": scope[1], "msg": scope[2]},
        "facets": facets
        or {
            "current": facet("unclear"),
            "local": facet("unclear"),
            "observed": facet("unclear"),
        },
        "danger": danger or [],
        "danger_refutation": refutation,
    }


def one_line_answer(signal: dict[str, Any], role: str = "new_problem") -> dict[str, Any]:
    return {
        "messages": [
            {"id": "m1", "role": role, "signals": [signal["ref"]], "link_certainty": "sure"}
        ],
        "signals": [signal],
    }


def use_model(
    pv: Any,  # noqa: F811
    response: dict[str, Any] | None = None,
    scenario: str = "ok",
) -> FakeProvider:
    provider = FakeProvider(scenario, response)  # type: ignore[arg-type]
    pv.container.passive_analysis.analyzer = WindowAnalyzer(provider)
    return provider


async def conversation(
    pv: Any,  # noqa: F811
    lines: tuple[str, ...],
    *,
    start: float,
    chat: str = CHAT_1,
    first_author: int = 0,
) -> None:
    for index, text in enumerate(lines):
        actor = NEIGHBOURS[(first_author + index) % len(NEIGHBOURS)]
        await pv.say(text, chat=chat, actor=actor, at=ago(start - 5 * index))


async def settle(pv: Any) -> None:  # noqa: F811
    """Закрыть окна по тишине и разобрать их: оба пула, как в установке."""
    await pv.drain("operational")
    await pv.drain_all()


# ------------------------------------------------------------- ветка и счётчики


async def test_a_thread_of_seven_lines_is_one_signal_with_growing_counters(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600, chat=CHAT_1)
    await settle(pv)
    first = await pv.scalar(select(Signal))
    assert first.subtype == "elevator.stopped" and first.strength == "weak"
    assert first.disposition == "inbox"
    assert first.entrance is not None and first.entrance["value"] == "2"
    assert first.entrance["quote"] and first.entrance["line_mid"]
    lines_before, authors_before = first.report_count, first.author_count
    assert lines_before == 3 and authors_before == 3

    # Продолжение ветки через пять минут: двое новых соседей и один прежний.
    await conversation(pv, LIFT_SECOND, start=300, chat=CHAT_1, first_author=2)
    await settle(pv)
    signals = await pv.all(select(Signal))
    assert len(signals) == 1, "ветка об одном дефекте не создаёт второй строки"
    signal = signals[0]
    assert signal.report_count == 6 and signal.report_count > lines_before
    assert signal.author_count == 5 and signal.author_count > authors_before
    assert signal.last_seen_at > first.last_seen_at
    quotes = await pv.all(select(SignalQuote).where(SignalQuote.signal_id == signal.id))
    assert len(quotes) == 3
    assert all(quote.text in LIFT_FIRST + LIFT_SECOND for quote in quotes)
    kinds = [event.kind for event in await pv.all(select(SignalEvent))]
    assert "signal_grouped" in kinds
    windows = await pv.all(select(ConversationWindow))
    assert {window.state for window in windows} == {"done"}
    assert all(window.execution_state == "disabled" for window in windows)  # правила


async def test_the_rules_signal_carries_route_quotes_and_line_roles(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await settle(pv)
    signal = await pv.scalar(select(Signal))
    outcome = await pv.scalar(
        select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id)
    )
    assert outcome.source == "passive" and outcome.signal_id == signal.id
    assert outcome.route_type == "uk_internal" and outcome.decision == "needs_clarification"
    roles = {
        line.line_mid: line.role
        for line in await pv.all(select(SignalLine))
    }
    assert sorted(roles.values(), key=str) == sorted(
        ["new_problem", "new_problem", "me_too", "status_question"], key=str
    )
    unlinked = await pv.all(select(SignalLine).where(SignalLine.signal_id.is_(None)))
    assert [line.role for line in unlinked] == ["status_question"]
    consumed = await pv.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.consumed_at.is_not(None))
    )
    assert consumed == 4
    # Заявка и обращение из пассивного сигнала автоматически не создаются.
    from domsignal.db.models import Incident, Report

    assert await pv.scalar(select(func.count()).select_from(Incident)) == 0
    assert await pv.scalar(select(func.count()).select_from(Report)) == 0


# ------------------------------------------------------------- Audit Pool


async def test_weak_overflow_goes_to_the_audit_pool(pv) -> None:  # noqa: F811
    await pv.bind()
    pv.configure(weak_daily_limit=1)
    await pv.say("Лифт во втором подъезде не работает", at=ago(600))
    await pv.say("На улице у остановки не горит фонарь, темно", at=ago(300))
    await settle(pv)
    signals = await pv.all(select(Signal).order_by(Signal.created_at))
    assert [(item.strength, item.disposition, item.audit_reason) for item in signals] == [
        ("weak", "inbox", None),
        ("weak", "audit_pool", "weak_overflow"),
    ]
    kinds = [event.kind for event in await pv.all(select(SignalEvent))]
    assert "weak_overflow" in kinds


async def test_a_filtered_signal_goes_to_the_audit_pool_and_not_to_the_inbox(pv) -> None:  # noqa: F811
    await pv.bind()
    text = "У мамы в доме лифт третий день не работает"
    use_model(
        pv,
        one_line_answer(
            model_signal(
                subtype="elevator.stopped",
                obj="лифт",
                facets={
                    "current": facet("yes", "третий день не работает", "m1"),
                    "local": facet("no", "У мамы в доме", "m1"),
                    "observed": facet("yes", "лифт третий день не работает", "m1"),
                },
            ),
            role="out_of_scope",
        ),
    )
    await pv.say(text, at=ago(120))
    await settle(pv)
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "filtered" and signal.disposition == "audit_pool"
    assert signal.audit_reason in {"filtered", "audit_sample"}
    async with pv.container.session_factory() as session:
        inbox = await preview(session, house_id=pv.ids["h1"], pool="inbox")
        audit = await preview(session, house_id=pv.ids["h1"], pool="audit")
    assert inbox == [] and [item["id"] for item in audit] == [str(signal.id)]


# --------------------------------------------------- опасность против окна


async def test_a_downgrade_needs_a_quote_and_leaves_an_audit_event(pv) -> None:  # noqa: F811
    await pv.bind()
    use_model(
        pv,
        one_line_answer(
            model_signal(
                subtype="gas.smell",
                obj="газ в подъезде",
                scope=("house_common", "в подъезде", "m1"),
                facets={
                    "current": facet("no", "аварийка уже всё починила", "m1"),
                    "local": facet("yes", "в подъезде", "m1"),
                    "observed": facet("yes", "пахло газом", "m1"),
                },
                refutation={
                    "reason": "resolved",
                    "quote": "аварийка уже всё починила",
                    "msg": "m1",
                },
            ),
            role="resolved_claim",
        ),
    )
    await pv.say(REFUTED_GAS, at=ago(30))
    preliminary = await pv.scalar(select(Signal))
    assert preliminary.strength == "critical" and "preliminary" in preliminary.flags
    await pv.drain_all()
    signal = await pv.scalar(select(Signal))
    assert signal.id == preliminary.id, "примирение, а не второй сигнал"
    assert signal.strength == "filtered" and signal.disposition == "audit_pool"
    assert "preliminary" not in signal.flags and "reconciled" in signal.flags
    assert signal.subtype == "gas.smell"
    downgrade = signal.emergency["downgrades"][0]
    assert downgrade["reason"] == "resolved" and "аварийка уже всё починила" in downgrade["details"]
    event = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "emergency_downgraded"))
    assert event.signal_id == signal.id
    assert "аварийка уже всё починила" in event.details and "resolved" in event.details
    assert event.versions["taxonomy"] and event.versions["model"] == "fake/deterministic"


async def test_a_refutation_without_a_valid_quote_keeps_the_danger(pv) -> None:  # noqa: F811
    await pv.bind()
    use_model(
        pv,
        one_line_answer(
            model_signal(
                subtype="gas.smell",
                obj="газ",
                facets={
                    "current": facet("no", "всё давно исправили", "m1"),
                    "local": facet("yes"),
                    "observed": facet("yes"),
                },
                refutation={"reason": "resolved", "quote": "всё давно исправили", "msg": "m1"},
            )
        ),
    )
    await pv.say("Пахнет газом в третьем подъезде", at=ago(30))
    await pv.drain_all()
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "critical" and signal.disposition == "inbox"
    kinds = {event.kind for event in await pv.all(select(SignalEvent))}
    assert "refutation_rejected" in kinds and "emergency_downgraded" not in kinds


async def test_semantic_danger_alerts_the_operator_but_stays_out_of_the_chat(pv) -> None:  # noqa: F811
    await pv.bind()
    use_model(
        pv,
        one_line_answer(
            model_signal(
                subtype="electrical.panel",
                obj="щиток",
                scope=("house_common", "В щитке на этаже", "m1"),
                facets={
                    "current": facet("yes", "вспышки и треск", "m1"),
                    "local": facet("yes", "на этаже", "m1"),
                    "observed": facet("yes", "вспышки и треск", "m1"),
                },
                danger=[
                    {
                        "kind": "electric",
                        "evidence": [{"msg": "m1", "quote": "вспышки и треск"}],
                        "contextual": False,
                    }
                ],
            )
        ),
    )
    await pv.say("В щитке на этаже вспышки и треск", at=ago(60))
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0
    await settle(pv)
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "critical" and signal.emergency["sources"] == ["semantic"]
    assert len(await pv.jobs("signal.alert")) == 1
    await pv.deliver()
    assert pv.messaging.sent
    assert "Признак найден при разборе переписки." in pv.messaging.sent[0][2].text
    assert not pv.memos(), "семантическая опасность не пишет в чат"


# --------------------------------------------------------- отказы и бюджет


async def test_an_unavailable_provider_falls_back_to_rules(pv) -> None:  # noqa: F811
    await pv.bind()
    provider = use_model(pv, scenario="error")
    await conversation(pv, LIFT_FIRST, start=600)
    await settle(pv)
    assert provider.requests, "провайдер получил ровно один вызов"
    assert len(provider.requests) == 1
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.execution_state == "fallback_provider_error"
    assert window.analysis_mode == "rules" and window.analysis["provider_called"] is True
    signal = await pv.scalar(select(Signal))
    assert signal.subtype == "elevator.stopped" and signal.source == "rules"


async def test_an_exhausted_budget_means_no_call_at_all(pv) -> None:  # noqa: F811
    await pv.bind()
    provider = FakeProvider("ok")
    budget = PostgresBudgetGuard(pv.container.session_factory, daily_calls=0)
    pv.container.passive_analysis.analyzer = WindowAnalyzer(
        ResilientProvider(
            provider, breaker=CircuitBreaker(), limiter=ConcurrencyLimiter(2), budget=budget
        )
    )
    pv.container.passive_analysis.budget = budget
    await conversation(pv, LIFT_FIRST, start=600)
    await settle(pv)
    assert provider.requests == []
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.execution_state == "fallback_budget"
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1


async def test_two_tasks_racing_on_one_window_give_one_set_of_signals(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.drain("operational")
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed"
    payload = {"window_id": str(window.id)}
    analysis = pv.container.passive_analysis
    await asyncio.gather(analysis.analyze_window(payload), analysis.analyze_window(payload))
    await analysis.analyze_window(payload)  # повторный запуск после завершения
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1
    assert await pv.scalar(select(func.count()).select_from(RouteOutcome)) == 1
    assert await pv.scalar(select(func.count()).select_from(SignalLine)) == 4


async def test_a_stale_claim_loses_the_write_to_the_worker_that_took_over(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.drain("operational")
    window = await pv.scalar(select(ConversationWindow))
    payload = {"window_id": str(window.id)}
    slow = PassiveWindowAnalysis(
        session_factory=pv.container.session_factory,
        engine=pv.container.signals,
        analyzer=WindowAnalyzer(FakeProvider("ok", delay_seconds=1.0)),
    )
    first = asyncio.create_task(slow.analyze_window(payload))
    await asyncio.sleep(0.3)
    # Первый воркер «завис»: его захват устарел, окно берёт другой.
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ConversationWindow)
            .where(ConversationWindow.id == window.id)
            .values(claimed_at=datetime.now(UTC) - timedelta(minutes=11))
        )
    await pv.container.passive_analysis.analyze_window(payload)
    await first
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 1
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.execution_state == "disabled"


async def test_analysis_after_the_switch_is_off_writes_no_signals(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await pv.set_capture(binding, enabled=False)
    await settle(pv)
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "done" and window.execution_state == "capture_stopped"
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0


# ------------------------------------------------------------------- маршрут


async def test_a_subtype_outside_the_uk_gets_an_external_route(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("На улице у остановки не горит фонарь, темно", at=ago(120))
    await settle(pv)
    signal = await pv.scalar(select(Signal))
    assert signal.subtype == "street_lighting.failure"
    outcome = await pv.scalar(select(RouteOutcome).where(RouteOutcome.signal_id == signal.id))
    assert outcome.route_type == "municipality" and outcome.decision == "external"
    assert outcome.organization_id is None  # организация не выдумывается


async def test_an_unknown_subtype_routes_to_unknown_without_inventions(pv) -> None:  # noqa: F811
    await pv.bind()
    use_model(pv, one_line_answer(model_signal(subtype="invented.code", obj="что-то")))
    await pv.say("Безобразие, опять всё сломали и никто не чинит", at=ago(120))
    await settle(pv)
    signal = await pv.scalar(select(Signal))
    assert signal.subtype == "other.unspecified"
    outcome = await pv.scalar(select(RouteOutcome).where(RouteOutcome.signal_id == signal.id))
    assert outcome.route_type == "unknown"
    assert outcome.organization_id is None and outcome.channel_id is None
    dropped = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "field_dropped"))
    assert dropped is not None and dropped.signal_id == signal.id


# ------------------------------------------------------------------- изоляция


async def test_two_houses_never_mix_lines_windows_or_signals(pv) -> None:  # noqa: F811
    await pv.bind(chat=CHAT_1, house="h1", admin="admin1")
    await pv.bind(chat=CHAT_2, house="h2", admin="admin2")
    for index, text in enumerate(LIFT_FIRST):
        await pv.say(text, chat=CHAT_1, actor=NEIGHBOURS[index], at=ago(600 - 5 * index))
        await pv.say(
            "На улице у остановки не горит фонарь, темно" if index == 0 else "Да, темно",
            chat=CHAT_2,
            actor=NEIGHBOURS[index],
            at=ago(599 - 5 * index),
        )
    provider = use_model(pv, scenario="error")
    await settle(pv)
    windows = await pv.all(select(ConversationWindow))
    assert len(windows) == 2
    for window in windows:
        chat_lines = await pv.all(select(ChatMessage).where(ChatMessage.window_id == window.id))
        assert {line.max_chat_id for line in chat_lines} == {window.max_chat_id}
    chat_of_mid = {line.mid: line.max_chat_id for line in await pv.all(select(ChatMessage))}
    chat_of_house = {pv.ids["h1"]: CHAT_1, pv.ids["h2"]: CHAT_2}
    signals = await pv.all(select(Signal))
    assert {signal.house_id for signal in signals} == set(chat_of_house)
    for signal in signals:
        mids = [
            line.line_mid
            for line in await pv.all(select(SignalLine).where(SignalLine.signal_id == signal.id))
        ]
        assert mids and {chat_of_mid[mid] for mid in mids} == {chat_of_house[signal.house_id]}
    by_house = {signal.house_id: signal for signal in signals if signal.house_id == pv.ids["h1"]}
    assert by_house[pv.ids["h1"]].subtype == "elevator.stopped"
    assert {
        signal.product_category for signal in signals if signal.house_id == pv.ids["h2"]
    } == {"lighting"}
    # Одни и те же люди — разные псевдонимы в разных домах начинаются заново.
    aliases = {
        (line.max_chat_id, line.author_ref)
        for line in await pv.all(select(ChatMessage).where(ChatMessage.sent_at < ago(597)))
    }
    assert aliases == {(CHAT_1, "A"), (CHAT_2, "A")}
    # В запрос окна одного дома не уходят открытые элементы другого.
    for request in provider.requests:
        assert all(item.title != by_house[pv.ids["h1"]].object_label for item in request.open_items)


# ----------------------------------------------------------- хранение и чат


async def test_purge_removes_consumed_and_expired_lines_but_keeps_quotes(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST + LIFT_SECOND, start=900)
    await settle(pv)
    assert await pv.scalar(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.consumed_at.is_not(None))
    ) == 7
    # Свежая неразобранная реплика и одна просроченная.
    await pv.say("Ещё открытое окно", at=ago(5))
    await pv.say("Совсем старая реплика", at=ago(4))
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ChatMessage)
            .where(ChatMessage.text == "Совсем старая реплика")
            .values(received_at=datetime.now(UTC) - timedelta(hours=73))
        )
    assert await pv.container.passive.ensure_purge_scheduled() is True
    assert await pv.container.passive.ensure_purge_scheduled() is False
    await pv.drain("operational")
    remaining = await pv.all(select(ChatMessage).order_by(ChatMessage.sent_at))
    consumed = [line for line in remaining if line.consumed_at is not None]
    assert len(consumed) == 5, "остаются только реплики контекста"
    assert "Совсем старая реплика" not in {line.text for line in remaining}
    assert "Ещё открытое окно" in {line.text for line in remaining}
    signal = await pv.scalar(select(Signal))
    assert await pv.scalar(
        select(func.count()).select_from(SignalQuote).where(SignalQuote.signal_id == signal.id)
    ) == 3
    assert signal.report_count == 6
    purge = (await pv.jobs("chat.buffer.purge"))[0]
    assert purge.status == "pending" and purge.next_attempt_at > datetime.now(UTC)


async def test_the_reading_notice_is_sent_once_per_binding_version(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    first = await pv.set_capture(binding, enabled=True)
    assert first.notice_queued is False, "уже поставлено при первом включении"
    await pv.set_capture(binding, enabled=False)
    await pv.set_capture(binding, enabled=True)
    notices = await pv.all(
        select(OutboxMessage).where(
            OutboxMessage.kind == CHAT_MESSAGE_INTENT_KIND,
            OutboxMessage.payload["purpose"].astext == "chat_reading_notice",
        )
    )
    assert len(notices) == 1
    await pv.deliver()
    assert len(pv.notices()) == 1
    chat_id, _, message = pv.notices()[0]
    assert chat_id == CHAT_1
    assert "«УК Первая (тест)»" in message.text
    assert "не является официальным обращением" in message.text
    delivery = await pv.scalar(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "chat_reading_notice")
    )
    assert delivery.status == "accepted" and delivery.provider_message_id == "mid.chat-1"


async def test_chat_messages_stay_queued_when_max_transport_is_off(pv) -> None:  # noqa: F811
    await pv.bind()
    pv.container.notifications.enabled = False  # MAX_TRANSPORT=off: отправитель инертен
    await pv.say("Пахнет газом в третьем подъезде", at=ago(5))
    await pv.deliver()
    assert not pv.messaging.chat_sent and not pv.messaging.sent
    pending = await pv.all(
        select(NotificationDelivery).where(NotificationDelivery.status == "pending")
    )
    assert {item.purpose for item in pending} == {
        "chat_reading_notice",
        "chat_safety_memo",
        "signal_alert",
    }


async def test_the_memo_is_superseded_when_reading_is_turned_off_before_sending(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    pv.container.notifications.enabled = False
    await pv.say("Пахнет газом в третьем подъезде", at=ago(5))
    await pv.deliver()
    await pv.set_capture(binding, enabled=False)
    pv.container.notifications.enabled = True
    await pv.deliver()
    assert not pv.memos() and not pv.notices()
    memo = await pv.scalar(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "chat_safety_memo")
    )
    assert memo.status == "superseded"
    # Оповещение оператора от выключателя чтения не зависит.
    assert pv.messaging.sent


async def test_no_log_line_contains_text_or_the_external_user_id(pv, caplog) -> None:  # noqa: F811
    import logging

    caplog.set_level(logging.DEBUG)
    await pv.bind()
    await pv.say("Пахнет газом в третьем подъезде у квартиры 12", actor=NEIGHBOURS[3], at=ago(30))
    await conversation(pv, LIFT_FIRST, start=600)
    await settle(pv)
    await pv.deliver()
    standard = set(vars(logging.makeLogRecord({})))
    ours = [record for record in caplog.records if record.name.startswith("domsignal")]
    assert ours, "события пассивного пути журналируются"
    for record in ours:
        assert record.levelno < logging.ERROR, record.getMessage()
        extra = {key: value for key, value in vars(record).items() if key not in standard}
        rendered = record.getMessage() + " " + " ".join(f"{k}={v}" for k, v in extra.items())
        assert "газом" not in rendered and "Лифт" not in rendered and "квартиры" not in rendered
        # Идентификатор ищется целым токеном: случайный hex отпечатка входа
        # может содержать те же цифры, и это не утечка.
        assert not re.search(rf"{NEIGHBOURS[3]}", rendered), rendered


async def test_open_signals_of_the_house_reach_the_window_as_open_items(pv) -> None:  # noqa: F811
    await pv.bind()
    await conversation(pv, LIFT_FIRST, start=600)
    await settle(pv)
    signal = await pv.scalar(select(Signal))
    provider = use_model(pv)
    await pv.say("Лифт во втором подъезде всё ещё не работает", at=ago(120))
    await settle(pv)
    request = provider.requests[0]
    assert [item.title for item in request.open_items] == [signal.object_label]
    assert request.open_items[0].ref == "open:1"
    # Контекст — предыдущие реплики чата, только для чтения.
    assert [line.is_context for line in request.lines].count(True) == 4
    jobs = await pv.all(select(Job).where(Job.kind == "ai.window.analyze"))
    assert all(job.status == "succeeded" for job in jobs)
