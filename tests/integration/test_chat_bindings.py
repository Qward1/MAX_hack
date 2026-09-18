"""A-07 CB-01..CB-22 on real PostgreSQL and explicit deterministic MAX test double."""

import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from domsignal.bot.chat_provider import ChatMember
from domsignal.db.models import (
    ChatBinding,
    ConnectionRequest,
    House,
    HouseManagement,
    InboxReceipt,
    Incident,
    Job,
    ManagementCompany,
    MAXChat,
    OrganizationMembership,
    OutboxMessage,
    Report,
    ResidentMembership,
    User,
)
from domsignal.main import create_app
from domsignal.services.chat_connections import ChatConnectionError
from domsignal.services.management import ManagementService
from domsignal.worker.runner import WorkerRunner
from tests.fakes.max_chat import FakeMaxChatProvider


@dataclass
class Harness:
    client: AsyncClient
    container: object
    fake: FakeMaxChatProvider
    ids: dict
    headers: dict

    async def initiate(self, house="a1", actor="alice", scope=None):
        response = await self.client.post(
            f"/api/v1/houses/{self.ids[house]}/chat-connections",
            json=scope or {},
            headers=self.headers[actor],
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def webhook(self, kind, chat="-101", actor=101, **extra):
        value = {
            "update_type": kind,
            "timestamp": int(datetime.now(UTC).timestamp() * 1000) + 1,
            "chat_id": int(chat),
            "user": {"user_id": actor},
            **extra,
        }
        response = await self.client.post(
            "/max/webhook", json=value, headers={"X-Max-Bot-Api-Secret": "synthetic-webhook-secret"}
        )
        assert response.status_code == 200, response.text
        return response, value

    async def detect(self, request, chat="-101", connector=101):
        await self.webhook(
            "bot_started", chat="101", actor=connector, payload=request["correlation_token"]
        )
        await self.webhook("bot_added", chat=chat, actor=connector, is_channel=False)

    async def approve(self, request, actor="alice"):
        return await self.client.post(
            f"/api/v1/chat-connections/{request['id']}/approve",
            json={"confirm": True},
            headers=self.headers[actor],
        )

    async def bind(self, chat="-101", house="a1", actor="alice", connector=101, scope=None):
        self.fake.configure(chat, connector=str(connector))
        request = await self.initiate(house, actor, scope)
        await self.detect(request, chat, connector)
        response = await self.approve(request, actor)
        assert response.status_code == 200, response.text
        return request, response.json()

    async def message(self, chat="-101", actor=103, mid="m1", message="/report water Water leak"):
        return await self.webhook(
            "message_created",
            chat,
            actor,
            message={
                "sender": {"user_id": actor, "is_bot": False},
                "recipient": {"chat_id": int(chat), "chat_type": "chat"},
                "body": {"mid": mid, "text": message},
            },
        )

    async def drain(self):
        runner = WorkerRunner(
            session_factory=self.container.session_factory,
            handlers=self.container.worker_handlers.mapping,
        )
        for _ in range(20):
            if not await runner.run_once():
                break

    async def scalar(self, statement):
        async with self.container.session_factory() as session:
            return await session.scalar(statement)


@pytest_asyncio.fixture
async def cb(integration_settings):
    settings = integration_settings.model_copy(
        update={
            "max_transport": "webhook",
            "max_bot_token": "synthetic-initdata-token",
            "max_webhook_secret": "synthetic-webhook-secret",
        }
    )
    app = create_app(settings)
    container = app.state.container
    fake = FakeMaxChatProvider()
    container.chat_connections.provider = fake  # explicit test-only injection
    ids = {
        name: uuid4()
        for name in [
            "alpha",
            "beta",
            "a1",
            "b1",
            "ma1",
            "mb1",
            "alice",
            "bob",
            "resident",
            "outsider",
        ]
    }
    async with container.session_factory() as session, session.begin():
        for name in ["alpha", "beta"]:
            session.add(ManagementCompany(id=ids[name], name=name))
        for name in ["a1", "b1"]:
            session.add(House(id=ids[name], name=name, address=f"CB synthetic {name}"))
        for index, name in enumerate(["alice", "bob", "resident", "outsider"], 101):
            session.add(
                User(
                    id=ids[name], display_name=name, demo_alias=f"cb-{name}", max_user_id=str(index)
                )
            )
        await session.flush()
        for house, tenant in [("a1", "alpha"), ("b1", "beta")]:
            session.add(
                HouseManagement(
                    id=ids[f"m{house}"],
                    house_id=ids[house],
                    tenant_id=ids[tenant],
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                )
            )
            session.add(ResidentMembership(user_id=ids["resident"], house_id=ids[house]))
        for name, tenant in [("alice", "alpha"), ("bob", "beta")]:
            session.add(
                OrganizationMembership(
                    user_id=ids[name], tenant_id=ids[tenant], role="company_admin"
                )
            )
    headers = {}
    for name in ["alice", "bob", "resident", "outsider"]:
        async with container.session_factory() as session:
            auth = await container.session_service.issue_test_session(session, alias=f"cb-{name}")
        headers[name] = {"Authorization": "Bearer " + auth.access_token}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Harness(client, container, fake, ids, headers)
    await container.engine.dispose()


async def test_cb01_existing_chat_binds_with_explicit_confirmation(cb):
    request, binding = await cb.bind()
    assert binding["house_id"] == str(cb.ids["a1"]) and binding["binding_version"] == 1
    assert binding["status"] == "active"
    row = await cb.scalar(
        select(ConnectionRequest).where(ConnectionRequest.id == UUID(request["id"]))
    )
    assert row.status == "completed" and row.connector_max_user_id == "101"
    assert row.token_hash != request["correlation_token"] and len(row.token_hash) == 64
    assert row.verified_at and row.completed_at
    assert len(cb.fake.calls) == 3


async def test_cb02_unbound_message_never_enters_core_or_retains_text(cb):
    await cb.message()
    await cb.drain()
    assert await cb.scalar(select(func.count()).select_from(Job)) == 0
    assert (
        await cb.scalar(
            select(func.count()).select_from(Report).where(Report.provenance == "max_group")
        )
        == 0
    )
    receipt = await cb.scalar(
        select(InboxReceipt).where(InboxReceipt.event_type == "message_created")
    )
    assert receipt.payload == {"chat_id": "-101"}
    assert cb.fake.calls == []


async def test_cb03_same_message_different_house_results(cb):
    await cb.bind()
    await cb.bind("-102", "b1", "bob", 102)
    await cb.message("-101")
    await cb.message("-102")  # same mid/text/user, distinct chat event identity
    await cb.drain()
    async with cb.container.session_factory() as session:
        rows = (
            await session.execute(
                select(Incident.management_id, Incident.house_id)
                .join(Report)
                .where(Report.provenance == "max_group")
            )
        ).all()
    assert set(rows) == {(cb.ids["ma1"], cb.ids["a1"]), (cb.ids["mb1"], cb.ids["b1"])}


async def test_cb04_alpha_chat_never_resolves_beta(cb):
    _, binding = await cb.bind()
    await cb.message(actor=102)
    await cb.drain()
    assert (
        await cb.scalar(
            select(func.count()).select_from(Report).where(Report.provenance == "max_group")
        )
        == 0
    )
    async with cb.container.session_factory() as session, session.begin():
        context = await cb.container.chat_connections.resolve_context(
            session,
            actor_id=cb.ids["resident"],
            chat_id="-101",
            binding_id=UUID(binding["id"]),
            version=1,
            occurred_at=datetime.now(UTC),
        )
        assert context.tenant_id.value == cb.ids["alpha"]


async def test_cb05_connector_must_still_be_admin_at_approval(cb):
    cb.fake.configure("-101")
    request = await cb.initiate()
    await cb.detect(request)
    await cb.drain()
    cb.fake.admins["-101"] = (ChatMember("101", False),)
    response = await cb.approve(request)
    assert response.status_code == 409 and response.json()["code"] == "connector_not_chat_admin"
    assert await cb.scalar(select(func.count()).select_from(ChatBinding)) == 0


@pytest.mark.parametrize("admin,permissions", [(False, {"read_all_messages"}), (True, set())])
async def test_cb06_required_bot_permissions(cb, admin, permissions):
    cb.fake.configure("-101")
    cb.fake.bots["-101"] = replace(
        cb.fake.bots["-101"], is_admin=admin, permissions=frozenset(permissions)
    )
    request = await cb.initiate()
    await cb.detect(request)
    response = await cb.approve(request)
    assert response.json()["code"] == "bot_permission_missing"


async def test_cb07_expired_cannot_activate(cb):
    cb.fake.configure("-101")
    request = await cb.initiate()
    await cb.detect(request)
    async with cb.container.session_factory() as session, session.begin():
        await session.execute(
            update(ConnectionRequest).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (await cb.approve(request)).json()["code"] == "connection_expired"
    assert (await cb.scalar(select(ConnectionRequest))).status == "expired"


async def test_cb08_duplicate_bot_added_idempotent(cb):
    cb.fake.configure("-101")
    request = await cb.initiate()
    await cb.detect(request)
    await cb.webhook("bot_added", is_channel=False)
    await cb.drain()
    assert await cb.scalar(select(func.count()).select_from(MAXChat)) == 1
    assert await cb.scalar(select(func.count()).select_from(ConnectionRequest)) == 1
    assert await cb.scalar(select(func.count()).select_from(Job)) == 1
    assert await cb.scalar(select(func.count()).select_from(ChatBinding)) == 0


async def test_cb09_chat_cannot_bind_two_houses(cb):
    await cb.bind()
    cb.fake.admins["-101"] = (ChatMember("102", True),)
    request = await cb.initiate("b1", "bob")
    await cb.detect(request, connector=102)
    response = await cb.approve(request, "bob")
    assert response.status_code == 409 and response.json()["code"] == "chat_already_bound"
    assert "alpha" not in response.text and str(cb.ids["a1"]) not in response.text


async def test_cb10_house_has_multiple_chats(cb):
    await cb.bind()
    await cb.bind("-102")
    assert (
        await cb.scalar(
            select(func.count()).select_from(ChatBinding).where(ChatBinding.status == "active")
        )
        == 2
    )


async def test_cb11_removed_suspends_idempotently_and_retains_history(cb):
    await cb.bind()
    await cb.webhook("bot_removed")
    await cb.webhook("bot_removed")
    binding = await cb.scalar(select(ChatBinding))
    assert binding.status == "suspended" and binding.suspension_reason == "BOT_REMOVED"
    assert not (await cb.scalar(select(MAXChat))).bot_present
    assert (await cb.scalar(select(ConnectionRequest))).status == "completed"
    assert (
        await cb.scalar(
            select(func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.kind == "chat_binding.suspended")
        )
        == 1
    )


@pytest.mark.parametrize("cause", ["permission", "admin", "max_chat_not_found", "timeout"])
async def test_cb12_health_permission_or_access_loss(cb, cause):
    _, binding = await cb.bind()
    if cause == "permission":
        cb.fake.bots["-101"] = replace(cb.fake.bots["-101"], permissions=frozenset())
    elif cause == "admin":
        cb.fake.bots["-101"] = replace(cb.fake.bots["-101"], is_admin=False)
    else:
        cb.fake.failures["-101"] = cause
    await cb.container.worker_handlers.verify_binding_health({"chat_binding_id": binding["id"]})
    assert (await cb.scalar(select(ChatBinding))).status == "suspended"


async def test_cb13_management_switch_suspends_without_transfer(cb):
    await cb.bind()
    await cb.message()
    async with cb.container.session_factory() as session, session.begin():
        await ManagementService().switch(
            session, management_id=cb.ids["ma1"], tenant_id=cb.ids["beta"], at=datetime.now(UTC)
        )
    await cb.drain()
    binding = await cb.scalar(select(ChatBinding))
    assert binding.status == "suspended" and binding.suspension_reason == "MANAGEMENT_ENDED"
    assert binding.management_id == cb.ids["ma1"]
    assert (
        await cb.scalar(
            select(func.count()).select_from(Report).where(Report.provenance == "max_group")
        )
        == 0
    )


async def test_cb14_stale_job_after_revoke_and_rebind(cb):
    _, old = await cb.bind()
    await cb.message()
    async with cb.container.session_factory() as session, session.begin():
        await cb.container.chat_connections.revoke(
            session, binding_id=UUID(old["id"]), actor_id=cb.ids["alice"]
        )
    _, new = await cb.bind()
    assert new["binding_version"] == 2 and new["id"] != old["id"]
    await cb.drain()
    assert (
        await cb.scalar(
            select(func.count()).select_from(Report).where(Report.provenance == "max_group")
        )
        == 0
    )
    async with cb.container.session_factory() as session, session.begin():
        with pytest.raises(ChatConnectionError, match="Chat connection") as error:
            await cb.container.chat_connections.resolve_context(
                session,
                actor_id=cb.ids["resident"],
                chat_id="-101",
                binding_id=UUID(new["id"]),
                version=1,
                occurred_at=datetime.now(UTC),
            )
        assert error.value.code == "stale_binding_version"


async def test_cb15_signed_miniapp_chat_and_start_do_not_grant_access(cb):
    await cb.bind()
    values = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "chat": json.dumps({"id": -101}),
        "start_param": str(cb.ids["a1"]),
        "user": json.dumps({"id": 104, "first_name": "outsider"}),
    }
    secret = hmac.new(b"WebAppData", b"synthetic-initdata-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256
    ).hexdigest()
    auth = await cb.client.post("/api/v1/auth/max", json={"init_data": urlencode(values)})
    assert auth.status_code == 200
    headers = {"Authorization": "Bearer " + auth.json()["access_token"]}
    response = await cb.client.get(f"/api/v1/houses/{cb.ids['a1']}/incidents", headers=headers)
    assert response.status_code == 404
    assert (await cb.client.get("/api/v1/me", headers=headers)).json()["houses"] == []


async def test_cb16_chat_title_changes_only_snapshot(cb):
    _, binding = await cb.bind()
    cb.fake.chats["-101"] = replace(cb.fake.chats["-101"], title="Beta unrelated address")
    await cb.container.worker_handlers.verify_binding_health({"chat_binding_id": binding["id"]})
    assert (await cb.scalar(select(MAXChat))).title == "Beta unrelated address"
    assert (await cb.scalar(select(ChatBinding))).management_id == cb.ids["ma1"]


async def test_cb17_concurrent_duplicate_delivery_has_one_effect(cb):
    await cb.bind()
    _, value = await cb.message()
    replies = await asyncio.gather(
        *[
            cb.client.post(
                "/max/webhook",
                json=value,
                headers={"X-Max-Bot-Api-Secret": "synthetic-webhook-secret"},
            )
            for _ in range(4)
        ]
    )
    assert all(reply.status_code == 200 and reply.json()["duplicate"] for reply in replies)
    await cb.drain()
    assert (
        await cb.scalar(
            select(func.count()).select_from(Report).where(Report.provenance == "max_group")
        )
        == 1
    )


@pytest.mark.parametrize("failure", ["timeout", "429", "5xx"])
async def test_cb18_max_temporary_failure_is_pending_with_durable_retry(cb, failure):
    cb.fake.configure("-101")
    cb.fake.failures["-101"] = failure
    request = await cb.initiate()
    await cb.detect(request)
    await cb.drain()
    row = await cb.scalar(select(ConnectionRequest))
    assert row.status == "chat_detected" and row.verified_at is None
    job = await cb.scalar(select(Job))
    assert job.status == "pending" and job.attempts == 1
    response = await cb.approve(request)
    assert response.status_code == 503 and response.json()["retryable"]
    assert await cb.scalar(select(func.count()).select_from(ChatBinding)) == 0


async def test_cb19_token_not_authority_and_cannot_be_stolen(cb):
    request = await cb.initiate()
    await cb.webhook("bot_started", payload=request["correlation_token"])
    await cb.webhook("bot_started", actor=102, payload=request["correlation_token"])
    response = await cb.approve(request)
    assert response.status_code == 409
    row = await cb.scalar(select(ConnectionRequest))
    assert row.status == "connector_claimed" and row.connector_max_user_id == "101"
    response = await cb.approve(request, "bob")
    assert response.status_code == 404


async def test_cb20_concurrent_approvals_one_binding(cb):
    cb.fake.configure("-101")
    request = await cb.initiate()
    await cb.detect(request)
    responses = await asyncio.gather(*[cb.approve(request) for _ in range(5)])
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["id"] for response in responses}) == 1
    assert await cb.scalar(select(func.count()).select_from(ChatBinding)) == 1


