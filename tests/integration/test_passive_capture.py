"""Приём всех реплик привязанного чата, опасность в приёме и сборщик окон."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from domsignal.db.models import (
    ChatBinding,
    ChatMessage,
    ConversationWindow,
    ExplicitIntake,
    Job,
    NotificationDelivery,
    OutboxMessage,
    Signal,
    SignalEvent,
    SignalLine,
)
from domsignal.services.chat_voice import CHAT_MESSAGE_INTENT_KIND
from domsignal.worker.pools import AI_JOB_KINDS, pool_for
from tests.integration.passive_harness import (
    CHAT_1,
    NEIGHBOURS,
    RESIDENT,
    pv,  # noqa: F401
)

GAS = "Пахнет газом в третьем подъезде"


def ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


# ------------------------------------------------------------------- приём


async def test_an_ordinary_line_lands_in_the_buffer_once(pv) -> None:  # noqa: F811
    await pv.bind()
    at = ago(30)
    mid = await pv.say("Лифт во втором подъезде опять стоит", at=at, reply_to="mid.earlier")
    # Повтор того же вебхука — вторая строка не появляется.
    await pv.say("Лифт во втором подъезде опять стоит", at=at, mid=mid, reply_to="mid.earlier")
    rows = await pv.all(select(ChatMessage))
    assert len(rows) == 1
    row = rows[0]
    assert row.mid == mid and row.max_chat_id == CHAT_1
    assert row.author_ref == "A"
    assert row.reply_to_mid == "mid.earlier"
    assert row.text == "Лифт во втором подъезде опять стоит" and not row.text_truncated
    assert row.window_id is not None and row.consumed_at is None
    assert abs((row.sent_at - at).total_seconds()) < 1


async def test_a_long_line_is_truncated_with_a_flag(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Лифт " + "стоит " * 900, at=ago(30))
    row = await pv.scalar(select(ChatMessage))
    assert len(row.text) == 4000 and row.text_truncated


async def test_the_same_author_keeps_one_alias_across_chats_of_the_house(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Первая реплика", actor=NEIGHBOURS[0], at=ago(40))
    await pv.say("Вторая реплика", actor=NEIGHBOURS[1], at=ago(35))
    await pv.say("Третья реплика", actor=NEIGHBOURS[0], at=ago(30))
    rows = await pv.all(select(ChatMessage).order_by(ChatMessage.sent_at))
    aliases = [row.author_ref for row in rows]
    assert aliases == ["A", "B", "A"]


async def test_structural_filter_drops_everything_that_is_not_conversation(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    await pv.say("Бот пишет сам себе", is_bot=True, at=ago(50))
    await pv.say("Сообщение канала", chat_type="channel", at=ago(49))
    await pv.say(None, at=ago(48))
    await pv.say("   ", at=ago(47))
    await pv.say("Чужой чат без привязки", chat="-799", at=ago(46))
    # Событие раньше активации привязки.
    await pv.say("Реплика до подключения", at=datetime.now(UTC) - timedelta(hours=5))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 0
    # Неактивная привязка.
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ChatBinding).where(ChatBinding.id == binding).values(status="suspended")
        )
    await pv.say("Реплика после отключения привязки", at=ago(10))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 0


async def test_disabled_capture_stores_nothing_at_all(pv) -> None:  # noqa: F811
    binding = await pv.bind(enable=False)
    await pv.say("Лифт стоит", at=ago(20))
    await pv.say(GAS, at=ago(10))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0
    await pv.set_capture(binding, enabled=True)
    await pv.say("Лифт стоит", at=ago(5))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 1
    # Выключение сразу прекращает приём и не трогает собранное.
    await pv.set_capture(binding, enabled=False)
    await pv.say("Ещё одна реплика", at=ago(1))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 1


async def test_global_switch_off_stores_nothing(pv) -> None:  # noqa: F811
    await pv.bind()
    pv.container.signals.config = pv.container.signals.config.__class__(
        **{**pv.container.signals.config.__dict__, "capture_enabled": False}
    )
    await pv.say("Лифт стоит", at=ago(10))
    await pv.say(GAS, at=ago(5))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0


async def test_report_commands_keep_their_own_path(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("/report elevator Лифт во втором подъезде не едет", actor=RESIDENT, at=ago(20))
    await pv.say("/report во дворе не горит фонарь у подъезда", actor=RESIDENT, at=ago(10))
    assert await pv.scalar(select(func.count()).select_from(ChatMessage)) == 0
    pending = select(Job).where(Job.status == "pending").order_by(Job.created_at, Job.priority)
    assert [job.kind for job in await pv.all(pending)] == [
        "max.group.report",
        "ai.report.analyze",
        "report.fallback",
    ]
    assert await pv.scalar(select(func.count()).select_from(ExplicitIntake)) == 1


# --------------------------------------------------------------- опасность


async def test_gas_in_the_chat_gives_an_alert_and_a_memo_with_the_ai_pool_stopped(pv) -> None:  # noqa: F811
    binding = await pv.bind()
    mid = await pv.say(GAS, at=ago(5))
    # Прямо в транзакции приёма: сигнал, закрытое окно, разбор и оповещение.
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "critical" and signal.disposition == "inbox"
    assert signal.source == "rules" and "preliminary" in signal.flags
    assert signal.emergency["kinds"] == ["gas"]
    assert signal.emergency["evidence"][0]["line_mid"] == mid
    assert signal.route_outcome_id is not None
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed" and window.close_reason == "danger" and window.has_danger
    analyze = await pv.jobs("ai.window.analyze")
    assert len(analyze) == 1 and analyze[0].priority == 20
    alert = await pv.jobs("signal.alert")
    assert len(alert) == 1 and alert[0].priority == 10 and pool_for("signal.alert") == "operational"
    assert "ai.window.analyze" in AI_JOB_KINDS

    # Работает только операционный пул: AI-пул остановлен.
    await pv.deliver()
    assert (await pv.jobs("ai.window.analyze"))[0].status == "pending"
    alerts = await pv.all(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "signal_alert")
    )
    assert len(alerts) == 1 and alerts[0].status == "accepted"
    assert alerts[0].recipient_user_id == pv.ids["admin1"]
    destination, _, message = pv.messaging.sent[0]
    assert destination == "701"
    assert "запах газа" in message.text and GAS in message.text
    memos = pv.memos()
    assert len(memos) == 1 and memos[0][0] == CHAT_1
    assert "112" in memos[0][2].text and "Федеральный закон" in memos[0][2].text
    assert len(pv.notices()) == 1, "сообщение о чтении чата ушло раньше памятки"
    memo_delivery = await pv.scalar(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "chat_safety_memo")
    )
    assert memo_delivery.chat_binding_id == binding and memo_delivery.recipient_user_id is None


async def test_negated_danger_gives_no_signal_and_no_memo(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Газом не пахнет, всё проверили", at=ago(5))
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0
    event = await pv.scalar(select(SignalEvent))
    assert event.kind == "danger_negated" and event.signal_id is None
    assert event.details == "gas"
    await pv.deliver()
    assert not pv.memos() and not pv.messaging.sent
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "open"


async def test_displaced_danger_is_preliminary_without_a_memo(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("В соседнем доме вчера пахло газом, приезжала служба", at=ago(5))
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "critical" and "displaced" in signal.flags
    assert signal.emergency["memo_allowed"] is False
    await pv.deliver()
    assert pv.messaging.sent, "оператор оповещён"
    assert not pv.memos(), "памятки в чат нет"
    queued = await pv.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.kind == CHAT_MESSAGE_INTENT_KIND)
    )
    assert queued == 1  # только сообщение о чтении чата


async def test_repeated_gas_reports_group_and_the_memo_is_not_repeated(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(GAS, actor=NEIGHBOURS[0], at=ago(40))
    await pv.say("Да, в третьем подъезде сильно пахнет газом", actor=NEIGHBOURS[1], at=ago(30))
    signals = await pv.all(select(Signal))
    assert len(signals) == 1
    assert signals[0].report_count == 2 and signals[0].author_count == 2
    assert len(await pv.jobs("signal.alert")) == 1
    memos = await pv.all(
        select(OutboxMessage).where(
            OutboxMessage.kind == CHAT_MESSAGE_INTENT_KIND,
            OutboxMessage.payload["purpose"].astext == "chat_safety_memo",
        )
    )
    assert len(memos) == 1


async def test_no_staff_with_max_means_a_skipped_alert_and_the_signal_stays(pv) -> None:  # noqa: F811
    from domsignal.db.models import User

    await pv.bind()
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(User).where(User.id == pv.ids["admin1"]).values(max_identity_verified_at=None)
        )
    await pv.say(GAS, at=ago(5))
    await pv.drain("operational")
    delivery = await pv.scalar(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "signal_alert")
    )
    assert delivery.status == "skipped" and delivery.last_error_code == "NO_RECIPIENTS"
    assert delivery.recipient_user_id is None
    signal = await pv.scalar(select(Signal))
    assert signal.disposition == "inbox" and signal.strength == "critical"
    kinds = [event.kind for event in await pv.all(select(SignalEvent))]
    assert "operator_alert_skipped" in kinds


# ------------------------------------------------------------------- окна


async def test_ten_lines_close_the_window_in_the_intake_transaction(pv) -> None:  # noqa: F811
    await pv.bind()
    for index in range(10):
        await pv.say(f"Реплика номер {index}", actor=NEIGHBOURS[index % 3], at=ago(60 - index))
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed" and window.close_reason == "max_lines"
    assert window.line_count == 10
    assert len(await pv.jobs("ai.window.analyze")) == 1
    await pv.say("Одиннадцатая реплика", at=ago(1))
    windows = await pv.all(select(ConversationWindow).order_by(ConversationWindow.created_at))
    assert [item.state for item in windows] == ["closed", "open"]


async def test_age_closes_the_window_when_the_next_line_arrives(pv) -> None:  # noqa: F811
    await pv.bind()
    pv.configure(policy={"max_lines": 35})
    # Реплики каждые 15 секунд — тишины нет, но возраст окна переваливает за 300 с.
    start = ago(400)
    for index in range(22):
        await pv.say(f"Разговор {index}", at=start + timedelta(seconds=15 * index))
    windows = await pv.all(select(ConversationWindow).order_by(ConversationWindow.first_line_at))
    assert [item.close_reason for item in windows] == ["max_age", None]
    assert windows[0].line_count == 21  # 0…300 с включительно; 315-я секунда — новое окно
    assert windows[1].line_count == 1 and windows[1].state == "open"


async def test_silence_closes_the_window_through_one_tick_job(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Лифт снова стоит", at=ago(60))
    await pv.say("Да, с утра", actor=NEIGHBOURS[1], at=ago(55))
    ticks = await pv.jobs("chat.window.tick")
    assert len(ticks) == 1, "одна задача тишины на окно"
    window = await pv.scalar(select(ConversationWindow))
    assert window.tick_job_id == ticks[0].id
    await pv.drain("operational")
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed" and window.close_reason == "silence"
    assert len(await pv.jobs("ai.window.analyze")) == 1


async def test_the_tick_reschedules_itself_while_the_chat_is_talking(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Лифт снова стоит", at=ago(2))
    tick = (await pv.jobs("chat.window.tick"))[0]
    # Тишина ещё не наступила: тик переносит себя, а не плодит новые задачи.
    await pv.drain("operational", now=tick.next_attempt_at + timedelta(seconds=1))
    await pv.runner("operational").process(await _claim(pv, tick.id))
    ticks = await pv.jobs("chat.window.tick")
    assert len(ticks) == 1 and ticks[0].status == "pending"
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "open"


async def _claim(pv, job_id):  # noqa: ANN001, ANN202, F811
    """Взять конкретную задачу, не дожидаясь её времени."""
    from domsignal.worker.runner import ClaimedJob

    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(Job).where(Job.id == job_id).values(next_attempt_at=datetime.now(UTC))
        )
    runner = pv.runner("operational")
    claimed = await runner.claim()
    assert isinstance(claimed, ClaimedJob) and claimed.id == job_id
    return claimed


async def test_a_repeated_tick_on_a_closed_window_does_nothing(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Лифт снова стоит", at=ago(60))
    window = await pv.scalar(select(ConversationWindow))
    await pv.container.passive.tick({"window_id": str(window.id)})
    await pv.container.passive.tick({"window_id": str(window.id)})
    assert len(await pv.jobs("ai.window.analyze")) == 1
    window = await pv.scalar(select(ConversationWindow))
    assert window.state == "closed"


async def test_a_worker_restart_neither_loses_nor_duplicates_the_window(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("Лифт снова стоит", at=ago(60))
    tick = (await pv.jobs("chat.window.tick"))[0]
    # Воркер взял тик и упал: аренда истекла, задачу добирает другой процесс.
    runner = pv.runner("operational")
    claimed = await runner.claim()
    assert claimed is not None and claimed.id == tick.id
    later = datetime.now(UTC) + timedelta(seconds=runner.lease_seconds + 5)
    await pv.drain("operational", now=later)
    windows = await pv.all(select(ConversationWindow))
    assert len(windows) == 1 and windows[0].state == "closed"
    assert len(await pv.jobs("ai.window.analyze")) == 1
    lines = await pv.all(select(SignalLine))
    assert lines == []  # разбор ещё не шёл: AI-пул не запускался
