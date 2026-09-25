"""D3 §1, §2, §7–§9: «Мой дом», выполненные работы, «Мои обращения»,
сопровождение A-09, ежедневная сводка и запись на приём.

Время сопровождения и сводки задаётся явно (`now`), сутки в тестах не
ждутся. Данные синтетические.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from domsignal.db.models import AppealDraft, NotificationDelivery, Ticket
from domsignal.services import community_texts
from tests.integration.d3_harness import (  # noqa: F401 - фикстура стенда
    call,
    chat,
    d3,
    deliveries,
    key,
    labels,
    payloads,
    settle,
)
from tests.integration.passive_harness import ADMIN_1, RESIDENT, ms

PROFILE = {
    "phone": "+7 843 000-00-01",
    "email": "uk@example.invalid",
    "dispatcher_phone": "+7 843 000-00-02",
    "office_hours": "Пн–Пт 9:00–18:00",
    "reception_hours": "Вт 14:00–17:00",
    "website": "https://uk.example.invalid",
    "office_address": "Казань, Синтетическая улица, 10",
}


# ------------------------------------------------------------------ «Мой дом»


async def test_my_house_shows_company_data_and_only_verified_directory_facts(d3) -> None:  # noqa: F811
    await chat(d3)
    saved = await call(d3, "POST", f"/api/v1/companies/{d3.ids['t1']}/profile", json=PROFILE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["updated_at"] and saved.json()["can_edit"] is True
    facts = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/houses/{d3.ids['h1']}/facts",
        json={"entrance_count": 4, "floor_count": 9},
    )
    assert facts.status_code == 200, facts.text

    overview = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/overview", who="resident")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["address"] == "Казань, Синтетическая улица, 1"
    assert (body["entrance_count"], body["floor_count"]) == (4, 9) and body["facts_updated_at"]
    assert body["company"]["name"] == "УК Первая (тест)"
    assert body["company"]["dispatcher_phone"] == "+7 843 000-00-02"
    assert body["company"]["updated_at"]
    assert body["chat"] == {"connected": True, "reading_enabled": True}
    phones = [item["phone"] for item in body["emergency"]]
    assert "112" in phones
    emergency = next(item for item in body["emergency"] if item["phone"] == "112")
    assert emergency["source"]["verified_at"] and emergency["source"]["title"]
    channel_ids = [item["id"] for item in body["channels"]]
    assert "pos_gosuslugi" in channel_ids
    assert "gosuslugi_dom" not in channel_ids and "gas_emergency_104" not in phones
    assert all(item["verification_status"] == "verified" for item in body["channels"])
    steps = [item["basis"] for item in body["accident_steps"]]
    assert steps[:2] == ["directory", "company"]
    for forbidden in ("тариф", "норматив", "капремонт"):
        assert forbidden not in overview.text.lower()


async def test_my_house_is_for_residents_of_the_house(d3) -> None:  # noqa: F811
    staff = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/overview")
    assert staff.status_code == 403
    stranger = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/overview", who="admin2")
    assert stranger.status_code == 404
    foreign_profile = await call(
        d3, "POST", f"/api/v1/companies/{d3.ids['t1']}/profile", who="admin2", json=PROFILE
    )
    assert foreign_profile.status_code == 404
    wrong = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/profile",
        json={**PROFILE, "website": "javascript:alert(1)"},
    )
    assert wrong.status_code == 422


# ------------------------------------------------------------- работы и заявки


async def resident_ticket(h: Any, description: str = "Не работает лифт в подъезде") -> Ticket:
    created = await call(
        h,
        "POST",
        "/api/v1/reports",
        who="resident",
        json={"house_id": str(h.ids["h1"]), "category": "elevator", "description": description},
        idempotency=key(),
    )
    assert created.status_code == 201, created.text
    return await h.scalar(  # type: ignore[no-any-return]
        select(Ticket).where(Ticket.incident_id == created.json()["incident"]["id"])
    )


async def work(h: Any, current: Ticket, text: str) -> str:
    for action, body in (
        ("accept", {}),
        ("start", {}),
        ("work-attempts", {"public_description": text}),
    ):
        fresh = await h.scalar(select(Ticket).where(Ticket.id == current.id))
        response = await call(
            h,
            "POST",
            f"/api/v1/tickets/{current.id}/{action}",
            json={"expected_version": fresh.version, **body},
            idempotency=key(),
        )
        assert response.status_code == 200, response.text
    return str(response.json()["attempt_id"])


async def observe(h: Any, attempt: str, outcome: str) -> None:
    response = await call(
        h,
        "POST",
        f"/api/v1/work-attempts/{attempt}/observations",
        who="resident",
        json={"outcome": outcome},
        idempotency=key(),
    )
    assert response.status_code == 200, response.text


async def test_completed_works_show_the_public_report_and_the_resident_verdict(d3) -> None:  # noqa: F811
    first = await resident_ticket(d3)
    await observe(d3, await work(d3, first, "Заменён блок управления лифтом"), "resolved")
    second = await resident_ticket(d3, "Не горит свет на площадке")
    await observe(d3, await work(d3, second, "Заменена лампа на площадке"), "unresolved")

    works = await call(
        d3,
        "GET",
        f"/api/v1/houses/{d3.ids['h1']}/completed-works",
        who="resident",
        params={"days": 90},
    )
    assert works.status_code == 200, works.text
    items = works.json()["items"]
    assert {item["outcome"] for item in items} == {"confirmed", "returned"}
    confirmed = next(item for item in items if item["outcome"] == "confirmed")
    assert confirmed["public_description"] == "Заменён блок управления лифтом"
    assert confirmed["category_title"] == "Проблема с лифтом" and confirmed["outcome_at"]
    for private in ("admin1", str(d3.ids["admin1"]), "performer", "comment"):
        assert private not in works.text
    wrong = await call(
        d3,
        "GET",
        f"/api/v1/houses/{d3.ids['h1']}/completed-works",
        who="resident",
        params={"days": 45},
    )
    assert wrong.status_code == 422
    staff = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/completed-works")
    assert staff.status_code == 403


async def test_my_activity_lists_reports_route_cards_drafts_and_joined(d3) -> None:  # noqa: F811
    await resident_ticket(d3)
    submitted = await call(
        d3,
        "POST",
        f"/api/v1/houses/{d3.ids['h1']}/reports/submit",
        who="resident",
        json={"description": "На улице у остановки не горят фонари, темно"},
        idempotency=key(),
    )
    assert submitted.status_code == 201, submitted.text
    outcome_id = submitted.json()["route_outcome_id"]
    draft = await call(
        d3,
        "POST",
        "/api/v1/appeal-drafts",
        who="resident",
        json={"house_id": str(d3.ids["h1"]), "route_outcome_id": outcome_id},
    )
    assert draft.status_code == 201, draft.text
    filed = await call(
        d3,
        "POST",
        f"/api/v1/appeal-drafts/{draft.json()['id']}/mark-filed",
        who="resident",
        json={"reference": None},
    )
    assert filed.status_code == 200, filed.text

    activity = await call(d3, "GET", "/api/v1/me/activity", who="resident", params={"limit": 10})
    assert activity.status_code == 200, activity.text
    items = activity.json()["items"]
    kinds = [item["kind"] for item in items]
    assert {"report", "route_card", "appeal_draft"} <= set(kinds)
    report = next(item for item in items if item["kind"] == "report")
    assert report["ticket_number"].startswith("T-")
    assert report["status_label"] == "Заявка у УК: ждёт принятия в работу"
    appeal = next(item for item in items if item["kind"] == "appeal_draft")
    assert appeal["status_label"] == "Вы отметили: «Я отправил»" and appeal["filed_at"]
    page = await call(
        d3, "GET", "/api/v1/me/activity", who="resident", params={"limit": 1, "offset": 1}
    )
    assert page.json()["page"]["total"] == len(items) and len(page.json()["items"]) == 1
    for phrase in ("заявка отправлена", "обращение зарегистрировано", "передано в"):
        assert phrase not in activity.text.lower()


# -------------------------------------------------------- сопровождение (A-09)


async def filed_draft(h: Any) -> AppealDraft:
    submitted = await call(
        h,
        "POST",
        f"/api/v1/houses/{h.ids['h1']}/reports/submit",
        who="resident",
        json={"description": "На улице у остановки не горят фонари, темно"},
        idempotency=key(),
    )
    draft = await call(
        h,
        "POST",
        "/api/v1/appeal-drafts",
        who="resident",
        json={
            "house_id": str(h.ids["h1"]),
            "route_outcome_id": submitted.json()["route_outcome_id"],
        },
    )
    await call(
        h,
        "POST",
        f"/api/v1/appeal-drafts/{draft.json()['id']}/mark-filed",
        who="resident",
        json={"reference": None},
    )
    return await h.scalar(select(AppealDraft).where(AppealDraft.id == draft.json()["id"]))  # type: ignore[no-any-return]


async def press_dm(h: Any, payload: str, *, actor: int = RESIDENT) -> None:
    h.counter += 1
    await h.webhook(
        {
            "update_type": "message_callback",
            "timestamp": ms(datetime.now(UTC)),
            "callback": {
                "timestamp": ms(datetime.now(UTC)),
                "callback_id": f"cb-fu-{h.counter}",
                "payload": payload,
                "user": {"user_id": actor},
            },
            "message": {
                "recipient": {"chat_id": 9000 + actor, "chat_type": "dialog"},
                "body": {"mid": f"mid.fu-{h.counter}"},
            },
        }
    )
    await settle(h)


async def test_followup_asks_after_fourteen_days_once_and_offers_a_next_step(d3) -> None:  # noqa: F811
    draft = await filed_draft(d3)
    assert draft.followup_due_at == draft.filed_at + timedelta(days=14)
    service = d3.container.followups
    assert await service.enqueue_due(now=draft.filed_at + timedelta(days=13)) == 0
    assert await service.enqueue_due(now=draft.filed_at + timedelta(days=15)) == 1
    assert await service.enqueue_due(now=draft.filed_at + timedelta(days=16)) == 0
    await settle(d3)
    [(_, _, question)] = [
        item
        for item in d3.messaging.sent
        if item[0] == str(RESIDENT) and "Пришёл ли ответ?" in item[2].text
    ]
    assert labels(question) == [
        community_texts.FOLLOWUP_RESOLVED_LABEL,
        community_texts.FOLLOWUP_ANSWERED_LABEL,
        community_texts.FOLLOWUP_NONE_LABEL,
    ]
    for word in ("30 дней", "срок", "обязан"):
        assert word not in question.text
    await press_dm(d3, payloads(question)[2])
    answer = d3.messaging.answered[-1][1]
    assert answer.text.startswith(community_texts.FOLLOWUP_NEXT_LEAD) or answer.text.startswith(
        "Других проверенных каналов"
    )
    stored = await d3.scalar(select(AppealDraft).where(AppealDraft.id == draft.id))
    assert stored.followup_answer == "no_answer" and stored.followup_answered_at
    await press_dm(d3, payloads(question)[0])
    assert d3.messaging.answered[-1][1].text == community_texts.FOLLOWUP_ALREADY


async def test_followup_is_not_sent_after_an_answer(d3) -> None:  # noqa: F811
    draft = await filed_draft(d3)
    async with d3.container.session_factory() as session, session.begin():
        row = await session.get(AppealDraft, draft.id)
        row.followup_answer = "resolved"
        row.followup_answered_at = datetime.now(UTC)
    assert await d3.container.followups.enqueue_due(now=draft.filed_at + timedelta(days=15)) == 0


# ------------------------------------------------------------ ежедневная сводка


async def test_the_daily_digest_goes_to_those_who_enabled_it_and_skips_empty_days(d3) -> None:  # noqa: F811
    await resident_ticket(d3)
    digest = d3.container.digest
    assert await digest.run(now=datetime.now(UTC)) == 0, "сводка выключена по умолчанию"
    enabled = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/me/settings",
        json={"daily_digest_enabled": True},
    )
    assert enabled.status_code == 200 and enabled.json() == {
        "daily_digest_enabled": True,
        "max_linked": True,
    }
    await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t2']}/me/settings",
        who="admin2",
        json={"daily_digest_enabled": True},
    )
    assert await digest.run(now=datetime.now(UTC)) == 1, "у второй УК пустой день"
    assert await digest.run(now=datetime.now(UTC)) == 0, "повтор в тот же день не дублирует"
    await settle(d3)
    [(_, _, message)] = [item for item in d3.messaging.sent if item[0] == str(ADMIN_1)]
    assert message.text.startswith("ДомСигнал — сводка на")
    assert "Заявки без исполнителя: 1" in message.text
    assert "Кабинет: http" in message.text


# --------------------------------------------------------------- запись на приём


async def test_reception_slots_booking_capacity_and_reminder(d3) -> None:  # noqa: F811
    starts = datetime.now(UTC) + timedelta(hours=20)
    slot = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/reception-slots",
        json={"starts_at": starts.isoformat(), "capacity": 1, "place": "Кабинет 3"},
    )
    assert slot.status_code == 201, slot.text
    overview = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/reception", who="resident")
    assert overview.status_code == 200, overview.text
    [free] = overview.json()["slots"]
    assert free["free"] == 1 and free["place"] == "Кабинет 3"
    booked = await call(
        d3,
        "POST",
        f"/api/v1/houses/{d3.ids['h1']}/reception/bookings",
        who="resident",
        json={"slot_id": free["id"], "topic": "Перерасчёт за отопление"},
    )
    assert booked.status_code == 200, booked.text
    assert booked.json()["slots"][0]["free"] == 0
    [mine] = booked.json()["bookings"]
    assert mine["status"] == "booked" and mine["topic"] == "Перерасчёт за отопление"
    staff = await call(d3, "GET", f"/api/v1/companies/{d3.ids['t1']}/reception-slots")
    [row] = staff.json()
    assert row["booked"] == 1 and row["bookings"][0]["resident_name"] == "resident"
    stranger = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/reception", who="admin2")
    assert stranger.status_code == 404

    assert await d3.container.reception.enqueue_reminders(now=datetime.now(UTC)) == 1
    assert await d3.container.reception.enqueue_reminders(now=datetime.now(UTC)) == 0
    await settle(d3)
    [(_, _, reminder)] = [
        item
        for item in d3.messaging.sent
        if item[0] == str(RESIDENT) and item[2].text.startswith("Напоминание")
    ]
    assert "Кабинет 3" in reminder.text and "Перерасчёт за отопление" in reminder.text

    cancelled = await call(
        d3,
        "POST",
        f"/api/v1/houses/{d3.ids['h1']}/reception/bookings/{mine['id']}/cancel",
        who="resident",
    )
    assert cancelled.json()["bookings"][0]["status"] == "cancelled"
    assert cancelled.json()["slots"][0]["free"] == 1
    reminders = await deliveries(d3, purpose="reception_reminder")
    assert len(reminders) == 1 and isinstance(reminders[0], NotificationDelivery)