async def test_cb21_external_connector_requires_target_company_approval(cb):
    cb.fake.configure("-101", connector="102")
    request = await cb.initiate()
    await cb.detect(request, connector=102)
    await cb.drain()
    assert (await cb.scalar(select(ConnectionRequest))).status == "awaiting_approval"
    assert (await cb.approve(request, "bob")).status_code == 404
    assert (await cb.approve(request)).status_code == 200


async def test_cb22_entrance_context_preserves_house(cb):
    _, binding = await cb.bind(scope={"scope_type": "entrance", "scope_value": "2"})
    async with cb.container.session_factory() as session, session.begin():
        context = await cb.container.chat_connections.resolve_context(
            session,
            actor_id=cb.ids["resident"],
            chat_id="-101",
            binding_id=UUID(binding["id"]),
            version=1,
            occurred_at=datetime.now(UTC),
        )
        assert context.entrance == "2" and context.house_id == cb.ids["a1"]
    await cb.message(message="/report water Text says entrance 3, no automatic rebinding")
    await cb.drain()
    binding_row = await cb.scalar(select(ChatBinding))
    assert binding_row.scope_value == "2"
    outbox = await cb.scalar(
        select(OutboxMessage).where(
            OutboxMessage.kind == "incident.created",
            OutboxMessage.payload["chat_binding_id"].astext == binding["id"],
        )
    )
    assert outbox.payload["entrance"] == "2"


