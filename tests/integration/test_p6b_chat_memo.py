"""P6b: памятка в чат — только по высокоточному срабатыванию правил.

Живые шаги P6b на стенде без модели, настоящим путём приёма (вебхук →
буфер → правила опасности → сигнал, оповещение, памятка).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from domsignal.db.models import Signal, SignalEvent
from tests.integration.passive_harness import NEIGHBOURS, pv  # noqa: F401

DRILL = "Учебная пожарная тревога сегодня в 14:00, не пугайтесь"
THANKS = "Спасибо пожарным, приехали за 10 минут"
LIGHTING = "В третьем подъезде опять не горит свет на лестнице"
GAS = "Пахнет газом во втором подъезде"


def ago(seconds: float) -> datetime:
    return datetime.now(UTC) - timedelta(seconds=seconds)


async def events(pv) -> list[str]:  # noqa: F811
    return [event.kind for event in await pv.all(select(SignalEvent))]


async def test_a_drill_and_thanks_give_no_signal_and_no_memo(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(DRILL, actor=NEIGHBOURS[0], at=ago(60))
    await pv.say(THANKS, actor=NEIGHBOURS[1], at=ago(50))
    await pv.say(LIGHTING, actor=NEIGHBOURS[0], at=ago(40))
    await pv.deliver()
    critical = await pv.scalar(
        select(func.count()).select_from(Signal).where(Signal.strength == "critical")
    )
    assert critical == 0, "нет критического сигнала"
    assert not pv.memos(), "нет памятки в чат"
    assert not pv.messaging.sent, "оператор не оповещён"
    assert (await events(pv)).count("danger_negated") == 3


async def test_gas_gives_the_memo_and_the_alert(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(GAS, actor=NEIGHBOURS[0], at=ago(30))
    await pv.deliver()
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "critical" and signal.emergency["memo_allowed"] is True
    assert len(pv.memos()) == 1
    assert pv.messaging.sent, "оператор оповещён"
    assert "chat_memo_queued" in await events(pv)


async def test_a_hypothetical_alerts_the_operator_without_a_memo(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say("если пахнет газом — куда звонить, в ук или 104?", actor=NEIGHBOURS[0], at=ago(30))
    await pv.deliver()
    signal = await pv.scalar(select(Signal))
    assert signal.strength == "critical" and signal.emergency["memo_allowed"] is False
    assert not pv.memos()
    assert pv.messaging.sent, "оповещение оператора — как было"
    kinds = await events(pv)
    assert "chat_memo_not_eligible" in kinds and "chat_memo_queued" not in kinds
