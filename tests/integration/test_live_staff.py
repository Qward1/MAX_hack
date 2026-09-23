"""P7a: операторская выдача роли сотрудника MAX-аккаунту — только в live-стенде.

Детерминированные синтетические идентичности PostgreSQL; не живое доказательство.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from domsignal.bootstrap import build_container
from domsignal.db.models import HouseAssignment, InboxReceipt, OrganizationMembership, User
from domsignal.services.errors import ResourceNotFound
from domsignal.services.membership import MembershipService
from domsignal.settings import Settings
from domsignal.tools import live_fixture, live_staff

ARGS = dict(operator="pytest", reason="deterministic test")


def _max_user(user_id: UUID, *, validated: bool = True) -> User:
    return User(
        id=user_id,
        display_name="Synthetic MAX user",
        max_user_id=f"staff-{user_id}",
        max_identity_verified_at=datetime.now(UTC) if validated else None,
    )


async def test_staff_grant_is_scoped_audited_and_revocable(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    factory = container.session_factory
    resident, staff, other = uuid4(), uuid4(), uuid4()
    try:
        async with factory() as s, s.begin():
            s.add_all([_max_user(resident), _max_user(staff), _max_user(other)])
        # Без активного стенда выдачи нет.
        async with factory() as s, s.begin():
            with pytest.raises(ValueError, match="live fixture"):
                await live_staff.operate(s, action="grant", user_id=staff, **ARGS)
        async with factory() as s, s.begin():
            fixture = await live_fixture.operate(s, action="create", user_id=resident, **ARGS)
        house_id = UUID(fixture["house_id"])
        async with factory() as s, s.begin():
            with pytest.raises(ValueError, match="stays a resident"):
                await live_staff.operate(s, action="grant", user_id=resident, **ARGS)
        async with factory() as s, s.begin():
            granted = await live_staff.operate(s, action="grant", user_id=staff, **ARGS)
            assert granted["role"] == "operator" and granted["status"] == "active"
            assert granted["tenant_id"] == fixture["tenant_id"]
            # Повтор для того же человека — та же выдача, без второй записи.
            again = await live_staff.operate(s, action="grant", user_id=staff, **ARGS)
            assert again["membership_id"] == granted["membership_id"]
            with pytest.raises(ValueError, match="another user"):
                await live_staff.operate(s, action="grant", user_id=other, **ARGS)
        async with factory() as s, s.begin():
            context = await MembershipService().require_house(s, user_id=staff, house_id=house_id)
            assert context.organization_role == "operator"
            assert {"ticket.read", "ticket.work"} <= context.permissions
            assert "chat.connect" not in context.permissions
            assert "ticket.manage" not in context.permissions
            # Оповещение об опасности теперь есть кому доставить лично.
            recipients = await container.notifications._staff_recipients(s, house_id)
            assert [user.id for user in recipients] == [staff]
        async with factory() as s, s.begin():
            revoked = await live_staff.operate(s, action="revoke", user_id=staff, **ARGS)
            assert revoked["status"] == "revoked"
            assert [entry["action"] for entry in revoked["history"]] == ["grant", "revoke"]
            grant = await s.get(OrganizationMembership, UUID(granted["membership_id"]))
            assignment = await s.get(HouseAssignment, UUID(granted["assignment_id"]))
            assert grant is not None and grant.status == "revoked"
            assert assignment is not None and assignment.status == "revoked"
            audit = await s.get(InboxReceipt, live_staff.STAFF_AUDIT)
            assert audit is not None and audit.event_type == "operator.live_staff"
        async with factory() as s, s.begin():
            with pytest.raises(ResourceNotFound):
                await MembershipService().require_house(s, user_id=staff, house_id=house_id)
            assert await container.notifications._staff_recipients(s, house_id) == []
            with pytest.raises(ValueError, match="silently recreated"):
                await live_staff.operate(s, action="grant", user_id=staff, **ARGS)
    finally:
        await container.engine.dispose()


async def test_staff_grant_needs_a_validated_max_user_without_other_grants(
    integration_settings: Settings,
) -> None:
    container = build_container(integration_settings)
    factory = container.session_factory
    resident, unvalidated, employee = uuid4(), uuid4(), uuid4()
    try:
        async with factory() as s, s.begin():
            s.add_all(
                [
                    _max_user(resident),
                    _max_user(unvalidated, validated=False),
                    _max_user(employee),
                ]
            )
        async with factory() as s, s.begin():
            fixture = await live_fixture.operate(s, action="create", user_id=resident, **ARGS)
            s.add(
                OrganizationMembership(
                    user_id=employee, tenant_id=UUID(fixture["tenant_id"]), role="company_admin"
                )
            )
        for user_id, message in ((unvalidated, "validated"), (employee, "already has")):
            async with factory() as s, s.begin():
                with pytest.raises(ValueError, match=message):
                    await live_staff.operate(s, action="grant", user_id=user_id, **ARGS)
                assert await s.get(InboxReceipt, live_staff.STAFF_AUDIT) is None
        for operator, reason in (("", "reason"), ("pytest", " ")):
            async with factory() as s, s.begin():
                with pytest.raises(ValueError, match="bounded operator"):
                    await live_staff.operate(
                        s, action="grant", user_id=resident, operator=operator, reason=reason
                    )
    finally:
        await container.engine.dispose()