async def test_repeated_initiation_claim_cancel_and_reject(cb):
    request = await cb.initiate()
    repeated = await cb.initiate()
    assert repeated["id"] == request["id"] and repeated["correlation_token"] is None
    for _ in range(2):
        await cb.webhook("bot_started", payload=request["correlation_token"])
    assert (await cb.scalar(select(ConnectionRequest))).status == "connector_claimed"
    for _ in range(2):
        response = await cb.client.post(
            f"/api/v1/chat-connections/{request['id']}/cancel", headers=cb.headers["alice"]
        )
        assert response.status_code == 200 and response.json()["status"] == "cancelled"
    new = await cb.initiate()
    assert new["id"] != request["id"]
    response = await cb.client.post(
        f"/api/v1/chat-connections/{new['id']}/reject", headers=cb.headers["alice"]
    )
    assert response.json()["status"] == "rejected"
    assert (await cb.approve(new)).status_code == 409


async def test_webhook_secret_payload_and_secrets_not_persisted(cb):
    request = await cb.initiate()
    denied = await cb.client.post("/max/webhook", json={"update_type": "bot_added"})
    assert denied.status_code == 401
    assert await cb.scalar(select(func.count()).select_from(InboxReceipt)) == 0
    invalid = await cb.client.post(
        "/max/webhook",
        json={"update_type": "bot_added"},
        headers={"X-Max-Bot-Api-Secret": "synthetic-webhook-secret"},
    )
    assert invalid.status_code == 422 and invalid.json()["code"] == "invalid_max_update"
    await cb.detect(request)
    async with cb.container.session_factory() as session:
        rows = await session.scalars(select(InboxReceipt.payload))
        assert all(request["correlation_token"] not in json.dumps(row) for row in rows)


