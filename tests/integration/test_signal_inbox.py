"""Очередь сигналов оператора (P5): доступ, порядок, решения, повтор, новые реплики.

Сигналы засеваются настоящим путём P4: события вебхука → приём → окно →
разбор правилами (или детерминированным FakeProvider там, где нужна сила,
которой правила не дают). Прямых INSERT сигналов здесь нет.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update

from domsignal.db.models import (
    Incident,
    Report,
    RouteOutcome,
    Signal,
    SignalEvent,
    Ticket,
)
from domsignal.services.signal_texts import RELATED_CONVERSION_REASON
from tests.integration.passive_harness import pv  # noqa: F401
from tests.integration.test_passive_signals import (
    LIFT_FIRST,
    LIFT_SECOND,
    ago,
    conversation,
    facet,
    model_signal,
    one_line_answer,
    settle,
    use_model,
)

GAS = "Пахнет газом в третьем подъезде"
STREET_LIGHT = "На улице у остановки не горит фонарь, темно"
LEAK = "Протекает потолок на пятом этаже, капает с утра"


def new_key() -> str:
    return f"p5-{uuid4().hex}"


async def call(
    pv: Any,  # noqa: F811
    method: str,
    path: str,
    *,
    who: str = "admin1",
    json: dict[str, Any] | None = None,
    key: str | None = None,
    params: Any = None,
) -> Any:
    headers = dict(pv.headers[who])
    if key is not None:
        headers["Idempotency-Key"] = key
    return await pv.client.request(method, path, json=json, headers=headers, params=params)


async def detail(pv: Any, signal_id: Any, who: str = "admin1") -> dict[str, Any]:  # noqa: F811
    response = await call(pv, "GET", f"/api/v1/signals/{signal_id}", who=who)
    assert response.status_code == 200, response.text
    return response.json()


async def decide(
    pv: Any,  # noqa: F811
    signal_id: Any,
    action: str,
    body: dict[str, Any],
    *,
    key: str | None = None,
    who: str = "admin1",
) -> Any:
    return await call(
        pv,
        "POST",
        f"/api/v1/signals/{signal_id}/{action}",
        who=who,
        json=body,
        key=key or new_key(),
    )


async def lift(pv: Any) -> Signal:  # noqa: F811
    await conversation(pv, LIFT_FIRST, start=900)
    await settle(pv)
    signal = await pv.scalar(select(Signal).where(Signal.subtype == "elevator.stopped"))
    assert signal is not None
    return signal


async def unknown_signal(pv: Any, text: str = "Безобразие, опять всё сломали") -> Signal:  # noqa: F811
    use_model(pv, one_line_answer(model_signal(subtype="invented.code", obj="что-то")))
    await pv.say(text, at=ago(300))
    await settle(pv)
    signal = await pv.scalar(select(Signal).where(Signal.subtype == "other.unspecified"))
    assert signal is not None
    return signal


# ------------------------------------------------------------ список и порядок


async def test_the_queue_shows_only_the_inbox_in_strength_order(pv) -> None:  # noqa: F811
    await pv.bind()
    pv.configure(weak_daily_limit=1)
    await pv.say("Лифт во втором подъезде не работает", at=ago(1200))
    await pv.say(STREET_LIGHT, at=ago(900))
    await settle(pv)
    use_model(
        pv,
        one_line_answer(
            model_signal(
                subtype="water.leak",
                obj="потолок",
                scope=("house_common", "на пятом этаже", "m1"),
                facets={
                    "current": facet("unclear"),
                    "local": facet("unclear"),
                    "observed": facet("yes", "Протекает потолок", "m1"),
                },
            )
        ),
    )
    await pv.say(LEAK, at=ago(600))
    await settle(pv)
    await pv.say(GAS, at=ago(30))
    audit = await pv.scalar(select(Signal).where(Signal.disposition == "audit_pool"))
    assert audit is not None and audit.audit_reason == "weak_overflow"

    response = await call(pv, "GET", "/api/v1/signals", params={"house_id": str(pv.ids["h1"])})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["strength"] for item in body["items"]] == ["critical", "medium", "weak"]
    assert str(audit.id) not in {item["id"] for item in body["items"]}
    assert body["page"]["total"] == 3
    assert body["counts"] == {"critical": 1, "strong": 0, "medium": 1, "weak": 1}
    critical = body["items"][0]
    assert body["attention"]["count"] == 1
    assert body["attention"]["latest_signal_id"] == critical["id"]
    assert critical["route_type"] == "emergency_service"
    assert critical["danger_kinds"] == ["gas"]
    assert critical["first_quote"]["text"] == GAS
    assert critical["first_quote"]["author"].startswith("Житель ")
    weak = body["items"][2]
    assert weak["place"]["entrance"]["value"] == "2" and weak["place"]["entrance"]["quote"]
    assert weak["report_count"] == 1 and weak["author_count"] == 1

    only_weak = await call(pv, "GET", "/api/v1/signals", params=[("strength", "weak")])
    assert [item["strength"] for item in only_weak.json()["items"]] == ["weak"]
    assert only_weak.json()["counts"]["critical"] == 1, "счётчики — без фильтра силы"
    two = await call(
        pv, "GET", "/api/v1/signals", params=[("strength", "critical"), ("strength", "medium")]
    )
    assert two.json()["page"]["total"] == 2
    none = await call(pv, "GET", "/api/v1/signals", params=[("status", "dismissed")])
    assert none.json()["items"] == [] and none.json()["page"]["total"] == 0
    paged = await call(pv, "GET", "/api/v1/signals", params={"limit": 1, "offset": 1})
    assert [item["strength"] for item in paged.json()["items"]] == ["medium"]
    assert paged.json()["page"] == {"limit": 1, "offset": 1, "total": 3}

    # Audit Pool оператору не отдаётся и по идентификатору.
    hidden = await call(pv, "GET", f"/api/v1/signals/{audit.id}")
    assert hidden.status_code == 404


async def test_a_foreign_house_is_masked_and_a_resident_has_no_right(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    foreign = await call(pv, "GET", f"/api/v1/signals/{signal.id}", who="admin2")
    assert foreign.status_code == 404
    assert foreign.headers["content-type"].startswith("application/problem+json")
    listed = await call(
        pv, "GET", "/api/v1/signals", who="admin2", params={"house_id": str(pv.ids["h1"])}
    )
    assert listed.status_code == 404
    everything = await call(pv, "GET", "/api/v1/signals", who="admin2")
    assert everything.status_code == 200 and everything.json()["items"] == []
    resident = await call(pv, "GET", f"/api/v1/signals/{signal.id}", who="resident")
    assert resident.status_code == 403
    resident_list = await call(
        pv, "GET", "/api/v1/signals", who="resident", params={"house_id": str(pv.ids["h1"])}
    )
    assert resident_list.status_code == 403
    body = {"expected_version": signal.version, "reason": "spam"}
    assert (await decide(pv, signal.id, "dismiss", body, who="resident")).status_code == 403
    assert (await decide(pv, signal.id, "dismiss", body, who="admin2")).status_code == 404
    missing = await call(pv, "GET", f"/api/v1/signals/{uuid4()}")
    assert missing.status_code == 404
    unchanged = await pv.scalar(select(Signal).where(Signal.id == signal.id))
    assert unchanged.status == "new"


# ------------------------------------------------------------- создать заявку


async def test_create_ticket_uses_the_quotes_and_the_employee_context(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    assert view["subtype_label"] == "Лифт" and view["category"] == "elevator"
    assert view["route_type"] == "uk_internal" and view["route_source"] == "router"
    assert view["action_card"]["audience"] == "operator"
    codes = [action["code"] for action in view["allowed_actions"]]
    assert codes[0] == "create-ticket" and "dismiss" in codes
    join = next(action for action in view["allowed_actions"] if action["code"] == "join")
    assert join["enabled"] is False and join["reason"]
    draft = view["ticket_draft"]
    assert draft["category"] == "elevator"
    assert "Подъезд: 2." in draft["description"]
    for quote in view["quotes"]:
        assert quote["text"] in draft["description"]
    assert draft["description"].startswith("Из домового чата: лифт. Сообщений: 3, жителей: 3.")
    assert await pv.scalar(select(func.count()).select_from(Report)) == 0, "автоматически нет"

    key = new_key()
    body = {"expected_version": view["version"]}
    created = await decide(pv, signal.id, "create-ticket", body, key=key)
    assert created.status_code == 200, created.text
    mutation = created.json()
    assert mutation["replayed"] is False
    result = mutation["signal"]
    assert result["status"] == "converted" and result["allowed_actions"] == []
    assert result["version"] == view["version"] + 1 == mutation["effect_version"]
    assert result["linked"]["ticket_number"].startswith("T-")
    assert result["decision"]["decided_by"] == "admin1"

    report = await pv.scalar(select(Report))
    assert report.author_id == pv.ids["admin1"]
    assert report.classification_mode == "manual" and report.category == "elevator"
    assert report.description == draft["description"]
    ticket = await pv.scalar(select(Ticket))
    assert ticket.incident_id == report.incident_id and ticket.status == "new"
    assert result["linked"]["ticket_number"] == f"T-{ticket.number}"
    incident = await pv.scalar(select(Incident))
    assert incident.location_entrance == "2"
    stored = await pv.scalar(select(Signal).where(Signal.id == signal.id))
    assert stored.report_id == report.id and stored.incident_id == incident.id
    assert stored.decided_by == pv.ids["admin1"] and stored.decided_at is not None
    outcome = await pv.scalar(
        select(RouteOutcome).where(RouteOutcome.id == stored.route_outcome_id)
    )
    assert outcome.decision == "ticket" and outcome.report_id == report.id
    assert outcome.author_id == pv.ids["admin1"]
    event = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "signal_converted"))
    assert event.actor_id == pv.ids["admin1"] and event.signal_id == signal.id

    # Повтор с тем же ключом — тот же результат, без второй заявки.
    replay = await decide(pv, signal.id, "create-ticket", body, key=key)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["effect_version"] == mutation["effect_version"]
    assert await pv.scalar(select(func.count()).select_from(Report)) == 1
    assert await pv.scalar(select(func.count()).select_from(Ticket)) == 1
    conflict = await decide(pv, signal.id, "create-ticket", {**body, "category": "water"}, key=key)
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    stale = await decide(pv, signal.id, "create-ticket", body)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    decided = await decide(
        pv, signal.id, "dismiss", {"expected_version": result["version"], "reason": "spam"}
    )
    assert decided.status_code == 409 and decided.json()["code"] == "signal_decided"
    # Заявка появилась в очереди заявок сотрудника и принимается как обычно.
    queue = await call(pv, "GET", "/api/v1/tickets", params={"house_id": str(pv.ids["h1"])})
    assert [item["id"] for item in queue.json()["items"]] == [str(ticket.id)]
    accepted = await call(
        pv,
        "POST",
        f"/api/v1/tickets/{ticket.id}/accept",
        json={"expected_version": ticket.version},
        key=new_key(),
    )
    assert accepted.status_code == 200, accepted.text


async def test_the_operator_may_correct_the_ticket_before_sending(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    created = await decide(
        pv,
        signal.id,
        "create-ticket",
        {
            "expected_version": view["version"],
            "category": "other",
            "description": "Лифт во втором подъезде стоит с утра, жители поднимаются пешком",
        },
    )
    assert created.status_code == 200, created.text
    report = await pv.scalar(select(Report))
    assert report.category == "other"
    assert report.description.startswith("Лифт во втором подъезде стоит с утра")
    short = await decide(
        pv, signal.id, "create-ticket", {"expected_version": 1, "description": "ой"}
    )
    assert short.status_code == 422


async def test_an_engine_change_makes_the_old_version_stale(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    before = (await detail(pv, signal.id))["version"]
    await conversation(pv, LIFT_SECOND, start=300, first_author=2)
    await settle(pv)
    after = await detail(pv, signal.id)
    assert after["version"] > before and after["report_count"] == 6
    stale = await decide(pv, signal.id, "dismiss", {"expected_version": before, "reason": "spam"})
    assert stale.status_code == 409 and stale.json()["code"] == "stale_version"
    fresh = await decide(
        pv, signal.id, "dismiss", {"expected_version": after["version"], "reason": "spam"}
    )
    assert fresh.status_code == 200


# ---------------------------------------------------------------- присоединить


async def test_join_adds_a_report_without_a_second_ticket(pv) -> None:  # noqa: F811
    await pv.bind()
    created = await call(
        pv,
        "POST",
        "/api/v1/reports",
        who="resident",
        json={
            "house_id": str(pv.ids["h1"]),
            "category": "elevator",
            "description": "Лифт во втором подъезде не работает с утра",
        },
        key=new_key(),
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["incident"]["id"]
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    candidates = view["join_candidates"]
    assert [item["incident_id"] for item in candidates] == [incident_id]
    join = next(action for action in view["allowed_actions"] if action["code"] == "join")
    assert join["enabled"] is True
    assert view["action_card"]["existing_ticket_ref"] == candidates[0]["title"]

    wrong = await decide(
        pv, signal.id, "join", {"expected_version": view["version"], "incident_id": str(uuid4())}
    )
    assert wrong.status_code == 422
    assert wrong.json()["field_errors"][0]["field"] == "incident_id"
    joined = await decide(
        pv, signal.id, "join", {"expected_version": view["version"], "incident_id": incident_id}
    )
    assert joined.status_code == 200, joined.text
    result = joined.json()["signal"]
    assert result["status"] == "converted" and result["linked"]["incident_id"] == incident_id
    assert await pv.scalar(select(func.count()).select_from(Ticket)) == 1, "второй Ticket не нужен"
    reports = await pv.all(select(Report).order_by(Report.created_at))
    assert len(reports) == 2 and {str(item.incident_id) for item in reports} == {incident_id}
    assert reports[1].author_id == pv.ids["admin1"]
    assert "Лифт во втором подъезде опять не работает" in reports[1].description


# ------------------------------------------------------------ внешний маршрут


async def test_route_external_keeps_a_snapshot_and_sends_nothing(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(GAS, at=ago(30))
    signal = await pv.scalar(select(Signal))
    view = await detail(pv, signal.id)
    assert view["route_type"] == "emergency_service"
    assert view["danger"]["kinds"] == ["gas"] and view["danger"]["preliminary"] is True
    assert view["danger"]["evidence"][0]["source"] == "rules"
    assert view["action_card"]["safety"]["phone"] == "112"
    assert view["action_card"]["actions"][0]["type"] == "call_phone"
    codes = [action["code"] for action in view["allowed_actions"]]
    assert codes[:3] == ["route-external", "dismiss", "create-ticket"]
    sent_before = len(pv.messaging.sent) + len(pv.messaging.chat_sent)

    routed = await decide(pv, signal.id, "route-external", {"expected_version": view["version"]})
    assert routed.status_code == 200, routed.text
    result = routed.json()["signal"]
    assert result["status"] == "routed_external"
    snapshot = result["decision"]["route"]
    assert snapshot["route_type"] == "emergency_service"
    assert snapshot["basis_source_title"] and "488-ФЗ" in snapshot["basis_source_title"]
    assert snapshot["basis_verification_status"] == "verified"
    assert snapshot["channel_label"] == "Единый номер вызова экстренных оперативных служб"
    assert snapshot["directory_version"]
    outcome = await pv.scalar(
        select(RouteOutcome).where(
            RouteOutcome.signal_id == signal.id, RouteOutcome.author_id.is_not(None)
        )
    )
    assert outcome.decision == "external" and outcome.channel_id == "emergency_112"
    assert outcome.basis["rule_id"] == "federal.gas_smell.emergency"
    assert outcome.directory_version == snapshot["directory_version"]
    assert await pv.scalar(select(func.count()).select_from(Report)) == 0
    await pv.drain("operational")
    assert len(pv.messaging.sent) + len(pv.messaging.chat_sent) >= sent_before
    assert not [item for item in pv.messaging.sent if "внешн" in item[2].text.lower()], (
        "продукт никуда не отправляет внешний маршрут"
    )


async def test_route_external_is_refused_for_the_uk_route(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    assert "route-external" not in [action["code"] for action in view["allowed_actions"]]
    refused = await decide(pv, signal.id, "route-external", {"expected_version": view["version"]})
    assert refused.status_code == 409 and refused.json()["code"] == "signal_action_unavailable"


# --------------------------------------------------------------- выбор маршрута


async def test_choose_route_only_for_unknown_and_only_allowed_types(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await unknown_signal(pv)
    view = await detail(pv, signal.id)
    assert view["route_type"] == "unknown"
    assert "unknown" not in view["route_choices"] and "municipality" in view["route_choices"]
    codes = {action["code"]: action for action in view["allowed_actions"]}
    assert codes["choose-route"]["enabled"] is True
    assert codes["route-external"]["enabled"] is False and codes["route-external"]["reason"]

    invalid = await decide(
        pv,
        signal.id,
        "choose-route",
        {"expected_version": view["version"], "route_type": "unknown"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["field_errors"][0]["field"] == "route_type"
    bogus = await decide(
        pv, signal.id, "choose-route", {"expected_version": view["version"], "route_type": "police"}
    )
    assert bogus.status_code == 422
    free_text = await decide(
        pv,
        signal.id,
        "choose-route",
        {"expected_version": view["version"], "route_type": "municipality", "organization": "X"},
    )
    assert free_text.status_code == 422, "свободного текста организации нет"

    chosen = await decide(
        pv,
        signal.id,
        "choose-route",
        {"expected_version": view["version"], "route_type": "municipality"},
    )
    assert chosen.status_code == 200, chosen.text
    result = chosen.json()["signal"]
    assert result["status"] == "in_review" and result["route_type"] == "municipality"
    assert result["route_source"] == "operator" and result["route_chosen_by"] == "admin1"
    assert result["action_card"]["route"]["organization_name"] is None
    outcome = await pv.scalar(
        select(RouteOutcome).where(
            RouteOutcome.id
            == (await pv.scalar(select(Signal.route_outcome_id).where(Signal.id == signal.id)))
        )
    )
    assert outcome.author_id == pv.ids["admin1"] and outcome.decision == "external"
    assert outcome.route_type == "municipality" and outcome.organization_id is None
    routed = await decide(pv, signal.id, "route-external", {"expected_version": result["version"]})
    assert routed.status_code == 200 and routed.json()["signal"]["status"] == "routed_external"


async def test_choose_route_is_refused_when_the_directory_decided(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    assert view["route_choices"] == []
    refused = await decide(
        pv,
        signal.id,
        "choose-route",
        {"expected_version": view["version"], "route_type": "municipality"},
    )
    assert refused.status_code == 409


# --------------------------------------------------------------------- закрыть


async def test_dismiss_requires_a_reason_and_records_it(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    missing = await decide(pv, signal.id, "dismiss", {"expected_version": view["version"]})
    assert missing.status_code == 422
    long_note = await decide(
        pv,
        signal.id,
        "dismiss",
        {"expected_version": view["version"], "reason": "duplicate", "note": "x" * 501},
    )
    assert long_note.status_code == 422
    closed = await decide(
        pv,
        signal.id,
        "dismiss",
        {"expected_version": view["version"], "reason": "duplicate", "note": "Уже в заявке T-5"},
    )
    assert closed.status_code == 200, closed.text
    decision = closed.json()["signal"]["decision"]
    assert decision["reason"] == "duplicate" and decision["reason_label"] == "Дубликат"
    assert decision["note"] == "Уже в заявке T-5" and decision["decided_by"] == "admin1"
    stored = await pv.scalar(select(Signal).where(Signal.id == signal.id))
    assert stored.status == "dismissed" and stored.decision_reason == "duplicate"
    event = await pv.scalar(select(SignalEvent).where(SignalEvent.kind == "signal_dismissed"))
    assert event.actor_id == pv.ids["admin1"] and event.details == "duplicate"
    labels = [item["label"] for item in closed.json()["signal"]["events"]]
    assert "Оператор закрыл сигнал" in labels
    assert all("versions" not in item for item in closed.json()["signal"]["events"])


# ---------------------------------------------------- новые реплики после решения


async def test_new_lines_after_dismiss_or_external_start_a_new_signal(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    await decide(pv, signal.id, "dismiss", {"expected_version": view["version"], "reason": "spam"})
    await conversation(pv, LIFT_SECOND, start=300, first_author=2)
    await settle(pv)
    lifts = await pv.all(
        select(Signal).where(Signal.subtype == "elevator.stopped").order_by(Signal.created_at)
    )
    assert [item.status for item in lifts] == ["dismissed", "new"]
    assert lifts[0].report_count == 3, "решённый сигнал не наращивает ветку"

    await pv.say(STREET_LIGHT, at=ago(240))
    await settle(pv)
    light = await pv.scalar(select(Signal).where(Signal.subtype == "street_lighting.failure"))
    light_view = await detail(pv, light.id)
    assert light_view["route_type"] == "municipality"
    await decide(pv, light.id, "route-external", {"expected_version": light_view["version"]})
    await pv.say("Фонарь у остановки так и не горит", at=ago(120))
    await settle(pv)
    lights = await pv.all(
        select(Signal)
        .where(Signal.subtype == "street_lighting.failure")
        .order_by(Signal.created_at)
    )
    assert [item.status for item in lights] == ["routed_external", "new"]


async def test_new_lines_after_conversion_offer_the_linked_problem_first(pv) -> None:  # noqa: F811
    await pv.bind()
    signal = await lift(pv)
    view = await detail(pv, signal.id)
    converted = await decide(pv, signal.id, "create-ticket", {"expected_version": view["version"]})
    incident_id = converted.json()["signal"]["linked"]["incident_id"]
    await conversation(pv, LIFT_SECOND, start=300, first_author=2)
    await settle(pv)
    fresh = await pv.scalar(
        select(Signal).where(Signal.subtype == "elevator.stopped", Signal.status == "new")
    )
    assert fresh is not None and fresh.id != signal.id
    fresh_view = await detail(pv, fresh.id)
    first = fresh_view["join_candidates"][0]
    assert first["incident_id"] == incident_id
    assert first["match_reason"] == RELATED_CONVERSION_REASON
    joined = await decide(
        pv,
        fresh.id,
        "join",
        {"expected_version": fresh_view["version"], "incident_id": incident_id},
    )
    assert joined.status_code == 200
    assert await pv.scalar(select(func.count()).select_from(Ticket)) == 1


# ------------------------------------------------------ оповещение со ссылкой


async def test_the_operator_alert_links_to_the_signal_in_the_cabinet(pv) -> None:  # noqa: F811
    await pv.bind()
    await pv.say(GAS, at=ago(30))
    signal = await pv.scalar(select(Signal))
    await pv.deliver()
    alerts = [item for item in pv.messaging.sent if "возможная опасность" in item[2].text]
    assert alerts, "оповещение оператора отправлено"
    text = alerts[0][2].text
    link = f"http://localhost:8000/admin/?section=signals&signal={signal.id}"
    assert text.splitlines()[-1] == f"Сигнал в кабинете: {link}"
    assert alerts[0][2].buttons == (), "ссылка — строкой текста, без кнопки"


# ------------------------------------------------------ выключатель в кабинете


async def test_the_cabinet_switch_toggles_chat_reading_with_chat_connect(pv) -> None:  # noqa: F811
    binding = await pv.bind(enable=False)
    path = f"/api/v1/chat-bindings/{binding}/passive-capture"
    foreign = await call(pv, "POST", path, who="admin2", json={"enabled": True})
    assert foreign.status_code in {403, 404}
    resident = await call(pv, "POST", path, who="resident", json={"enabled": True})
    assert resident.status_code in {403, 404}
    enabled = await call(pv, "POST", path, json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["passive_capture_enabled"] is True
    assert enabled.json()["notice_queued"] is True
    again = await call(pv, "POST", path, json={"enabled": True})
    assert again.json()["notice_queued"] is False, "сообщение о чтении — один раз на версию"
    houses = await call(pv, "GET", f"/api/v1/companies/{pv.ids['t1']}/houses")
    assert houses.status_code == 200, houses.text
    summary = houses.json()[0]["bindings"][0]
    assert summary["passive_capture_enabled"] is True
    disabled = await call(pv, "POST", path, json={"enabled": False})
    assert disabled.json()["passive_capture_enabled"] is False
    await pv.say("Лифт во втором подъезде не работает", at=ago(60))
    assert await pv.scalar(select(func.count()).select_from(Signal)) == 0
    capabilities = await pv.client.get("/api/v1/capabilities")
    assert capabilities.json()["features"]["passive_capture"] is True


async def test_a_place_quoted_only_from_context_is_not_shown_or_sent(pv) -> None:  # noqa: F811
    """Модель может взять подъезд из реплики контекста (прошлого разговора):
    цитата есть, но строки окна у неё нет. Оператору и в заявку это не идёт."""
    await pv.bind()
    signal = await lift(pv)
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(Signal)
            .where(Signal.id == signal.id)
            .values(entrance={"value": "3", "quote": "в третьем подъезде", "line_mid": None})
        )
    view = await detail(pv, signal.id)
    assert view["place"].get("entrance") is None
    assert "Подъезд" not in view["ticket_draft"]["description"]
    created = await decide(pv, signal.id, "create-ticket", {"expected_version": view["version"]})
    assert created.status_code == 200
    incident = await pv.scalar(select(Incident))
    assert incident.location_entrance is None
