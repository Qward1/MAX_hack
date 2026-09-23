"""P7b §1: находки живого прогона P7a в оповещениях и уведомлениях.

1. Новый вид опасности у открытого сигнала оповещает оператора снова; тот же
   вид в пределах `PASSIVE_DANGER_GROUP_MINUTES` — нет.
2. Цитата оповещения — реплика, в которой найдена опасность, а не первая
   реплика окна; время — в поясе показа с пометкой «МСК».
3. Заявка из сигнала без жителя-получателя: доставка `skipped` с кодом
   `NO_RESIDENT_RECIPIENT`, а настоящий отзыв доступа остаётся
   `ACCESS_REVOKED`.

Сигналы засеваются настоящим путём P4 (вебхук → приём → окно → разбор).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from domsignal.db.models import (
    NotificationDelivery,
    OutboxMessage,
    ResidentMembership,
    RouteOutcome,
    Signal,
    SignalEvent,
    Ticket,
    User,
)
from domsignal.services.chat_voice import SIGNAL_ALERT_INTENT_KIND
from tests.integration.passive_harness import NEIGHBOURS, pv  # noqa: F401
from tests.integration.test_passive_signals import (
    ago,
    facet,
    model_signal,
    settle,
    use_model,
)
from tests.integration.test_signal_inbox import call, decide, detail, lift, new_key

GAS_2 = "Пахнет газом во втором подъезде"
GAS_AND_SMOKE = "Теперь пахнет газом и тянет дымом"
GAS_AGAIN = "Да, газом очень пахнет"
SMOKE = "и дымом тоже тянет"
TRAPPED = ("Там кто-нибудь внутри?", "Да, женщина стучит", "Двери вообще не открываются")

MSK = timedelta(hours=3)


def verdict(msg: str, role: str, ref: str) -> dict[str, Any]:
    return {"id": msg, "role": role, "signals": [ref], "link_certainty": "sure"}


def alerts(pv: Any) -> list[str]:  # noqa: F811
    return [item[2].text for item in pv.messaging.sent if item[2].text.startswith("ДомСигнал")]


def moscow(at: datetime) -> str:
    return (at.astimezone(UTC) + MSK).strftime("%d.%m.%Y %H:%M") + " МСК"


async def alert_intents(pv: Any) -> list[dict[str, Any]]:  # noqa: F811
    rows = await pv.all(
        select(OutboxMessage)
        .where(OutboxMessage.kind == SIGNAL_ALERT_INTENT_KIND)
        .order_by(OutboxMessage.created_at)
    )
    return [row.payload for row in rows]


# ------------------------------------------------------------- новый вид


async def test_a_new_danger_kind_alerts_again_and_the_same_kind_does_not(pv) -> None:  # noqa: F811
    await pv.bind()
    first_at, second_at = ago(90), ago(60)
    first = await pv.say(GAS_2, actor=NEIGHBOURS[0], at=first_at)
    await pv.deliver()
    second = await pv.say(GAS_AND_SMOKE, actor=NEIGHBOURS[0], at=second_at)
    await pv.say(GAS_AGAIN, actor=NEIGHBOURS[1], at=ago(30))
    await pv.deliver()

    signals = await pv.all(select(Signal))
    assert len(signals) == 1, "газ и дым в одной реплике присоединяются к газовому сигналу"
    assert signals[0].emergency["kinds"] == ["gas", "smoke_fire"]
    intents = await alert_intents(pv)
    assert [item["new_kinds"] for item in intents] == [[], ["smoke_fire"]]
    assert [item["evidence_mid"] for item in intents] == [first, second]
    texts = alerts(pv)
    assert len(texts) == 2, "тот же вид в окне склейки не оповещает"
    assert texts[0].startswith("ДомСигнал: возможная опасность в домовом чате.")
    assert f"Цитата: «{GAS_2}» — Житель A, {moscow(first_at)}" in texts[0]
    assert texts[1].startswith("ДомСигнал: новый признак опасности в уже открытом сигнале.")
    assert "Новый признак: дым или огонь" in texts[1]
    assert "Все признаки сигнала: запах газа, дым или огонь" in texts[1]
    assert f"Цитата: «{GAS_AND_SMOKE}» — Житель A, {moscow(second_at)}" in texts[1]
    assert not any("UTC" in text for text in texts)
    kinds = [event.kind for event in await pv.all(select(SignalEvent))]
    assert kinds.count("danger_kind_added") == 1
    assert kinds.count("operator_alert_requested") == 2
    # Памятка в чат — прежние правила: реплика, в которой есть вид с недавней
    # памяткой, памятку не повторяет, даже если в ней появился новый вид.
    assert len(pv.memos()) == 1


async def test_smoke_after_gas_is_its_own_alert_with_the_112_route(pv) -> None:  # noqa: F811
    """Шаг 2 живого прогона на стенде без модели: «и дымом тоже тянет»."""
    await pv.bind()
    await pv.say(GAS_2, actor=NEIGHBOURS[0], at=ago(90))
    smoke_at = ago(60)
    await pv.say(SMOKE, actor=NEIGHBOURS[0], at=smoke_at)
    await pv.deliver()
    smoke = await pv.scalar(
        select(Signal).where(Signal.emergency["kinds"].astext.contains("smoke_fire"))
    )
    assert smoke is not None and smoke.strength == "critical"
    outcome = await pv.scalar(select(RouteOutcome).where(RouteOutcome.id == smoke.route_outcome_id))
    assert outcome.route_type == "emergency_service"
    texts = alerts(pv)
    assert len(texts) == 2
    assert f"Цитата: «{SMOKE}» — Житель A, {moscow(smoke_at)}" in texts[1]
    assert "Признаки: дым или огонь" in texts[1]
    # Пауза памятки — на вид: у дыма памятки ещё не было.
    assert len(pv.memos()) == 2


async def test_the_model_adding_a_kind_to_an_open_signal_alerts_with_the_evidence_line(
    pv,  # noqa: F811
) -> None:
    """P7a: модель отнесла «человек не может выйти» к открытому газовому сигналу."""
    await pv.bind()
    await pv.say(GAS_2, actor=NEIGHBOURS[0], at=ago(600))
    await settle(pv)
    await pv.deliver()
    gas = await pv.scalar(select(Signal))
    assert gas.emergency["kinds"] == ["gas"]
    # m1 — контекст (реплика про газ), m2..m4 — окно, open:1 — газовый сигнал.
    use_model(
        pv,
        {
            "messages": [
                verdict("m2", "new_problem", "open:1"),
                verdict("m3", "confirmation", "open:1"),
                verdict("m4", "confirmation", "open:1"),
            ],
            "signals": [
                {
                    **model_signal(
                        subtype="gas.smell",
                        obj="газ",
                        facets={
                            "current": facet("yes", "женщина стучит", "m3"),
                            "local": facet("unclear"),
                            "observed": facet("yes", "женщина стучит", "m3"),
                        },
                        danger=[
                            {
                                "kind": "person_trapped",
                                "evidence": [{"msg": "m3", "quote": "женщина стучит"}],
                                "contextual": False,
                            }
                        ],
                    ),
                    "ref": "open:1",
                }
            ],
        },
    )
    trapped_at = ago(100)
    mids = [
        await pv.say(TRAPPED[0], actor=NEIGHBOURS[1], at=ago(110)),
        await pv.say(TRAPPED[1], actor=NEIGHBOURS[2], at=trapped_at),
        await pv.say(TRAPPED[2], actor=NEIGHBOURS[3], at=ago(90)),
    ]
    await settle(pv)
    await pv.deliver()
    stored = await pv.scalar(select(Signal).where(Signal.id == gas.id))
    assert stored.emergency["kinds"] == ["gas", "person_trapped"]
    intents = await alert_intents(pv)
    assert intents[-1]["new_kinds"] == ["person_trapped"]
    assert intents[-1]["evidence_mid"] == mids[1], "доказательство, а не первая реплика окна"
    text = alerts(pv)[-1]
    assert "Новый признак: человек не может выйти" in text
    assert f"«{TRAPPED[1]}»" in text and TRAPPED[0] not in text
    assert "Признак найден при разборе переписки." in text
    assert re.search(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2} МСК", text)
    assert not pv.memos()[1:], "смысловая опасность в чат не пишет"


async def test_a_new_signal_from_the_window_quotes_the_evidence_line(pv) -> None:  # noqa: F811
    await pv.bind()
    use_model(
        pv,
        {
            "messages": [
                verdict("m1", "new_problem", "new:1"),
                verdict("m2", "confirmation", "new:1"),
                verdict("m3", "confirmation", "new:1"),
            ],
            "signals": [
                model_signal(
                    subtype="elevator.doors",
                    obj="лифт",
                    facets={
                        "current": facet("yes", "женщина стучит", "m2"),
                        "local": facet("unclear"),
                        "observed": facet("yes", "женщина стучит", "m2"),
                    },
                    danger=[
                        {
                            "kind": "person_trapped",
                            "evidence": [{"msg": "m2", "quote": "женщина стучит"}],
                            "contextual": False,
                        }
                    ],
                )
            ],
        },
    )
    trapped_at = ago(100)
    await pv.say(TRAPPED[0], actor=NEIGHBOURS[1], at=ago(110))
    await pv.say(TRAPPED[1], actor=NEIGHBOURS[2], at=trapped_at)
    await pv.say(TRAPPED[2], actor=NEIGHBOURS[3], at=ago(90))
    await settle(pv)
    await pv.deliver()
    text = alerts(pv)[-1]
    assert text.startswith("ДомСигнал: возможная опасность в домовом чате.")
    assert f"Цитата: «{TRAPPED[1]}» — Житель B, {moscow(trapped_at)}" in text


# ------------------------------------------------- заявка из сигнала


async def _resident(pv: Any, alias: str) -> tuple[Any, dict[str, str]]:  # noqa: F811
    user_id = uuid4()
    async with pv.container.session_factory() as session, session.begin():
        session.add(
            User(
                id=user_id,
                display_name=alias,
                demo_alias=alias,
                max_user_id=str(700_000 + len(pv.headers)),
                max_identity_verified_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(ResidentMembership(user_id=user_id, house_id=pv.ids["h1"]))
    async with pv.container.session_factory() as session:
        auth = await pv.container.session_service.issue_test_session(session, alias=alias)
    headers = {"Authorization": "Bearer " + auth.access_token}
    pv.headers[alias] = headers
    return user_id, headers


async def test_ticket_from_a_signal_skips_the_staff_author_but_not_a_revoked_resident(
    pv,  # noqa: F811
) -> None:
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    created = await decide(pv, signal.id, "create-ticket", {"expected_version": view["version"]})
    assert created.status_code == 200, created.text
    ticket = await pv.scalar(select(Ticket))
    # Житель, присоединившийся сам, и житель, у которого потом отозвали доступ.
    joined = await call(
        pv,
        "POST",
        f"/api/v1/incidents/{ticket.incident_id}/join",
        who="resident",
        key=new_key(),
    )
    assert joined.status_code == 200, joined.text
    revoked_id, _ = await _resident(pv, "p7b-revoked")
    left = await call(
        pv,
        "POST",
        f"/api/v1/incidents/{ticket.incident_id}/join",
        who="p7b-revoked",
        key=new_key(),
    )
    assert left.status_code == 200, left.text
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ResidentMembership)
            .where(ResidentMembership.user_id == revoked_id)
            .values(status="revoked")
        )
    accepted = await call(
        pv,
        "POST",
        f"/api/v1/tickets/{ticket.id}/accept",
        json={"expected_version": ticket.version},
        key=new_key(),
    )
    assert accepted.status_code == 200, accepted.text
    await pv.drain("operational")
    deliveries = {
        row.recipient_user_id: row
        for row in await pv.all(
            select(NotificationDelivery).where(NotificationDelivery.purpose == "ticket_accepted")
        )
    }
    staff = deliveries[pv.ids["admin1"]]
    assert (staff.status, staff.last_error_code) == ("skipped", "NO_RESIDENT_RECIPIENT")
    revoked = deliveries[revoked_id]
    assert (revoked.status, revoked.last_error_code) == ("superseded", "ACCESS_REVOKED")
    resident = deliveries[pv.ids["resident"]]
    assert resident.last_error_code is None and resident.status in {"pending", "accepted"}


async def test_a_ticket_from_a_signal_alone_has_only_the_skipped_staff_delivery(
    pv,  # noqa: F811
) -> None:
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    assert (
        await decide(pv, signal.id, "create-ticket", {"expected_version": view["version"]})
    ).status_code == 200
    ticket = await pv.scalar(select(Ticket))
    accepted = await call(
        pv,
        "POST",
        f"/api/v1/tickets/{ticket.id}/accept",
        json={"expected_version": ticket.version},
        key=new_key(),
    )
    assert accepted.status_code == 200, accepted.text
    await pv.drain("operational")
    rows = await pv.all(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "ticket_accepted")
    )
    assert [(row.status, row.last_error_code) for row in rows] == [
        ("skipped", "NO_RESIDENT_RECIPIENT")
    ]
    assert not [item for item in pv.messaging.sent if "Заявка" in item[2].text]