async def test_client_authority_and_unauthorized_init_are_rejected(cb):
    response = await cb.client.post(
        f"/api/v1/houses/{cb.ids['a1']}/chat-connections", json={}, headers=cb.headers["resident"]
    )
    assert response.status_code == 403
    for extras in [
        {"tenant_id": str(cb.ids["alpha"])},
        {"house_id": str(cb.ids["b1"])},
        {"chat_id": "-101"},
        {"role": "company_admin"},
    ]:
        response = await cb.client.post(
            f"/api/v1/houses/{cb.ids['a1']}/chat-connections",
            json=extras,
            headers=cb.headers["alice"],
        )
        assert response.status_code == 422
    request = await cb.initiate()
    response = await cb.client.post(
        f"/api/v1/chat-connections/{request['id']}/approve",
        json={"confirm": False},
        headers=cb.headers["alice"],
    )
    assert response.status_code == 422


async def test_two_houses_concurrent_approval_and_db_constraints(cb):
    cb.fake.configure("-101")
    cb.fake.admins["-101"] = (ChatMember("101", True), ChatMember("102", True))
    first = await cb.initiate()
    second = await cb.initiate("b1", "bob")
    await cb.detect(first)
    await cb.detect(second, connector=102)
    responses = await asyncio.gather(cb.approve(first), cb.approve(second, "bob"))
    assert sorted(response.status_code for response in responses) == [200, 409]
    async with cb.container.session_factory() as session, session.begin():
        binding = await session.scalar(select(ChatBinding))
        assert binding is not None
        other = second if str(binding.connection_request_id) == first["id"] else first
        # A second, consistent active binding is independently forbidden by PostgreSQL.
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    ChatBinding(
                        max_chat_id="-101",
                        connection_request_id=UUID(other["id"]),
                        house_id=binding.house_id,
                        management_id=binding.management_id,
                        scope_type="house",
                        status="active",
                        binding_version=2,
                    )
                )
                await session.flush()
        # Mismatched physical house and management are rejected even for pending rows.
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    ChatBinding(
                        max_chat_id="-101",
                        connection_request_id=UUID(other["id"]),
                        house_id=cb.ids["a1"],
                        management_id=cb.ids["mb1"],
                        scope_type="house",
                        status="pending",
                        binding_version=2,
                    )
                )
                await session.flush()
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.execute(update(ChatBinding).values(binding_version=99))


