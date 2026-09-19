"""Operator CLI tests on isolated PG; synthetic provider/events are never live evidence."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.db.models import AppSession, ChatBinding, InboxReceipt, User
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.chat_connections import ChatConnectionError, ChatConnectionService
from domsignal.services.errors import ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.settings import Settings
from domsignal.tools.live_connection import CONNECTION_AUDIT, operate
from domsignal.tools.live_fixture import operate as fixture_operate
from tests.fakes.max_chat import FakeMaxChatProvider


async def test_operator_connection_requires_correlated_events_and_fresh_rights(
    integration_settings: Settings,
) -> None:
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    fake = FakeMaxChatProvider()
    fake.configure("-480", connector="101")
    connections = ChatConnectionService(fake)
    uid = uuid4()
    args = dict(chat_id="-480", operator="pytest", reason="isolated deterministic test")
    fixture_args = dict(user_id=uid, operator="pytest", reason="isolated deterministic test")
    async with factory() as s, s.begin():
        s.add(
            User(
                id=uid,
                display_name="Synthetic",
                max_user_id="101",
                max_identity_verified_at=datetime.now(UTC),
            )
        )
        await s.flush()
        fixture = await fixture_operate(s, action="create", **fixture_args)
        with pytest.raises(ValueError, match="persisted bot_added"):
            await operate(s, connections, action="prepare", **args)
        s.add(
            InboxReceipt(
                event_id="synthetic-added", event_type="bot_added", payload={"chat_id": "-480"}
            )
        )
        await connections.bot_added(
            s, chat_id="-480", actor="101", occurred_at=datetime.now(UTC), is_channel=False
        )
        prepared = await operate(s, connections, action="prepare", **args)
        assert (await operate(s, connections, action="prepare", **args))["launch_url"] is None
        assert await s.scalar(select(func.count()).select_from(ChatBinding)) == 0
        staff = await s.get(User, UUID(prepared["operator_user_id"]))
        assert staff and staff.max_user_id is None and staff.platform_role is None
        assert (
            await s.scalar(
                select(func.count()).select_from(AppSession).where(AppSession.user_id == staff.id)
            )
            == 0
        )
        for actor, role in ((uid, "resident"), (staff.id, "admin")):
            me = await MembershipService().me(
                s, user_id=actor, capabilities=CapabilityFlags(test_auth=False)
            )
            assert [(str(h.id), h.role) for h in me.houses] == [(fixture["house_id"], role)]
            with pytest.raises(ResourceNotFound):
                await MembershipService().require_house(s, user_id=actor, house_id=uuid4())
        with pytest.raises(ValueError, match="--confirm"):
            await operate(s, connections, action="approve", **args)
        with pytest.raises(ValueError, match="correlated"):
            await operate(s, connections, action="approve", confirm=True, **args)
        token = parse_qs(urlparse(prepared["launch_url"]).query)["start"][0]
        audit = await s.get(InboxReceipt, CONNECTION_AUDIT)
        assert audit and token not in str(audit.payload)
    async with factory() as s, s.begin():
        await connections.claim(s, token=token, connector="101", occurred_at=datetime.now(UTC))
        await connections.bot_added(
            s, chat_id="-480", actor="101", occurred_at=datetime.now(UTC), is_channel=False
        )
    fake.failures["-480"] = "bot_permission_missing"
    async with factory() as s, s.begin():
        with pytest.raises(ChatConnectionError):
            await operate(s, connections, action="approve", confirm=True, **args)
        assert await s.scalar(select(func.count()).select_from(ChatBinding)) == 0
    fake.failures.clear()
    async with factory() as s, s.begin():
        result = await operate(s, connections, action="approve", confirm=True, **args)
        assert result["status"] == "active" and result["version"] == 1
        binding = await s.get(ChatBinding, UUID(result["binding_id"]))
        assert binding and str(binding.management_id) == fixture["management_id"]
        await fixture_operate(s, action="revoke", **fixture_args)
        await s.refresh(binding)
        assert binding.status == "suspended"
        me = await MembershipService().me(
            s, user_id=staff.id, capabilities=CapabilityFlags(test_auth=False)
        )
        assert me.houses == []
    await engine.dispose()
