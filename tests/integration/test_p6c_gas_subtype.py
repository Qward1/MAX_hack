"""P6c §1: газовый сигнал после разбора окна — «запах газа», а не «Другое».

Живой шаг 4 P6b: предварительный сигнал правил (подтип-заглушка
`other.unspecified`) уходил в `open_items` своего же окна; модель продолжала
его и повторяла заглушку, примирение записывало её в сигнал. Теперь окно не
видит собственного предварительного сигнала (оно примиряет его само по
привязке реплики), а заглушка подтипа модели не передаётся.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from domsignal.db.models import RouteOutcome, Signal, SignalEvent
from tests.integration.passive_harness import NEIGHBOURS, pv  # noqa: F401
from tests.integration.test_passive_signals import ago, facet, model_signal, settle, use_model

GAS_2 = "Пахнет газом во втором подъезде"


def verdict(msg: str, role: str, ref: str) -> dict[str, Any]:
    return {"id": msg, "role": role, "signals": [ref], "link_certainty": "sure"}


def gas_answer(*, ref: str, subtype: str) -> dict[str, Any]:
    return {
        "messages": [verdict("m1", "new_problem", ref)],
        "signals": [
            model_signal(
                subtype=subtype,
                obj="газ",
                ref=ref,
                facets={
                    "current": facet("yes", "Пахнет газом", "m1"),
                    "local": facet("unclear"),
                    "observed": facet("yes", "Пахнет газом", "m1"),
                },
                danger=[
                    {
                        "kind": "gas",
                        "evidence": [{"msg": "m1", "quote": "Пахнет газом"}],
                        "contextual": False,
                    }
                ],
            )
        ],
    }


async def test_the_window_does_not_see_its_own_preliminary_signal(pv) -> None:  # noqa: F811
    await pv.bind()
    provider = use_model(pv, gas_answer(ref="new:1", subtype="gas.smell"))
    await pv.say(GAS_2, actor=NEIGHBOURS[0], at=ago(60))
    await settle(pv)
    [request] = provider.requests
    assert request.open_items == (), "свой предварительный сигнал — не открытый элемент"
    [signal] = await pv.all(select(Signal))
    assert signal.subtype == "gas.smell"
    assert "reconciled" in signal.flags and "preliminary" not in signal.flags


async def test_live_step_4_the_model_repeating_the_placeholder_still_gives_gas_smell(
    pv,  # noqa: F811
) -> None:
    """Ответ той же формы, что в живом шаге 4: ссылка на открытый элемент и заглушка."""
    await pv.bind()
    use_model(pv, gas_answer(ref="open:1", subtype="other.unspecified"))
    await pv.say(GAS_2, actor=NEIGHBOURS[0], at=ago(60))
    await settle(pv)
    await pv.deliver()
    [signal] = await pv.all(select(Signal))
    assert signal.subtype == "gas.smell", "в кабинете «запах газа», а не «Другое»"
    assert signal.product_category == "other"
    assert signal.entrance is not None and signal.entrance["value"] == "2"
    assert signal.strength == "critical" and signal.emergency["kinds"] == ["gas"]
    assert {"reconciled", "subtype_from_danger"} <= set(signal.flags)
    route = select(RouteOutcome).where(RouteOutcome.id == signal.route_outcome_id)
    assert (await pv.scalar(route)).route_type == "emergency_service"
    events = [event.kind for event in await pv.all(select(SignalEvent))]
    assert "subtype_from_danger" in events
    assert events.count("operator_alert_requested") == 1, "одно оповещение на сигнал"


async def test_another_preliminary_signal_is_passed_without_its_placeholder(
    pv,  # noqa: F811
) -> None:
    """Предварительный сигнал другого, ещё не разобранного окна: подтип не передаётся."""
    await pv.bind()
    use_model(pv, gas_answer(ref="new:1", subtype="gas.smell"))
    await pv.say(GAS_2, actor=NEIGHBOURS[0], at=ago(600))
    await settle(pv)
    gas = await pv.scalar(select(Signal))
    # Состояние «окно газа ещё не разобрано»: заглушка правил, флаг preliminary.
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(Signal)
            .where(Signal.id == gas.id)
            .values(subtype="other.unspecified", flags=["preliminary"])
        )
    provider = use_model(pv, {"messages": [], "signals": []})
    await pv.say("Во дворе опять не горит фонарь", actor=NEIGHBOURS[1], at=ago(60))
    await settle(pv)
    [request] = provider.requests
    [item] = request.open_items
    assert item.subtype is None and item.danger_kinds == ("gas",)