@pytest.mark.parametrize("change", ["tenant", "resident", "organization", "natural_expiry"])
async def test_fresh_access_before_effect_and_approval(cb, change):
    request, _ = await cb.bind()
    await cb.message()
    async with cb.container.session_factory() as session, session.begin():
        if change == "tenant":
            await session.execute(
                update(ManagementCompany)
                .where(ManagementCompany.id == cb.ids["alpha"])
                .values(status="suspended")
            )
        elif change == "resident":
            await session.execute(
                update(ResidentMembership)
                .where(ResidentMembership.user_id == cb.ids["resident"])
                .values(status="revoked")
            )
        elif change == "organization":
            await session.execute(
                update(OrganizationMembership)
                .where(OrganizationMembership.user_id == cb.ids["alice"])
                .values(status="revoked")
            )
        else:
            # An end reached without another update is detected by health/context resolution.
            await session.execute(
                text("UPDATE house_managements SET valid_to=clock_timestamp() WHERE id=:id"),
                {"id": cb.ids["ma1"]},
            )
    await cb.drain()
    if change != "organization":
        assert (
            await cb.scalar(
                select(func.count()).select_from(Report).where(Report.provenance == "max_group")
            )
            == 0
        )
    else:
        assert (await cb.approve(request)).status_code == 404


