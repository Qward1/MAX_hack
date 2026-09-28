"""D-06 (живой прогон 28.09): одна реплика о газе не даёт двух критических сигналов.

Повтор опасности присоединяется к открытому газовому сигналу при приёме;
если модель прочитала ту же реплику ещё раз, с темой из контекста прошлой
ветки («домофон»), второй критический сигнал и второе оповещение оператору
не появляются.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from domsignal.db.models import Signal
from tests.integration.passive_harness import NEIGHBOURS, pv  # noqa: F401
from tests.integration.test_passive_signals import ago, facet, model_signal, settle, use_model


def gas(ref: str, subtype: str, obj: str) -> dict[str, Any]:
    return model_signal(
        ref=ref,
        subtype=subtype,
        obj=obj,
        scope=("house_common", "на третьем этаже", "m1"),
        facets={
            "current": facet("yes", "газом пахнет", "m1"),
            "local": facet("yes", "на третьем этаже", "m1"),
            "observed": facet("yes", "газом пахнет", "m1"),
        },
        danger=[
            {
                "kind": "gas",
                "evidence": [{"msg": "m1", "quote": "газом пахнет"}],
                "contextual": False,
            }
        ],
    )


async def test_a_repeated_gas_line_read_twice_by_the_model_gives_one_critical_signal(
    pv,  # noqa: F811
) -> None:
    await pv.bind()
    await pv.say("Пахнет газом во втором подъезде", at=ago(400))
    await settle(pv)
    assert (
        await pv.scalar(
            select(func.count()).select_from(Signal).where(Signal.strength == "critical")
        )
        == 1
    )
    alerts_before = len(await pv.jobs("signal.alert"))
    use_model(
        pv,
        {
            "messages": [
                {
                    "id": "m1",
                    "role": "new_problem",
                    "signals": ["new:1", "new:2"],
                    "link_certainty": "sure",
                }
            ],
            "signals": [
                gas("new:1", "gas.smell", "запах газа"),
                gas("new:2", "intercom.broken", "домофон"),
            ],
        },
    )
    await pv.say("Да, на третьем этаже тоже газом пахнет", at=ago(60), actor=NEIGHBOURS[1])
    await settle(pv)
    critical = await pv.all(select(Signal).where(Signal.strength == "critical"))
    assert len(critical) == 1, [signal.object_label for signal in critical]
    assert len(await pv.jobs("signal.alert")) == alerts_before, "второго оповещения нет"
