"""ND evidence: real PostgreSQL, HTTP use cases, authenticated webhook and worker."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from domsignal.bootstrap import build_container
from domsignal.bot.messaging import MessagingError
from domsignal.db.models import (
    Job,
    MaxDestinationLimit,
    NotificationDelivery,
    OutboxMessage,
    Report,
    ResidentMembership,
    ResultObservation,
    User,
)
from domsignal.db.repositories.notifications import NotificationRepository
from domsignal.services.management import ManagementService
from domsignal.settings import MaxTransportMode
from domsignal.worker.runner import WorkerRunner
from tests.fakes.max_messaging import RecordingMaxMessagingProvider
from tests.integration.test_tenant_access import dataset  # noqa: F401
from tests.integration.test_tickets import (
    attempt,  # noqa: F401
    command,
    count,
    observe,
    read,
    tickets,  # noqa: F401
)


@pytest_asyncio.fixture
async def nd(tickets):  # noqa: F811
    d = tickets
    c = d["container"]
    # integration_settings is session-scoped; this fixture must not mutate other regressions.
    c.settings = c.settings.model_copy()
    async with c.session_factory() as s, s.begin():
        for actor, number in (("carol", "101"), ("eve", "102"), ("dave", "103")):
            user = await s.get(User, d["ids"][actor])
            user.max_user_id = number
            user.max_identity_verified_at = datetime.now(UTC)
    d["provider"] = RecordingMaxMessagingProvider()
    d["handler"] = c.notifications
    c.notifications.enabled = True
    c.notifications.provider = d["provider"]
    c.settings.max_transport = MaxTransportMode.WEBHOOK
    c.settings.max_webhook_secret = "nd-test-secret"
    return d


async def fanout(d):
    for _ in range(50):
        if not await d["handler"].consume_once():
            return
    raise AssertionError("Consumer did not drain")


async def deliver(d):
    await fanout(d)
    # Advancing a supplied clock avoids real throttling sleeps in deterministic tests.
    at = datetime.now(UTC) + timedelta(minutes=5)
    for i in range(30):
        if not await d["handler"].deliver_once(now=at + timedelta(seconds=i)):
            return
    raise AssertionError("Delivery did not drain")


async def deliveries(d, purpose="work_verification"):
    async with d["container"].session_factory() as s:
        return list(
            await s.scalars(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.purpose == purpose,
                )
                .order_by(NotificationDelivery.created_at, NotificationDelivery.recipient_user_id)
            )
        )


def callback(row, *, actor=None, outcome="resolved", callback_id="cb-1"):
    return {
        "update_type": "message_callback",
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        "callback": {
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "callback_id": callback_id,
            "payload": f"{row.launch_ref}:{outcome}",
            "user": {"user_id": int(actor or row.destination), "is_bot": False},
        },
        "message": {
            "recipient": {"chat_id": 222, "chat_type": "dialog"},
            "body": {"mid": row.provider_message_id},
        },
    }


async def webhook(d, payload, secret="nd-test-secret"):
    return await d["client"].post(
        "/max/webhook", json=payload, headers={"X-Max-Bot-Api-Secret": secret}
    )


def runner(d):
    return WorkerRunner(
        session_factory=d["container"].session_factory,
        handlers=d["container"].worker_handlers.mapping,
    )


async def test_nd01_02_04_06_08_11_26_fanout_concurrency(nd):
    d = nd
    aid = await attempt(d)
    await asyncio.gather(*(fanout(d) for _ in range(3)))
    rows = await deliveries(d)
    assert len(rows) == 2
    assert {r.recipient_user_id for r in rows} == {d["ids"]["carol"], d["ids"]["eve"]}
    async with d["container"].session_factory() as s:
        intents = list(
            await s.scalars(
                select(OutboxMessage).where(
                    OutboxMessage.payload["attempt_id"].astext == aid,
                )
            )
        )
        assert len(intents) == 1 and intents[0].status == "processed"
    await asyncio.gather(*(deliver(d) for _ in range(3)))
    assert len(d["provider"].sent) == 2
    for destination, _, message in d["provider"].sent:
        assert destination in {"101", "102"}
        assert [b.text for row in message.buttons for b in row] == [
            "Открыть и проверить",
            "Исправлено",
            "Проблема осталась",
        ]
        assert "Separate original Report" not in message.text
        assert "A16 accepted" not in message.text
        assert "carol" not in message.text and "eve" not in message.text
    assert len({r.launch_ref for r in rows}) == 2
    assert all(
        r.status == "accepted" and r.provider_message_id and r.accepted_at
        for r in await deliveries(d)
    )
    await deliver(d)
    assert len(d["provider"].sent) == 2


async def test_nd03_identity_not_inferred_from_legacy_id(nd):
    d = nd
    async with d["container"].session_factory() as s, s.begin():
        await s.execute(
            update(User).where(User.id == d["ids"]["carol"]).values(max_identity_verified_at=None)
        )
    await attempt(d)
    await deliver(d)
    skipped = next(r for r in await deliveries(d) if r.recipient_user_id == d["ids"]["carol"])
    assert skipped.status == "skipped" and skipped.last_error_code == "NO_MAX_IDENTITY"
    assert {x[0] for x in d["provider"].sent} == {"102"}


@pytest.mark.parametrize("change", ["revoked", "management", "identity"])
async def test_nd05_27_access_rechecked_after_fanout(nd, change):
    d = nd
    await attempt(d)
    await fanout(d)
    async with d["container"].session_factory() as s, s.begin():
        if change == "revoked":
            await s.execute(
                update(ResidentMembership)
                .where(
                    ResidentMembership.house_id == d["ids"]["a1"],
                )
                .values(status="revoked")
            )
        elif change == "management":
            await ManagementService().switch(
                s,
                management_id=d["ids"]["ma1"],
                tenant_id=d["ids"]["beta"],
                at=datetime.now(UTC),
                basis_reference="ND synthetic switch",
            )
        else:
            await s.execute(
                update(User)
                .where(User.id.in_([d["ids"]["carol"], d["ids"]["eve"]]))
                .values(max_identity_verified_at=None)
            )
    await deliver(d)
    assert not d["provider"].sent
    assert all(r.status == "superseded" for r in await deliveries(d))


async def test_nd07_28_kill_old_attempt_before_send(nd):
    d = nd
    old = await attempt(d)
    await fanout(d)
    assert (await observe(d, old, "carol", "unresolved")).status_code == 200
    result = await command(d, "work-attempts", public_description="Вторая работа")
    new = result.json()["attempt_id"]
    assert old != new
    await deliver(d)
    rows = await deliveries(d)
    assert all(r.status == "superseded" for r in rows if str(r.work_attempt_id) == old)
    assert all(r.status == "accepted" for r in rows if str(r.work_attempt_id) == new)
    assert len(d["provider"].sent) == 2
    assert all("Вторая работа" in x[2].text for x in d["provider"].sent)
    oldrow = next(r for r in rows if str(r.work_attempt_id) == old)
    fake = callback(oldrow)
    fake["message"]["body"]["mid"] = "mid.not-sent"
    await webhook(d, fake)
    await runner(d).run_once()
    assert (await read(d)).json()["status"] == "verification_pending"


async def test_nd12_13_launch_and_no_disclosure(nd):
    d = nd
    aid = await attempt(d)
    await deliver(d)
    row = next(r for r in await deliveries(d) if r.recipient_user_id == d["ids"]["carol"])
    path = f"/api/v1/notification-launch/{row.launch_ref}"
    good = await d["client"].get(path, headers=d["headers"]["carol"])
    # Контракт вырос аддитивно: у ссылки `w_` вид остаётся прежним, а поля
    # карточки маршрута пусты.
    assert good.json() == {
        "kind": "ticket",
        "incident_id": d["incident"],
        "house_id": str(d["ids"]["a1"]),
        "route_outcome_id": None,
        "work_attempt_id": aid,
        "stale": False,
    }
    for foreign in ("dave", "eve", "bob"):
        bad = await d["client"].get(path, headers=d["headers"][foreign])
        assert bad.status_code == 404 and d["incident"] not in bad.text
    assert (await d["client"].get(path)).status_code == 401


async def test_nd14_15_16_18_19_20_29_30_callbacks_and_miniapp(nd):
    d = nd
    old = await attempt(d)
    await deliver(d)
    rows = await deliveries(d)
    row = next(r for r in rows if r.recipient_user_id == d["ids"]["carol"])
    assert (await webhook(d, callback(row), secret="wrong")).status_code == 401
    await webhook(d, callback(row, actor="103", callback_id="wrong-actor"))
    await runner(d).run_once()
    assert await count(d, ResultObservation) == 0
    # Mini App HTTP mutation -> durable reconcile; editing failure cannot undo business commit.
    assert (await observe(d, old, "carol", "unresolved")).status_code == 200
    assert (await read(d)).json()["status"] == "in_progress"
    d["provider"].errors = [MessagingError("MAX_OPERATION_REJECTED", kind="retry")]
    await fanout(d)
    await d["handler"].deliver_once(now=datetime.now(UTC) + timedelta(minutes=6))
    assert any(r.status == "retry_wait" for r in await deliveries(d))
    await deliver(d)  # later clock below is advanced explicitly for failed row
    for i in range(5):
        await d["handler"].deliver_once(now=datetime.now(UTC) + timedelta(minutes=10, seconds=i))
    assert all(len(m.buttons) == 1 for _, m in d["provider"].edited)
    new = (await command(d, "work-attempts", public_description="Исправлено повторно")).json()[
        "attempt_id"
    ]
    for i in range(10):
        await fanout(d)
        await d["handler"].deliver_once(now=datetime.now(UTC) + timedelta(minutes=12, seconds=i))
    row = next(
        r
        for r in await deliveries(d)
        if str(r.work_attempt_id) == new and r.recipient_user_id == d["ids"]["carol"]
    )
    event = callback(row, callback_id="confirmation")
    first, duplicate = await webhook(d, event), await webhook(d, event)
    assert first.status_code == 200 and duplicate.json()["duplicate"] is True
    await runner(d).run_once()
    assert (await read(d)).json()["status"] == "closed"
    assert await count(d, ResultObservation) == 2
    # Replay with another provider callback id cannot correct/recreate the removed action.
    await webhook(d, callback(row, outcome="unresolved", callback_id="replayed-after-edit"))
    await runner(d).run_once()
    assert await count(d, ResultObservation) == 2
    assert (await read(d)).json()["status"] == "closed"


async def test_nd17_historical_callback_uses_a16_semantics(nd):
    d = nd
    old = await attempt(d)
    await deliver(d)
    oldrow = next(r for r in await deliveries(d) if r.recipient_user_id == d["ids"]["eve"])
    await observe(d, old, "carol", "unresolved")
    new = (await command(d, "work-attempts", public_description="Новая работа")).json()[
        "attempt_id"
    ]
    await webhook(d, callback(oldrow, callback_id="historical"))
    await runner(d).run_once()
    assert await count(d, ResultObservation) == 2
    current = (await read(d)).json()
    assert current["latest_attempt"]["id"] == new and current["status"] == "verification_pending"
    async with d["container"].session_factory() as s:
        receipt = await s.scalar(
            select(OutboxMessage).where(
                OutboxMessage.payload["event_kind"].astext == "observation_recorded",
            )
        )
        assert receipt.payload["attempt_id"] == old


@pytest.mark.parametrize(
    "kind,expected", [("retry", "retry_wait"), ("permanent", "failed"), ("unknown", "unknown")]
)
async def test_nd09_10_23_25_provider_failure_restart(nd, kind, expected):
    d = nd
    await attempt(d)
    await fanout(d)
    d["provider"].errors = [MessagingError("SANITIZED_FAILURE", kind=kind)]
    for _ in range(3):  # discard outdated accepted intents until a work POST is attempted
        await d["handler"].deliver_once()
        if any(r.status == expected for r in await deliveries(d)):
            break
    row = next(r for r in await deliveries(d) if r.status == expected)
    assert row.provider_message_id is None and row.accepted_at is None
    c = build_container(d["container"].settings)
    c.notifications.enabled = True
    c.notifications.provider = d["provider"]
    d["handler"] = c.notifications
    await deliver(d)
    async with c.session_factory() as s:
        saved = await s.get(NotificationDelivery, row.id)
        assert saved.status == ("accepted" if kind == "retry" else expected)
        if kind == "retry":
            assert saved.provider_message_id and saved.attempt_count == 2
    await c.engine.dispose()


async def test_nd22_shared_destination_limit_isolated_dialogs(nd):
    d = nd
    now = datetime.now(UTC)
    from uuid import uuid4

    async with d["container"].session_factory() as s, s.begin():
        repo = NotificationRepository(s)
        token = uuid4()
        assert await repo.reserve_destination("101", token, now) is None
        assert await repo.reserve_destination("101", uuid4(), now) > now
        assert await repo.reserve_destination("102", uuid4(), now) is None
        await repo.release_destination("101", token, now)
        assert await repo.reserve_destination("101", uuid4(), now + timedelta(milliseconds=499))
        assert (
            await repo.reserve_destination("101", uuid4(), now + timedelta(milliseconds=500))
            is None
        )


async def test_nd23_processing_crash_is_unknown_not_resent(nd):
    d = nd
    await attempt(d)
    await fanout(d)
    rows = await deliveries(d)
    async with d["container"].session_factory() as s, s.begin():
        await s.execute(
            update(NotificationDelivery)
            .where(NotificationDelivery.id == rows[0].id)
            .values(status="processing", lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    await deliver(d)
    saved = next(r for r in await deliveries(d) if r.id == rows[0].id)
    assert saved.status == "unknown" and saved.last_error_code == "SEND_LEASE_EXPIRED"
    assert len(d["provider"].sent) == 1


async def test_nd20_answer_failure_durable_bounded_after_commit(nd):
    d = nd
    await attempt(d)
    await deliver(d)
    row = (await deliveries(d))[0]
    payload = callback(row)
    await webhook(d, payload)
    await runner(d).run_once()
    assert (await read(d)).json()["status"] == "closed"
    async with d["container"].session_factory() as s, s.begin():
        await s.execute(
            update(MaxDestinationLimit).values(
                lease_until=None,
                next_allowed_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    d["provider"].errors = [MessagingError("MAX_OPERATION_REJECTED", kind="retry")]
    await runner(d).run_once()
    async with d["container"].session_factory() as s:
        answer = await s.scalar(select(Job).where(Job.kind == "max.ticket.answer"))
        assert answer.status == "pending" and answer.last_error_code == "MAX_OPERATION_REJECTED"
    assert (await read(d)).json()["status"] == "closed"
    assert await count(d, ResultObservation) == 1


async def test_accepted_is_informational_and_started_has_no_new_delivery(nd):
    d = nd
    assert (await command(d, "accept")).status_code == 200
    await deliver(d)
    assert len(d["provider"].sent) == 2
    assert all(
        "Проблема принята в работу" in message.text and len(message.buttons) == 1
        for _, _, message in d["provider"].sent
    )
    assert (await command(d, "start")).status_code == 200
    await deliver(d)
    assert len(d["provider"].sent) == 2


async def test_nd04_foreign_report_author_cannot_receive(nd):
    d = nd
    async with d["container"].session_factory() as s, s.begin():
        s.add(
            Report(
                incident_id=UUID(d["incident"]),
                house_id=d["ids"]["a1"],
                author_id=d["ids"]["dave"],
                category="water",
                description="foreign fixture",
                classification_mode="manual",
                provenance="api",
            )
        )
    await attempt(d)
    await deliver(d)
    assert {x[0] for x in d["provider"].sent} == {"101", "102"}
    foreign = next(r for r in await deliveries(d) if r.recipient_user_id == d["ids"]["dave"])
    assert foreign.status == "superseded"


async def test_retry_budget_five_calls_and_no_ticket_locks_across_network(nd):
    d = nd
    await attempt(d)
    await fanout(d)
    # Exercise one actual recipient. The other has lost access before any side effect.
    async with d["container"].session_factory() as s, s.begin():
        await s.execute(
            update(ResidentMembership)
            .where(
                ResidentMembership.user_id == d["ids"]["eve"],
            )
            .values(status="revoked")
        )
    calls = []

    async def rejected(destination, message):
        from domsignal.db.models import Incident

        async with d["container"].session_factory() as s, s.begin():
            await s.execute(
                select(Incident)
                .where(Incident.id == UUID(d["incident"]))
                .with_for_update(nowait=True)
            )
        calls.append(destination)
        raise MessagingError("MAX_RATE_LIMIT", kind="retry", retry_after=7)

    d["provider"].send_personal_message = rejected
    for i in range(16):
        await d["handler"].deliver_once(now=datetime.now(UTC) + timedelta(minutes=i))
    row = next(r for r in await deliveries(d) if r.recipient_user_id == d["ids"]["carol"])
    assert row.status == "failed" and row.attempt_count == 5 and row.next_attempt_at is None
    assert len(calls) == 5


async def test_nd15_late_unresolved_callback_reopens_same_ticket_and_reconciles(nd):
    d = nd
    aid = await attempt(d)
    await deliver(d)
    row = next(r for r in await deliveries(d) if r.recipient_user_id == d["ids"]["eve"])
    await observe(d, aid, "carol", "resolved")
    await deliver(d)
    assert (await read(d)).json()["status"] == "closed"
    await webhook(d, callback(row, outcome="unresolved", callback_id="late-objection"))
    await runner(d).run_once()
    view = (await read(d)).json()
    assert view["id"] == d["ticket"]["id"] and view["status"] == "in_progress"
    for i in range(6):
        await fanout(d)
        await d["handler"].deliver_once(now=datetime.now(UTC) + timedelta(minutes=7, seconds=i))
    assert len(d["provider"].sent) == 2
    assert all(len(message.buttons) == 1 for _, message in d["provider"].edited)
    assert "Проблема возвращена в работу" in d["provider"].edited[-1][1].text


async def test_access_recheck_after_claim_before_http(nd, monkeypatch):
    d = nd
    await attempt(d)
    await fanout(d)
    # Suppress outdated accepted intents first; isolate the claim/preflight boundary.
    for _ in range(2):
        await d["handler"].deliver_once()
    original = d["handler"]._snapshot
    calls = 0

    async def changed(session, delivery):
        nonlocal calls
        calls += 1
        if calls == 2:
            async with d["container"].session_factory() as s, s.begin():
                await s.execute(
                    update(ResidentMembership)
                    .where(
                        ResidentMembership.house_id == d["ids"]["a1"],
                    )
                    .values(status="revoked")
                )
        return await original(session, delivery)

    monkeypatch.setattr(d["handler"], "_snapshot", changed)
    await d["handler"].deliver_once()
    assert not d["provider"].sent