async def test_channels_and_unrelated_or_stale_added_do_not_activate(cb):
    await cb.webhook("bot_added", is_channel=False)
    assert await cb.scalar(select(func.count()).select_from(ConnectionRequest)) == 0
    request = await cb.initiate()
    await cb.webhook("bot_started", payload=request["correlation_token"])
    await cb.webhook("bot_added", chat="-103", is_channel=True)
    assert (await cb.scalar(select(ConnectionRequest))).status == "connector_claimed"
    await cb.webhook("bot_added", actor=102, chat="-104", is_channel=False)
    assert (await cb.scalar(select(ConnectionRequest))).candidate_max_chat_id is None


async def test_delayed_message_cannot_acquire_new_binding(cb):
    _, binding = await cb.bind()
    row = await cb.scalar(select(ChatBinding))
    await cb.webhook(
        "message_created",
        timestamp=int((row.activated_at - timedelta(seconds=1)).timestamp() * 1000),
        message={
            "sender": {"user_id": 103},
            "recipient": {"chat_id": -101, "chat_type": "chat"},
            "body": {"mid": "old", "text": "/report water Delayed old message"},
        },
    )
    await cb.drain()
    assert (
        await cb.scalar(
            select(func.count()).select_from(Report).where(Report.provenance == "max_group")
        )
        == 0
    )
    assert binding["binding_version"] == 1
