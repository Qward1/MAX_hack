"""D2: дашборды платформы и УК — агрегаты событий БД, изоляция УК, без текстов."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import update

from domsignal.db.models import ConversationWindow, Incident, Ticket, TicketEvent
from domsignal.services.dashboards import DashboardService
from domsignal.tools.seed_tickets import seed_id
from tests.integration.passive_harness import CHAT_1, pv  # noqa: F401 - стенд пассивного чтения
from tests.integration.test_administration import env  # noqa: F401 - стенд кабинета
from tests.integration.test_passive_signals import LIFT_FIRST, conversation, settle


async def test_dashboards_count_real_windows_and_signals_per_company(pv):  # noqa: F811
    await pv.bind(chat=CHAT_1, house="h1", admin="admin1")
    await conversation(pv, LIFT_FIRST, start=600)
    await settle(pv)
    mine = await pv.client.get(
        f"/api/v1/companies/{pv.ids['t1']}/dashboard?days=7", headers=pv.headers["admin1"]
    )
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["scope"] == "company" and body["timezone"] == "Europe/Moscow"
    assert [h["address"] for h in body["houses"]] == ["Казань, Синтетическая улица, 1"]
    assert body["houses"][0]["signals"] == 1
    assert len(body["activity"]) == 7 and sum(d["signals"] for d in body["activity"]) == 1
    assert body["quota"] == {
        "limit": None,
        "used": 1,
        "remaining": None,
        "over_limit": False,
        "exhausted": False,
    }
    # Другая УК: свой дом без сигналов, чужой обзор — 404.
    other = await pv.client.get(
        f"/api/v1/companies/{pv.ids['t2']}/dashboard", headers=pv.headers["admin2"]
    )
    assert [h["signals"] for h in other.json()["houses"]] == [0]
    foreign = await pv.client.get(
        f"/api/v1/companies/{pv.ids['t1']}/dashboard", headers=pv.headers["admin2"]
    )
    assert foreign.status_code == 404
    # Модель вызывалась в окнах этого дома (учёт разбора, без текста).
    async with pv.container.session_factory() as session, session.begin():
        await session.execute(
            update(ConversationWindow).values(
                analysis={"provider_called": True, "cost_rub": 0.05, "state": "ok"}
            )
        )
    async with pv.container.session_factory() as session:
        platform = await DashboardService(300).platform(session, 14)
    assert len(platform.activity) == 14
    today = platform.activity[-1]
    assert today.windows >= 1 and today.lines >= len(LIFT_FIRST) - 1
    assert today.signals_weak == 1
    assert platform.totals.chats_active == 1 and platform.totals.chats_total == 1
    row = next(c for c in platform.companies if c.company_id == pv.ids["t1"])
    assert row.chats_active == 1 and row.houses == 1 and row.quota.used == 1
    assert platform.model.calls == today.windows and platform.model.daily_budget == 300
    assert platform.model.cost_rub == round(0.05 * today.windows, 4)
    assert [c.company_id for c in platform.model.by_company] == [pv.ids["t1"]]
    dumped = json.dumps(platform.model_dump(mode="json"), ensure_ascii=False) + mine.text
    assert not any(line in dumped for line in LIFT_FIRST)
    assert "лифт" not in dumped.casefold()


async def add_ticket(db, *, created: datetime, category: str, accepted_after=None, outcome=None):
    actor = seed_id("admin")
    incident = Incident(
        management_id=seed_id("management-a1"),
        house_id=seed_id("a1"),
        category=category,
        title="Синтетическая проблема",
        description="ЧАСТНЫЙ ТЕКСТ ЖИТЕЛЯ",
        status="open",
        created_at=created,
    )
    db.add(incident)
    await db.flush()
    ticket = Ticket(
        incident_id=incident.id,
        management_id=seed_id("management-a1"),
        house_id=seed_id("a1"),
        status="new",
        routing_reason="synthetic",
        source="operator",
        created_by=actor,
        created_at=created,
        updated_at=created,
    )
    db.add(ticket)
    await db.flush()
    version = 1
    events = [("created", None, "new", created)]
    if accepted_after is not None:
        events.append(("accepted", "new", "accepted", created + accepted_after))
    if outcome == "confirmed":
        events.append(
            ("result_confirmed", "verification_pending", "closed", created + timedelta(hours=1))
        )
    if outcome == "returned":
        events.append(
            ("result_objected", "verification_pending", "in_progress", created + timedelta(hours=1))
        )
    for kind, before, after, at in events:
        db.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=actor,
                kind=kind,
                version=version,
                from_status=before,
                to_status=after,
                created_at=at,
            )
        )
        version += 1
    if outcome == "confirmed":
        ticket.status = "closed"
    return ticket


async def test_company_overview_tickets_median_verification_and_scope(env):  # noqa: F811
    now = datetime.now(UTC)
    async with env["container"].session_factory() as db, db.begin():
        await add_ticket(
            db,
            created=now - timedelta(hours=3),
            category="water",
            accepted_after=timedelta(minutes=30),
            outcome="confirmed",
        )
        await add_ticket(
            db,
            created=now - timedelta(hours=2),
            category="water",
            accepted_after=timedelta(minutes=10),
            outcome="returned",
        )
        await add_ticket(db, created=now - timedelta(hours=1), category="elevator")
        # Заявка вне периода не попадает в обзор недели.
        await add_ticket(db, created=now - timedelta(days=20), category="other")
    base = f"/api/v1/companies/{seed_id('alpha')}/dashboard"
    week = (await env["admin"].get(base + "?days=7")).json()
    a1 = next(h for h in week["houses"] if h["house_id"] == str(seed_id("a1")))
    assert a1["tickets_created"] == 3 and a1["tickets_closed"] == 1
    assert a1["tickets_open"] == 3  # три открыты сейчас, включая старую
    assert a1["median_accept_minutes"] == 20.0
    assert (a1["verification_confirmed"], a1["verification_returned"]) == (1, 1)
    assert a1["top_categories"] == [
        {"category": "water", "count": 2},
        {"category": "elevator", "count": 1},
    ]
    month = (await env["admin"].get(base + "?days=30")).json()
    assert len(month["activity"]) == 30
    assert (
        next(h for h in month["houses"] if h["house_id"] == str(seed_id("a1")))["tickets_created"]
        == 4
    )
    assert (await env["admin"].get(base + "?days=10")).status_code == 422
    # Ответственный видит только свой дом, оператор без назначений — ни одного.
    responsible = await env["client"](seed_id("responsible"))
    scoped = (await responsible.get(base)).json()
    assert scoped["scope"] == "assigned"
    assert [h["house_id"] for h in scoped["houses"]] == [str(seed_id("a1"))]
    assert (await env["operator"].get(base)).json()["houses"] == []
    assert (await env["foreign"].get(base)).status_code == 404
    assert (await env["public"].get(base)).status_code == 401
    csv = await env["admin"].get(base + ".csv?days=7")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"]
    text = csv.content.decode("utf-8")
    assert text.startswith("﻿Адрес;")
    assert "A16 synthetic house a1;0;3;3;1;20.0;1;1;Вода (2), Лифт (1)" in text
    assert "ЧАСТНЫЙ ТЕКСТ ЖИТЕЛЯ" not in text + json.dumps(week, ensure_ascii=False)
    assert (await env["foreign"].get(base + ".csv")).status_code == 404


async def test_platform_dashboard_funnel_and_permissions(env):  # noqa: F811
    from tests.integration.test_administration import application
    from tests.integration.test_d2_company_signup import decide

    obj = await application(env)
    await decide(env, obj, "approve", {"chat_quota": 2})
    await application(
        env,
        {
            "legal_name": "ООО Вторая",
            "short_name": "Вторая",
            "inn": "7700000022",
            "contact_name": "Контакт",
            "contact_phone": "+7 900 000-00-00",
            "requested_chat_count": 1,
        },
    )
    response = await env["platform"].get("/api/v1/platform/dashboard?days=7")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["funnel"] == {"applications": 2, "approved": 1, "first_chat": 0, "first_ticket": 0}
    assert body["totals"]["applications_pending"] == 1
    approved = next(c for c in body["companies"] if c["name"] == "Тестовая УК")
    assert approved["quota"]["limit"] == 2 and approved["chats_active"] == 0
    assert body["delivery"] == {"accepted": 0, "failed": 0, "unknown": 0, "in_flight": 0}
    for client in ("admin", "operator"):
        assert (await env[client].get("/api/v1/platform/dashboard")).status_code == 403
    assert (await env["public"].get("/api/v1/platform/dashboard")).status_code == 401
    assert str(uuid4()) not in response.text
