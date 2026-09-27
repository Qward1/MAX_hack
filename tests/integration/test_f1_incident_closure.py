"""F1 / D6 B-04: проблема закрывается вместе с заявкой (INCIDENT-CLOSE-WITH-TICKET-2026-09-28).

Настоящая PostgreSQL и HTTP-приложение. Заявка закрыта подтверждением
жителя — проблема «Решена»; отменена с причиной — закрыта с ней; «Проблема
осталась» к закрытой заявке — та же заявка в работе и проблема снова
открыта. Доска считает только открытые, дубли предлагаются только среди
открытых. B-06: при опасности дубли не предлагаются, «Другое» — не совпадение.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select

from domsignal.db.models import Incident, IncidentEvent
from tests.integration.test_chat_bindings import cb  # noqa: F401
from tests.integration.test_tenant_access import dataset  # noqa: F401
from tests.integration.test_tickets import (
    attempt,
    command,
    observe,
    read,
    tickets,  # noqa: F401
)


async def incident_row(d: dict) -> Incident:
    async with d["container"].session_factory() as session:
        row = await session.get(Incident, UUID(d["incident"]))
        assert row is not None
        return row


async def events(d: dict) -> list[str]:
    async with d["container"].session_factory() as session:
        return list(
            await session.scalars(
                select(IncidentEvent.kind)
                .where(IncidentEvent.incident_id == UUID(d["incident"]))
                .order_by(IncidentEvent.created_at)
            )
        )


async def board(d: dict, state: str = "all", user: str = "carol") -> dict:
    response = await d["client"].get(
        f"/api/v1/houses/{d['ids']['a1']}/incidents?state={state}", headers=d["headers"][user]
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_confirmed_ticket_resolves_the_incident(tickets: dict) -> None:  # noqa: F811
    d = tickets
    before = await board(d, "open")
    assert d["incident"] in {item["id"] for item in before["items"]}
    attempt_id = await attempt(d)
    response = await observe(d, attempt_id, "carol", "resolved")
    assert response.status_code == 200, response.text
    assert (await read(d)).json()["status"] == "closed"
    row = await incident_row(d)
    assert (row.status, row.closure) == ("resolved", "residents_confirmed")
    assert row.resolved_at is not None and row.status_changed_at is not None
    assert await events(d) == ["resolved"]
    detail = await d["client"].get(
        f"/api/v1/incidents/{d['incident']}", headers=d["headers"]["eve"]
    )
    body = detail.json()
    assert body["status"] == "resolved" and body["closure"] == "residents_confirmed"
    assert body["resolved_at"] is not None
    opened = await board(d, "open")
    assert d["incident"] not in {item["id"] for item in opened["items"]}
    assert opened["open_total"] == before["open_total"] - 1
    recent = await board(d, "resolved_recent")
    assert [item["id"] for item in recent["items"]] == [d["incident"]]
    assert recent["resolved_recent_total"] == 1
    # «Решена» к тому же не открывается для присоединения.
    join = await d["client"].post(
        f"/api/v1/incidents/{d['incident']}/join",
        headers={**d["headers"]["eve"], "Idempotency-Key": "join-closed-f1"},
    )
    assert join.status_code == 409, join.text


async def test_objection_after_close_reopens_the_same_ticket_and_incident(
    tickets: dict,  # noqa: F811
) -> None:
    d = tickets
    attempt_id = await attempt(d)
    assert (await observe(d, attempt_id, "carol", "resolved")).status_code == 200
    late = await observe(d, attempt_id, "eve", "unresolved", comment="Снова течёт")
    assert late.status_code == 200, late.text
    ticket = (await read(d)).json()
    assert ticket["status"] == "in_progress" and ticket["id"] == d["ticket"]["id"]
    row = await incident_row(d)
    assert (row.status, row.closure, row.resolved_at) == ("open", None, None)
    assert await events(d) == ["resolved", "reopened"]
    assert d["incident"] in {item["id"] for item in (await board(d, "open"))["items"]}


async def test_objection_before_close_keeps_the_incident_open(tickets: dict) -> None:  # noqa: F811
    d = tickets
    attempt_id = await attempt(d)
    response = await observe(d, attempt_id, "carol", "unresolved")
    assert response.status_code == 200, response.text
    assert (await read(d)).json()["status"] == "in_progress"
    assert (await incident_row(d)).status == "open"
    assert await events(d) == []


async def test_cancelled_ticket_closes_the_incident_with_its_reason(
    tickets: dict,  # noqa: F811
) -> None:
    d = tickets
    response = await command(d, "cancel", "alice", reason="Дубль заявки T-1")
    assert response.status_code == 200, response.text
    row = await incident_row(d)
    assert (row.status, row.closure, row.closure_reason) == (
        "dismissed",
        "ticket_cancelled",
        "Дубль заявки T-1",
    )
    assert await events(d) == ["closed_cancelled"]
    detail = await d["client"].get(
        f"/api/v1/incidents/{d['incident']}", headers=d["headers"]["carol"]
    )
    assert detail.json()["closure"] == "ticket_cancelled"
    assert "Дубль заявки" not in detail.text, "служебная причина жителю не отдаётся"
    assert d["incident"] not in {item["id"] for item in (await board(d, "open"))["items"]}


async def test_race_between_confirmation_and_objection_stays_consistent(
    tickets: dict,  # noqa: F811
) -> None:
    d = tickets
    attempt_id = await attempt(d)
    results = await asyncio.gather(
        observe(d, attempt_id, "carol", "resolved"),
        observe(d, attempt_id, "eve", "unresolved"),
    )
    assert all(response.status_code == 200 for response in results)
    ticket = (await read(d)).json()
    row = await incident_row(d)
    if ticket["status"] == "closed":
        assert row.status == "resolved"
    else:
        assert ticket["status"] == "in_progress" and row.status == "open"


async def test_duplicates_are_offered_only_among_open_problems(
    tickets: dict,  # noqa: F811
) -> None:
    d = tickets
    preview_url = f"/api/v1/houses/{d['ids']['a1']}/reports/preview"
    text = {"description": "Нет холодной воды на кухне с утра"}
    first = await d["client"].post(preview_url, json=text, headers=d["headers"]["carol"])
    assert first.status_code == 200, first.text
    assert d["incident"] in {item["incident_id"] for item in first.json()["duplicates"]}
    attempt_id = await attempt(d)
    assert (await observe(d, attempt_id, "carol", "resolved")).status_code == 200
    second = await d["client"].post(preview_url, json=text, headers=d["headers"]["carol"])
    assert d["incident"] not in {item["incident_id"] for item in second.json()["duplicates"]}


async def test_other_company_problems_do_not_change(tickets: dict) -> None:  # noqa: F811
    d = tickets
    await command(d, "cancel", "alice", reason="Отмена")
    async with d["container"].session_factory() as session:
        other = await session.get(Incident, UUID(d["incidents"]["b1"]))
        assert other is not None and other.status == "open"
    foreign = await d["client"].get(
        f"/api/v1/houses/{d['ids']['b1']}/incidents?state=open", headers=d["headers"]["dave"]
    )
    assert foreign.json()["open_total"] == 1
    hidden = await d["client"].get(
        f"/api/v1/houses/{d['ids']['a1']}/incidents?state=open", headers=d["headers"]["dave"]
    )
    assert hidden.status_code in {403, 404}


async def test_danger_in_the_form_offers_no_duplicates(tickets: dict) -> None:  # noqa: F811
    d = tickets
    await d["client"].post(
        "/api/v1/reports",
        headers={**d["headers"]["eve"], "Idempotency-Key": "other-lamp-f1"},
        json={
            "house_id": str(d["ids"]["a1"]),
            "category": "other",
            "description": "Во дворе сломан фонарь у третьего подъезда",
        },
    )
    response = await d["client"].post(
        f"/api/v1/houses/{d['ids']['a1']}/reports/preview",
        json={"description": "Сильно пахнет газом на лестнице во втором подъезде"},
        headers=d["headers"]["carol"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["danger_kinds"], "опасность найдена правилами"
    assert body["duplicates"] == []
