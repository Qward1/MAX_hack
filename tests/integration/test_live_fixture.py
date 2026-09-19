"""Deterministic isolated PG evidence only; these identities are never live evidence."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.db.models import (
    House,
    InboxReceipt,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.errors import ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.settings import Settings
from domsignal.tools.live_fixture import AUDIT_KEY, operate


async def test_fixture_is_explicit_scoped_idempotent_and_deletable(
    integration_settings: Settings,
) -> None:
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    user_id = uuid4()
    async with factory() as s, s.begin():
        s.add(
            User(
                id=user_id,
                display_name="Synthetic test",
                max_user_id="fixture-test",
                max_identity_verified_at=datetime.now(UTC),
            )
        )
    args = dict(user_id=user_id, operator="pytest", reason="deterministic test")
    async with factory() as s, s.begin():
        result = await operate(s, action="create", **args)
        assert await operate(s, action="create", **args) == result
        me = await MembershipService().me(
            s, user_id=user_id, capabilities=CapabilityFlags(test_auth=False)
        )
        assert [str(h.id) for h in me.houses] == [result["house_id"]]
        assert me.houses[0].role == "resident" and not me.houses[0].is_demo
        assert not await s.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(OrganizationMembership.user_id == user_id)
        )
        with pytest.raises(ResourceNotFound):
            await MembershipService().require_house(s, user_id=user_id, house_id=uuid4())
    async with factory() as s, s.begin():
        await operate(s, action="revoke", **args)
        me = await MembershipService().me(
            s, user_id=user_id, capabilities=CapabilityFlags(test_auth=False)
        )
        assert me.houses == []
        with pytest.raises(ValueError, match="retired"):
            await operate(s, action="create", **args)
    async with factory() as s, s.begin():
        assert (await operate(s, action="delete-empty", **args))["status"] == "deleted"
        assert await s.get(House, UUID(result["house_id"])) is None
        assert await s.get(User, user_id) is not None
        audit = await s.get(InboxReceipt, AUDIT_KEY)
        assert audit and audit.event_type == "operator.live_fixture"
        assert len(audit.payload["history"]) == 3
    await engine.dispose()


async def test_fixture_refuses_unvalidated_user_or_another_owner_and_dependent_data(
    integration_settings: Settings,
) -> None:
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    user_id, other = uuid4(), uuid4()
    async with factory() as s, s.begin():
        s.add_all(
            [
                User(id=user_id, display_name="Unvalidated", max_user_id="unvalidated"),
                User(id=other, display_name="Other"),
            ]
        )
    args = dict(user_id=user_id, operator="pytest", reason="deterministic test")
    async with factory() as s, s.begin():
        with pytest.raises(ValueError, match="validated"):
            await operate(s, action="create", **args)
        assert await s.get(InboxReceipt, AUDIT_KEY) is None
        user = await s.get(User, user_id)
        assert user
        user.max_identity_verified_at = datetime.now(UTC)
        await s.flush()
        result = await operate(s, action="create", **args)
        with pytest.raises(ValueError, match="another user"):
            await operate(s, action="create", **{**args, "user_id": other})
        s.add(ResidentMembership(user_id=other, house_id=UUID(result["house_id"])))
    async with factory() as s, s.begin():
        with pytest.raises(ValueError, match="dependent data"):
            await operate(s, action="delete-empty", **args)
        assert await s.get(House, UUID(result["house_id"])) is not None
    await engine.dispose()
