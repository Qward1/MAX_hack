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


# ------------------------- живой шаг 6: новый вид при открытой опасности


async def test_a_trapped_person_is_not_glued_to_an_open_smoke_signal_by_key(pv) -> None:  # noqa: F811
    """Живой шаг 6 P6b (повтор): модель вернула новый сигнал `person_trapped`,
    а продукт склеил его с открытым дымовым по ключу дедупликации — у обоих
    подтип `other.unspecified` без подъезда. Вид K не ложится в сигнал без K.
    """
    from tests.integration.test_p7b_alerts import alert_intents, verdict
    from tests.integration.test_passive_signals import facet, model_signal, settle, use_model

    await pv.bind()
    await pv.say("и дымом тоже тянет", actor=NEIGHBOURS[0], at=ago(600))
    await settle(pv)
    await pv.deliver()
    smoke = await pv.scalar(select(Signal))
    assert smoke.emergency["kinds"] == ["smoke_fire"]
    use_model(
        pv,
        {
            "messages": [
                verdict("m2", "status_question", "new:1"),
                verdict("m3", "new_problem", "new:1"),
                verdict("m4", "more_info", "new:1"),
            ],
            "signals": [
                model_signal(
                    subtype="other.unspecified",
                    obj="человек за дверью",
                    facets={
                        "current": facet("yes", "женщина стучит", "m3"),
                        "local": facet("unclear"),
                        "observed": facet("yes", "женщина стучит", "m3"),
                    },
                    danger=[
                        {
                            "kind": "person_trapped",
                            "evidence": [{"msg": "m3", "quote": "женщина стучит"}],
                            "contextual": True,
                        }
                    ],
                )
            ],
        },
    )
    await pv.say("Там кто-нибудь внутри?", actor=NEIGHBOURS[0], at=ago(120))
    await pv.say("Да, женщина стучит", actor=NEIGHBOURS[0], at=ago(110))
    await pv.say("Двери вообще не открываются", actor=NEIGHBOURS[0], at=ago(100))
    await settle(pv)
    await pv.deliver()
    stored = await pv.scalar(select(Signal).where(Signal.id == smoke.id))
    assert stored.emergency["kinds"] == ["smoke_fire"], "дымовой сигнал не поглотил новый вид"
    trapped = await pv.scalar(select(Signal).where(Signal.id != smoke.id))
    assert trapped is not None and trapped.strength == "critical"
    assert trapped.emergency["kinds"] == ["person_trapped"]
    intents = await alert_intents(pv)
    assert intents[-1]["signal_id"] == str(trapped.id)
    assert intents[-1]["new_kinds"] == [], "первое оповещение нового сигнала"
    assert not pv.memos(), "смысловая опасность в чат не пишет; «и дымом» без места — тоже"
