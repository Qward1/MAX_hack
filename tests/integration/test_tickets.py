"""A-16 TK checks against real PostgreSQL and the authenticated HTTP application.

Linked Reports below are explicit fixtures for an already determined Incident;
they are not evidence of A-06 semantic matching. Concurrent requests use distinct
API sessions/connections; aggregate lock tests also hold independent PG transactions.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from domsignal.db.models import (
    HouseAssignment,
    HouseManagement,
    Incident,
    ManagementCompany,
    OrganizationMembership,
    OutboxMessage,
    Report,
    ResidentMembership,
    ResultObservation,
    Ticket,
    TicketDeadline,
    TicketEvent,
    WorkAttempt,
)
from domsignal.db.repositories.incidents import IncidentRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.main import create_app
from domsignal.services.management import ManagementService
from domsignal.services.tickets import TicketService
from tests.integration.test_chat_bindings import cb  # noqa: F401
from tests.integration.test_tenant_access import dataset  # noqa: F401


@pytest_asyncio.fixture
async def tickets(dataset: dict) -> dict:  # noqa: F811
    d = dataset
    async with d["container"].session_factory() as session, session.begin():
        await session.execute(
            update(HouseManagement)
            .where(HouseManagement.id.in_([d["ids"]["ma1"], d["ids"]["ma2"], d["ids"]["mb1"]]))
            .values(ticket_intake_enabled=True)
        )
    response = await d["client"].post(
        "/api/v1/reports",
        headers={**d["headers"]["carol"], "Idempotency-Key": "ticket-intake-1"},
        json={
            "house_id": str(d["ids"]["a1"]),
            "category": "water",
            "description": "A16 accepted report with a public category",
        },
    )
    assert response.status_code == 201, response.text
    d["incident"] = response.json()["incident"]["id"]
    view = await d["client"].get(
        f"/api/v1/tickets?house_id={d['ids']['a1']}", headers=d["headers"]["bob"]
    )
    assert view.status_code == 200, view.text
    assert view.json()["page"]["total"] == 1
    d["ticket"] = view.json()["items"][0]
    await linked_report(d, "eve")
    return d


async def linked_report(d: dict, actor: str) -> None:
    async with d["container"].session_factory() as session, session.begin():
        context = await d["container"].membership_service.require_house(
            session,
            user_id=d["ids"][actor],
            house_id=d["ids"]["a1"],
            for_write=True,
        )
        await IncidentRepository(session).create_report(
            incident_id=UUID(d["incident"]),
            house_id=d["ids"]["a1"],
            author_id=d["ids"][actor],
            category="water",
            description=f"Separate original Report by {actor}",
            classification_mode="manual",
            provenance="api",
        )
        await TicketService().ensure(session, context=context, incident_id=UUID(d["incident"]))


async def read(d: dict, user: str = "bob"):
    return await d["client"].get(f"/api/v1/tickets/{d['ticket']['id']}", headers=d["headers"][user])


async def command(
    d: dict,
    action: str,
    user: str = "bob",
    *,
    version: int | None = None,
    key: str | None = None,
    **body,
):
    if version is None:
        version = (await read(d, user)).json()["version"]
    return await d["client"].post(
        f"/api/v1/tickets/{d['ticket']['id']}/{action}",
        headers={**d["headers"][user], "Idempotency-Key": key or str(uuid4())},
        json={"expected_version": version, **body},
    )


async def attempt(d: dict) -> str:
    for action in ("accept", "start"):
        response = await command(d, action)
        assert response.status_code == 200, response.text
    response = await command(d, "work-attempts", public_description="Проверено, работа выполнена")
    assert response.status_code == 200, response.text
    return response.json()["attempt_id"]


async def observe(
    d: dict, attempt_id: str, user: str, outcome: str, *, key: str | None = None, **body
):
    return await d["client"].post(
        f"/api/v1/work-attempts/{attempt_id}/observations",
        headers={**d["headers"][user], "Idempotency-Key": key or str(uuid4())},
        json={"outcome": outcome, **body},
    )


async def count(d: dict, model) -> int:
    async with d["container"].session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_tk01_intake_and_shared_incident_preserves_reports(tickets: dict) -> None:
    d = tickets
    view = (await read(d)).json()
    assert view["status"] == "new"
    assert view["assignee_id"] == str(d["ids"]["bob"])
    assert view["accepted_by"] is None
    assert view["internal_number"].startswith("T-")
    assert view["routing_reason"] == "single_responsible"
    assert await count(d, Ticket) == 1
    async with d["container"].session_factory() as session:
        reports = list(
            await session.scalars(select(Report).where(Report.incident_id == UUID(d["incident"])))
        )
        assert {r.author_id for r in reports} == {d["ids"]["carol"], d["ids"]["eve"]}
        assert len({r.id for r in reports}) == 2
        assert (await session.get(Incident, UUID(d["incident"]))).status == "open"
    # The old disabled-contour reports remain unchanged and are not backfilled by a read.
    old = await d["client"].get(
        f"/api/v1/incidents/{d['incidents']['a1']}/work-status", headers=d["headers"]["carol"]
    )
    assert old.json()["ticket_id"] is None
    assert await count(d, Ticket) == 1


async def test_tk02_lifecycle_late_objection_rework_and_stale(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    assert (await read(d)).json()["status"] == "verification_pending"  # Silence is not success.
    first = await observe(d, attempt_id, "carol", "resolved", comment="my private confirmation")
    assert first.status_code == 200, first.text
    assert first.json()["current"]["status"] == "closed"
    late = await observe(d, attempt_id, "eve", "unresolved", comment="my private objection")
    assert late.status_code == 200, late.text
    assert late.json()["state_changed"] and late.json()["applied_to_current"]
    assert late.json()["current"]["status"] == "in_progress"
    assert late.json()["current"]["observation_conflict"]
    fixed = await observe(
        d, attempt_id, "eve", "resolved", corrects_id=late.json()["observation"]["id"]
    )
    assert fixed.json()["current"]["status"] == "in_progress"
    assert fixed.json()["current"]["latest_attempt"]["rework_required"]
    assert not fixed.json()["current"]["observation_conflict"]
    retry = await command(d, "work-attempts", public_description="Выполнена повторная работа")
    assert retry.status_code == 200, retry.text
    new_id = retry.json()["attempt_id"]
    assert new_id != attempt_id
    stale = await observe(d, attempt_id, "carol", "unresolved")
    assert not stale.json()["applied_to_current"] and not stale.json()["state_changed"]
    assert stale.json()["current"]["status"] == "verification_pending"
    final = await observe(d, new_id, "eve", "resolved")
    assert final.json()["current"]["status"] == "closed"
    assert await count(d, Ticket) == 1
    assert await count(d, WorkAttempt) == 2
    assert await count(d, ResultObservation) == 5
    history = await d["client"].get(
        f"/api/v1/tickets/{d['ticket']['id']}/events?limit=2&offset=1",
        headers=d["headers"]["alice"],
    )
    assert len(history.json()["items"]) == 2
    assert history.json()["page"]["total"] == (await read(d)).json()["version"]
    async with d["container"].session_factory() as session:
        outcomes = list(
            await session.scalars(
                select(ResultObservation)
                .where(
                    ResultObservation.actor_id == d["ids"]["eve"],
                    ResultObservation.attempt_id == UUID(attempt_id),
                )
                .order_by(ResultObservation.revision)
            )
        )
        assert [o.outcome for o in outcomes] == ["unresolved", "resolved"]
        assert outcomes[1].corrects_id == outcomes[0].id


@pytest.mark.parametrize(
    "user,code",
    [
        ("beta_admin", 404),
        ("dave", 404),
        ("unassigned", 404),
        ("superadmin", 404),
        ("carol", 403),
    ],
)
async def test_tk03_private_scope_and_nested_ids(tickets: dict, user: str, code: int) -> None:
    d = tickets
    attempt_id = await attempt(d)
    for path in (
        f"/tickets/{d['ticket']['id']}",
        f"/tickets/{d['ticket']['id']}/events",
        f"/tickets/{d['ticket']['id']}/work-attempts",
        f"/tickets/{d['ticket']['id']}/deadlines",
        f"/tickets/{d['ticket']['id']}/assignees",
        f"/work-attempts/{attempt_id}/observations",
        f"/tickets?house_id={d['ids']['a1']}&limit=1&offset=100",
    ):
        response = await d["client"].get("/api/v1" + path, headers=d["headers"][user])
        assert response.status_code == code, (path, response.text)
        assert "public_description" not in response.text
    denied = await command(d, "accept", user=user, version=1)
    assert denied.status_code == code


async def test_tk04_resident_allowlist_and_own_history(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    await observe(d, attempt_id, "carol", "resolved", comment="SECRET_CAROL")
    response = await observe(d, attempt_id, "eve", "unresolved", comment="SECRET_EVE")
    summary = response.json()["current"]
    assert "SECRET_CAROL" not in response.text
    for forbidden in (
        "assignee_id",
        "reported_by",
        "performed_by",
        "management_id",
        "tenant_id",
        "actor_id",
        "created_by",
        "routing_reason",
        "accepted_by",
        "assignee_name",
        "performer_name",
        "resolved_count",
        "unresolved_count",
    ):
        assert forbidden not in response.text
    assert summary["my_latest_observation"]["comment"] == "SECRET_EVE"
    own = await d["client"].get(
        f"/api/v1/work-attempts/{attempt_id}/my-observations", headers=d["headers"]["carol"]
    )
    assert own.json()["page"]["total"] == 1
    assert "SECRET_EVE" not in own.text and "actor_id" not in own.text


async def test_tk05_self_verification_and_participation(tickets: dict) -> None:
    d = tickets
    async with d["container"].session_factory() as session, session.begin():
        for actor in ("bob", "alice"):
            session.add(ResidentMembership(user_id=d["ids"][actor], house_id=d["ids"]["a1"]))
    await linked_report(d, "bob")
    await linked_report(d, "alice")
    for action in ("accept", "start"):
        assert (await command(d, action)).status_code == 200
    reported = await command(
        d, "work-attempts", user="alice", public_description="Отчёт администратора"
    )
    attempt_id = reported.json()["attempt_id"]
    for actor in ("bob", "alice"):
        denied = await observe(d, attempt_id, actor, "resolved")
        assert denied.status_code == 403
    async with d["container"].session_factory() as session, session.begin():
        session.add(ResidentMembership(user_id=d["ids"]["unassigned"], house_id=d["ids"]["a1"]))
    assert (await observe(d, attempt_id, "unassigned", "resolved")).status_code == 403


async def test_tk06_idempotency_current_replay_hash_and_revoke(tickets: dict) -> None:
    d = tickets
    await command(d, "accept")
    await command(d, "start")
    version = (await read(d)).json()["version"]
    body = {"version": version, "key": "stable-work-attempt", "public_description": "Work result"}
    first, repeat = await asyncio.gather(
        command(d, "work-attempts", **body), command(d, "work-attempts", **body)
    )
    assert first.status_code == repeat.status_code == 200
    assert first.json()["attempt_id"] == repeat.json()["attempt_id"]
    assert await count(d, WorkAttempt) == 1
    attempt_id = first.json()["attempt_id"]
    result = await observe(d, attempt_id, "carol", "resolved", key="repeat-observation")
    replay = await command(d, "work-attempts", **body)
    assert replay.json()["replayed"]
    assert replay.json()["ticket"]["status"] == "closed"
    assert replay.json()["effect_version"] < replay.json()["ticket"]["version"]
    conflict = await command(d, "work-attempts", **{**body, "public_description": "Other result"})
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    second = await observe(d, attempt_id, "carol", "resolved", key="repeat-observation")
    assert second.json()["observation"]["id"] == result.json()["observation"]["id"]
    async with d["container"].session_factory() as session, session.begin():
        await session.execute(
            update(HouseAssignment)
            .where(HouseAssignment.user_id == d["ids"]["bob"])
            .values(status="revoked")
        )
        await session.execute(
            update(ResidentMembership)
            .where(ResidentMembership.user_id == d["ids"]["carol"])
            .values(status="revoked")
        )
    assert (await command(d, "work-attempts", **body)).status_code == 404
    assert (
        await observe(d, attempt_id, "carol", "resolved", key="repeat-observation")
    ).status_code == 404
    # Исполнитель отозван, но заявка уже закрыта — переназначать её незачем
    # (активная заявка с отозванным исполнителем — test_tk07).
    closed = (await read(d, "alice")).json()
    assert closed["status"] == "closed" and not closed["requires_reassignment"]


async def test_tk07_parallel_positive_negative_and_ensure(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)

    async def ensure():
        async with d["container"].session_factory() as session, session.begin():
            ctx = await d["container"].membership_service.require_house(
                session,
                user_id=d["ids"]["carol"],
                house_id=d["ids"]["a1"],
                for_write=True,
            )
            return (
                await TicketService().ensure(session, context=ctx, incident_id=UUID(d["incident"]))
            ).id

    results = await asyncio.gather(
        observe(d, attempt_id, "carol", "resolved"),
        observe(d, attempt_id, "eve", "unresolved"),
        ensure(),
        ensure(),
    )
    assert all(r.status_code == 200 for r in results[:2])
    assert results[2] == results[3] == UUID(d["ticket"]["id"])
    view = (await read(d)).json()
    assert view["status"] == "in_progress" and view["observation_conflict"]
    assert await count(d, Ticket) == 1
    assert await count(d, ResultObservation) == 2


async def test_tk08_real_aggregate_lock_and_competing_commands(tickets: dict) -> None:
    d = tickets
    # Hold a separate PG connection: the HTTP write must actually wait on the Incident lock.
    async with d["container"].session_factory() as held:
        async with held.begin():
            await held.execute(
                select(Incident.id).where(Incident.id == UUID(d["incident"])).with_for_update()
            )
            pending = asyncio.create_task(command(d, "accept", version=1))
            done, _ = await asyncio.wait([pending], timeout=0.15)
            assert not done
        assert (await pending).status_code == 200
    await command(d, "start")
    v = (await read(d)).json()["version"]
    responses = await asyncio.gather(
        command(d, "work-attempts", version=v, public_description="First concurrent result"),
        command(d, "work-attempts", version=v, public_description="Second concurrent result"),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert await count(d, WorkAttempt) == 1


async def test_tk09_routing_multiple_none_unknown_and_accept_race(tickets: dict) -> None:
    d = tickets
    async with d["container"].session_factory() as session, session.begin():
        session.add(
            HouseAssignment(
                user_id=d["ids"]["alice"], management_id=d["ids"]["ma1"], role="responsible"
            )
        )

    async def intake(house: str, category: str):
        result = await d["client"].post(
            "/api/v1/reports",
            headers={**d["headers"]["alice"], "Idempotency-Key": str(uuid4())},
            json={
                "house_id": str(d["ids"][house]),
                "category": category,
                "description": "Routing test report",
            },
        )
        assert result.status_code == 201, result.text
        view = await d["client"].get(
            f"/api/v1/tickets?house_id={d['ids'][house]}", headers=d["headers"]["alice"]
        )
        return view.json()["items"][0]

    multiple = await intake("a1", "water")
    assert multiple["routing_reason"] == "multiple_responsibles" and multiple["assignee_id"] is None
    none = await intake("a2", "water")
    assert none["routing_reason"] == "no_responsible" and none["assignee_id"] is None
    unknown = await intake("a1", "other")
    assert unknown["status"] == "needs_clarification"
    assert unknown["routing_reason"] == "responsibility_unknown"
    d = {**d, "ticket": multiple}
    responses = await asyncio.gather(
        command(d, "accept", "bob", version=1), command(d, "accept", "alice", version=1)
    )
    assert sorted(r.status_code for r in responses) == [200, 403]
    assert (await read(d, "alice")).json()["accepted_by"] in {
        str(d["ids"]["alice"]),
        str(d["ids"]["bob"]),
    }


async def test_tk10_reassignment_wait_cancel_and_invalid_transition(tickets: dict) -> None:
    d = tickets
    assert (await command(d, "start")).status_code == 403
    await command(d, "accept")
    await command(d, "start")
    wait = await command(d, "wait-external", reason="Ожидаем сведения внешней стороны")
    assert wait.json()["ticket"]["status"] == "waiting_external"
    reassigned = await command(
        d, "assign", "alice", assignee_id=str(d["ids"]["alice"]), reason="Смена исполнителя"
    )
    assert reassigned.json()["ticket"]["accepted_by"] is None
    resumed = await command(d, "resume", "alice", reason="Сведения получены")
    assert resumed.json()["ticket"]["status"] == "new"
    assert (await command(d, "accept", "bob")).status_code == 403
    assert (await command(d, "accept", "alice")).status_code == 200
    assert (await command(d, "accept", "alice")).status_code == 409
    assert (
        await command(d, "cancel", "alice", reason="Не требуется дальнейшая работа")
    ).status_code == 200
    assert (await read(d, "alice")).json()["allowed_actions"] == []


async def test_tk11_cancelled_observation_historical(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    assert (await command(d, "cancel", "alice", reason="Отмена с причиной")).status_code == 200
    recorded = await observe(d, attempt_id, "eve", "unresolved")
    assert recorded.status_code == 200
    assert not recorded.json()["applied_to_current"]
    assert recorded.json()["current"]["status"] == "cancelled"


@pytest.mark.parametrize("change", ["switch", "ended", "suspended"])
async def test_tk12_management_and_tenant_invalidation(tickets: dict, change: str) -> None:
    d = tickets
    attempt_id = await attempt(d)
    async with d["container"].session_factory() as session, session.begin():
        if change == "switch":
            await ManagementService().switch(
                session,
                management_id=d["ids"]["ma1"],
                tenant_id=d["ids"]["beta"],
                at=datetime.now(UTC),
                basis_reference="test switch",
            )
        elif change == "ended":
            await session.execute(
                update(HouseManagement)
                .where(HouseManagement.id == d["ids"]["ma1"])
                .values(status="ended")
            )
        else:
            await session.execute(
                update(ManagementCompany)
                .where(ManagementCompany.id == d["ids"]["alpha"])
                .values(status="suspended")
            )
    assert (await read(d)).status_code == 404
    assert (await observe(d, attempt_id, "carol", "resolved")).status_code == 404
    assert (
        await command(d, "cancel", "alice", version=4, reason="No authority")
    ).status_code == 404
    assert (await read(d, "beta_admin")).status_code == 404
    assert await count(d, Ticket) == 1


async def test_tk13_typed_deadlines_and_revision_history(tickets: dict) -> None:
    d = tickets
    events = await d["client"].get(
        f"/api/v1/tickets/{d['ticket']['id']}/events", headers=d["headers"]["alice"]
    )
    anchor = events.json()["items"][0]
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    for kind in ("response", "completion", "next_update"):
        response = await command(
            d,
            "deadlines",
            "alice",
            kind=kind,
            basis="internal",
            start_event_id=anchor["id"],
            due_at=None if kind == "response" else tomorrow,
            reason="Внутренний ориентир",
        )
        assert response.status_code == 200, response.text
    moved = await command(
        d,
        "deadlines",
        "alice",
        kind="completion",
        basis="internal",
        start_event_id=anchor["id"],
        due_at=(datetime.now(UTC) + timedelta(days=2)).isoformat(),
        reason="Перенос внутреннего ориентира",
    )
    assert moved.status_code == 200
    agreed = await command(
        d,
        "deadlines",
        "alice",
        kind="completion",
        basis="agreed",
        start_event_id=anchor["id"],
        due_at=tomorrow,
        reason="Согласование с заявителем",
        agreement_reference="PRIVATE agreement reference",
        agreed_at=datetime.now(UTC).isoformat(),
    )
    assert agreed.status_code == 200
    bad = await command(
        d,
        "deadlines",
        "alice",
        kind="completion",
        basis="normative",
        start_event_id=anchor["id"],
        due_at=tomorrow,
        reason="Claimed rule",
    )
    assert bad.status_code == 422
    missing = await command(
        d,
        "deadlines",
        "alice",
        kind="completion",
        basis="agreed",
        start_event_id=anchor["id"],
        due_at=tomorrow,
        reason="No source",
    )
    assert missing.status_code == 422
    assert await count(d, TicketDeadline) == 5
    public = await d["client"].get(
        f"/api/v1/incidents/{d['incident']}/work-status", headers=d["headers"]["carol"]
    )
    assert len(public.json()["deadlines"]) == 4
    assert "PRIVATE" not in public.text and "recorded_by" not in public.text
    assert {r["started_at"] for r in public.json()["deadlines"]} == {anchor["created_at"]}


async def test_tk14_atomic_rollback_intake_and_command(tickets: dict, monkeypatch) -> None:
    d = tickets
    before = [await count(d, m) for m in (Report, Incident, Ticket, TicketEvent, OutboxMessage)]
    original = ReliabilityRepository.add_outbox

    def fail(self, *, kind, **kwargs):
        if kind == "ticket.notification_intent.v1":
            raise RuntimeError("Injected durable outbox failure")
        return original(self, kind=kind, **kwargs)

    monkeypatch.setattr(ReliabilityRepository, "add_outbox", fail)
    with pytest.raises(RuntimeError, match="Injected"):
        await d["client"].post(
            "/api/v1/reports",
            headers={**d["headers"]["carol"], "Idempotency-Key": "failed-intake-command"},
            json={
                "house_id": str(d["ids"]["a1"]),
                "category": "water",
                "description": "Rollback test",
            },
        )
    with pytest.raises(RuntimeError, match="Injected"):
        await command(d, "accept")
    assert before == [
        await count(d, m) for m in (Report, Incident, Ticket, TicketEvent, OutboxMessage)
    ]
    assert (await read(d)).json()["version"] == 1


async def test_tk15_persist_restart_and_pending_outbox(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    await observe(d, attempt_id, "carol", "resolved", comment="NEVER_COPY_TO_INTENT")
    await observe(d, attempt_id, "eve", "unresolved")
    before = (await read(d)).json()
    new_app = create_app(d["container"].settings)
    async with AsyncClient(
        transport=ASGITransport(app=new_app), base_url="http://restart"
    ) as client:
        after = await client.get(
            f"/api/v1/tickets/{d['ticket']['id']}", headers=d["headers"]["bob"]
        )
        assert after.json() == before
    await new_app.state.container.engine.dispose()
    async with d["container"].session_factory() as session:
        intents = list(
            await session.scalars(
                select(OutboxMessage).where(OutboxMessage.kind == "ticket.notification_intent.v1")
            )
        )
        assert len(intents) == before["version"]
        assert all(i.status == "pending" and i.dedupe_key for i in intents)
        assert len({i.dedupe_key for i in intents}) == len(intents)
        assert "NEVER_COPY" not in str([i.payload for i in intents])
    assert "ticket.notification_intent.v1" not in d["container"].worker_handlers.mapping


async def test_tk16_db_scope_immutability_and_active_uniqueness(tickets: dict) -> None:
    d = tickets
    tid = UUID(d["ticket"]["id"])
    for values in (
        {"management_id": d["ids"]["mb1"]},
        {"created_by": d["ids"]["eve"]},
        {"number": 999999},
    ):
        async with d["container"].session_factory() as session:
            with pytest.raises(DBAPIError):
                async with session.begin():
                    await session.execute(update(Ticket).where(Ticket.id == tid).values(**values))
    async with d["container"].session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Ticket(
                        incident_id=UUID(d["incident"]),
                        management_id=d["ids"]["ma1"],
                        house_id=d["ids"]["a1"],
                        source="api",
                        created_by=d["ids"]["carol"],
                        routing_reason="test",
                        status="waiting_external",
                    )
                )
    attempt_id = await attempt(d)
    result = await observe(d, attempt_id, "carol", "resolved")
    for sql, values in [
        ("UPDATE work_attempts SET reported_by=:actor WHERE id=:id", {"id": attempt_id}),
        (
            "UPDATE result_observations SET outcome='unresolved' WHERE id=:id",
            {"id": result.json()["observation"]["id"]},
        ),
        ("DELETE FROM ticket_events WHERE ticket_id=:id", {"id": str(tid)}),
    ]:
        async with d["container"].session_factory() as session:
            with pytest.raises(DBAPIError):
                async with session.begin():
                    await session.execute(text(sql), {**values, "actor": d["ids"]["alice"]})


async def test_tk17_client_context_and_validation(tickets: dict) -> None:
    d = tickets
    response = await command(d, "accept", version=1, actor_id=str(d["ids"]["alice"]))
    assert response.status_code == 422
    response = await d["client"].post(
        f"/api/v1/tickets/{d['ticket']['id']}/accept",
        headers=d["headers"]["bob"],
        json={"expected_version": 1},
    )
    assert response.status_code == 422  # Mandatory idempotency header.
    assert (
        await d["client"].get(
            "/api/v1/tickets",
            params={"house_id": str(d["ids"]["a1"]), "limit": 101},
            headers=d["headers"]["bob"],
        )
    ).status_code == 422
    assert (await d["client"].get(f"/api/v1/tickets/{d['ticket']['id']}")).status_code == 401
    assert await count(d, TicketEvent) == 1


async def test_tk18_concurrent_absent_ensure_and_duplicate_intake(tickets: dict) -> None:
    d = tickets

    async def ensure_absent():
        async with d["container"].session_factory() as session, session.begin():
            ctx = await d["container"].membership_service.require_house(
                session,
                user_id=d["ids"]["carol"],
                house_id=d["ids"]["a1"],
                for_write=True,
            )
            # Explicit test-only selection of historical accepted data, not a migration backfill.
            ticket = await TicketService().ensure(
                session, context=ctx, incident_id=UUID(d["incidents"]["a1"])
            )
            return ticket.id

    ids = await asyncio.gather(*(ensure_absent() for _ in range(5)))
    assert len(set(ids)) == 1
    assert await count(d, Ticket) == 2

    async def report():
        return await d["client"].post(
            "/api/v1/reports",
            headers={**d["headers"]["carol"], "Idempotency-Key": "concurrent-intake"},
            json={
                "house_id": str(d["ids"]["a1"]),
                "category": "water",
                "description": "Repeated accepted report",
            },
        )

    results = await asyncio.gather(report(), report())
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json()["report_id"] == results[1].json()["report_id"]
    assert await count(d, Ticket) == 3


async def test_tk19_revoked_assignee_reopens_into_visible_reserve(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    await observe(d, attempt_id, "carol", "resolved")
    async with d["container"].session_factory() as session, session.begin():
        await session.execute(
            update(OrganizationMembership)
            .where(OrganizationMembership.user_id == d["ids"]["bob"])
            .values(status="revoked")
        )
    reopened = await observe(d, attempt_id, "eve", "unresolved")
    assert reopened.json()["current"]["status"] == "in_progress"
    view = (await read(d, "alice")).json()
    assert view["requires_reassignment"] and view["assignee_id"] == str(d["ids"]["bob"])
    assert view["accepted_by"] is None
    assert view["latest_attempt"]["performed_by"] == str(d["ids"]["bob"])
    assert (
        await command(
            d, "work-attempts", "bob", version=view["version"], public_description="Revoked work"
        )
    ).status_code == 404
    moved = await command(
        d,
        "assign",
        "alice",
        assignee_id=str(d["ids"]["alice"]),
        reason="Замена недоступного исполнителя",
    )
    assert moved.json()["ticket"]["status"] == "new"
    assert (await command(d, "accept", "alice")).status_code == 200


async def test_tk20_newer_ticket_keeps_old_observation_historical(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    await observe(d, attempt_id, "carol", "resolved")
    # A future independent-episode producer might create this record; A-16 never does.
    async with d["container"].session_factory() as session, session.begin():
        newer = Ticket(
            incident_id=UUID(d["incident"]),
            management_id=d["ids"]["ma1"],
            house_id=d["ids"]["a1"],
            source="api",
            created_by=d["ids"]["carol"],
            routing_reason="test_future_episode",
            status="new",
        )
        session.add(newer)
        await session.flush()
        newer_id = newer.id
    result = await observe(d, attempt_id, "eve", "unresolved", key="historic-on-newer")
    assert result.status_code == 200, result.text
    assert not result.json()["applied_to_current"] and not result.json()["state_changed"]
    assert result.json()["current"]["ticket_id"] == str(newer_id)
    replay = await observe(d, attempt_id, "eve", "unresolved", key="historic-on-newer")
    assert replay.json()["current"]["ticket_id"] == str(newer_id)
    assert (await read(d)).json()["status"] == "closed"


async def test_tk21_db_rejects_wrong_scope_and_foreign_latest_attempt(tickets: dict) -> None:
    d = tickets
    async with d["container"].session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Ticket(
                        incident_id=UUID(d["incidents"]["b1"]),
                        management_id=d["ids"]["ma1"],
                        house_id=d["ids"]["a1"],
                        source="api",
                        created_by=d["ids"]["carol"],
                        routing_reason="forged",
                        status="closed",
                    )
                )
    attempt_id = await attempt(d)
    async with d["container"].session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Ticket(
                        incident_id=UUID(d["incidents"]["a2"]),
                        management_id=d["ids"]["ma2"],
                        house_id=d["ids"]["a2"],
                        source="api",
                        created_by=d["ids"]["alice"],
                        routing_reason="test",
                        status="new",
                        latest_attempt_id=UUID(attempt_id),
                    )
                )


async def test_tk22_worker_faults_do_not_deliver_or_rollback_ticket(tickets: dict) -> None:
    from domsignal.worker.runner import WorkerRunner

    d = tickets
    async with d["container"].session_factory() as session, session.begin():
        repo = ReliabilityRepository(session)
        await repo.add_job(kind="unsupported.delivery", payload={}, priority=1)
        await repo.add_job(
            kind="diagnostic.record", payload={"destination": "test", "text": "healthy"}
        )
    runner = WorkerRunner(
        session_factory=d["container"].session_factory,
        handlers=d["container"].worker_handlers.mapping,
    )
    assert await runner.run_once()  # Unknown kind is separately retried, not an outbox dispatcher.
    assert await runner.run_once()  # Healthy queued job still progresses.
    assert len(d["container"].transport.sent) == 1
    assert (await read(d)).json()["status"] == "new"
    async with d["container"].session_factory() as session:
        intent = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.kind == "ticket.notification_intent.v1")
        )
        assert intent.status == "pending"


async def test_tk23_group_shared_intake_and_unbound_suspended_guard(cb) -> None:  # noqa: F811
    async with cb.container.session_factory() as session, session.begin():
        await session.execute(
            update(HouseManagement)
            .where(HouseManagement.id == cb.ids["ma1"])
            .values(ticket_intake_enabled=True)
        )
    await cb.message(mid="unbound")
    await cb.drain()
    assert await cb.scalar(select(func.count()).select_from(Ticket)) == 0
    _, binding = await cb.bind()
    await cb.message(mid="ordinary", message="A normal conversation")
    await cb.drain()
    assert await cb.scalar(select(func.count()).select_from(Ticket)) == 0
    await cb.message(mid="accepted")
    await cb.drain()
    ticket = await cb.scalar(select(Ticket))
    assert ticket is not None and ticket.source == "max_group"
    intent = await cb.scalar(
        select(OutboxMessage).where(OutboxMessage.kind == "ticket.notification_intent.v1")
    )
    assert intent.payload["chat_binding_id"] == binding["id"]
    assert intent.payload["binding_version"] == binding["binding_version"]
    await cb.webhook("bot_removed")
    await cb.message(mid="suspended")
    await cb.drain()
    assert await cb.scalar(select(func.count()).select_from(Ticket)) == 1


async def test_tk24_operator_scope_and_assignee_lookup(tickets: dict) -> None:
    d = tickets
    async with d["container"].session_factory() as session, session.begin():
        session.add(
            HouseAssignment(
                user_id=d["ids"]["unassigned"], management_id=d["ids"]["ma2"], role="operator"
            )
        )
    assert (await read(d, "unassigned")).status_code == 404  # Same organization, another house.
    async with d["container"].session_factory() as session, session.begin():
        session.add(
            HouseAssignment(
                user_id=d["ids"]["unassigned"], management_id=d["ids"]["ma1"], role="operator"
            )
        )
    assert (await read(d, "unassigned")).status_code == 200
    assert (await command(d, "accept", "unassigned")).status_code == 403
    assert (
        await command(d, "assign", "unassigned", assignee_id=None, reason="No coordination right")
    ).status_code == 403
    assert (
        await command(
            d, "assign", "alice", assignee_id=str(d["ids"]["beta_admin"]), reason="Foreign assignee"
        )
    ).status_code == 403
    await command(d, "assign", "alice", assignee_id=None, reason="В очередь дома")
    assert (await command(d, "accept", "unassigned")).status_code == 200
    assert (await command(d, "start", "unassigned")).status_code == 200


async def test_tk25_replay_spoofing_and_diagnostic_exclusion(tickets: dict) -> None:
    from domsignal.contracts.jobs import NormalizedInboundEvent

    d = tickets
    body = NormalizedInboundEvent(
        event_id="ticket-replay",
        event_type="diagnostic.report",
        external_user_id="test-carol",
        house_id=d["ids"]["a1"],
        category="water",
        description="Diagnostic replay only",
        occurred_at=datetime.now(UTC),
    ).model_dump(mode="json")
    for actor, override, code in [
        ("eve", {}, 403),
        ("carol", {"house_id": str(d["ids"]["b1"])}, 404),
    ]:
        result = await d["client"].post(
            "/max/replay", headers=d["headers"][actor], json={**body, **override}
        )
        assert result.status_code == code, result.text
    accepted = await d["client"].post("/max/replay", headers=d["headers"]["carol"], json=body)
    assert accepted.status_code == 202, accepted.text
    from domsignal.worker.runner import WorkerRunner

    runner = WorkerRunner(
        session_factory=d["container"].session_factory,
        handlers=d["container"].worker_handlers.mapping,
    )
    assert await runner.run_once()
    assert await count(d, Ticket) == 1  # Accepted diagnostic Report does not instruct a real queue.


async def test_b14_internal_attempt_summary_tracks_current_revisions(tickets: dict) -> None:
    d = tickets
    attempt_id = await attempt(d)
    await observe(d, attempt_id, "carol", "resolved")
    await observe(d, attempt_id, "eve", "unresolved")
    view = (await read(d)).json()
    assert view["assignee_name"]
    assert view["latest_attempt"]["performer_name"] == view["assignee_name"]
    assert view["latest_attempt"]["resolved_count"] == 1
    assert view["latest_attempt"]["unresolved_count"] == 1
    await observe(d, attempt_id, "carol", "unresolved")
    history = await d["client"].get(
        f"/api/v1/tickets/{d['ticket']['id']}/work-attempts", headers=d["headers"]["bob"]
    )
    summary = history.json()["items"][0]
    assert summary["resolved_count"] == 0
    assert summary["unresolved_count"] == 2
    assert summary == (await read(d)).json()["latest_attempt"]
