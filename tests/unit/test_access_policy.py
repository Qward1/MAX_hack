from uuid import uuid4

import pytest

from domsignal.core.access import AccessPolicy
from domsignal.services.context import OperationContext
from domsignal.services.errors import AccessDenied
from domsignal.services.membership import MembershipService


@pytest.mark.parametrize(
    "org,assignment,resident,allowed",
    [
        ("company_admin", None, False, True),
        ("operator", "responsible", False, True),
        ("operator", "operator", False, True),
        ("operator", None, False, False),
        (None, "responsible", False, False),
        (None, None, True, True),
        ("superadmin", None, False, False),
        ("operator", None, True, True),
    ],
)
def test_policy(org: str | None, assignment: str | None, resident: bool, allowed: bool) -> None:
    permissions = AccessPolicy.permissions(
        organization_role=org,
        assignment_role=assignment,
        resident=resident,
    )
    assert ("incident.read" in permissions) is allowed
    employee = org == "company_admin" or (
        org == "operator" and assignment in {"responsible", "operator"}
    )
    assert ("ticket.read" in permissions) is employee
    assert ("ticket.work" in permissions) is employee
    assert ("work.observe" in permissions) is resident
    # D3: объявления и опросы — администратор УК и ответственный за дом.
    manager = org == "company_admin" or (org == "operator" and assignment == "responsible")
    assert ("broadcast.send" in permissions) is manager
    assert not permissions & {"admin", "support.impersonate"}


def test_known_scope_without_action_permission_is_403() -> None:
    context = OperationContext(
        actor_user_id=uuid4(),
        house_id=uuid4(),
        source="api",
        roles=frozenset({"resident"}),
        permissions=frozenset({"incident.read"}),
    )
    with pytest.raises(AccessDenied) as failure:
        MembershipService.require_permission(context, "ticket.read")
    assert failure.value.status == 403
