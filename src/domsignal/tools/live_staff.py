"""Сотрудник тестовой УК с отображением в MAX — только для live-стенда.

Продукт не связывает веб-сотрудника с MAX-аккаунтом, поэтому оповещение об
опасности в production некому доставить лично. Эта операторская команда
выдаёт роль `operator` в УК активного аудированного стенда (`live_fixture`) и
назначение `operator` на его дом одному MAX-аккаунту, уже прошедшему
проверенный вход через mini app. Права — только `ticket.read`/`ticket.work`
этого дома: ни подключения чатов, ни управления заявками, ни платформенной
роли. Одна выдача на базу; `revoke` снимает обе записи, история остаётся.

    python -m domsignal.tools.live_staff grant --user-id <uuid> --operator <имя> --reason <текст>
    python -m domsignal.tools.live_staff revoke --user-id <uuid> --operator <имя> --reason <текст>
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bootstrap import build_container
from domsignal.db.models import (
    HouseAssignment,
    HouseManagement,
    InboxReceipt,
    OrganizationMembership,
    User,
)
from domsignal.settings import AppEnvironment, Settings
from domsignal.tools.live_fixture import AUDIT_KEY as FIXTURE_KEY

STAFF_AUDIT = "operator:live-smoke-staff:v1"
STAFF_ROLE = "operator"


async def operate(
    session: AsyncSession, *, action: str, user_id: UUID, operator: str, reason: str
) -> dict[str, Any]:
    """Транзакцией владеет вызывающий. Квитанция — операторская, не событие MAX."""
    if action not in {"grant", "revoke"}:
        raise ValueError("Unsupported staff action")
    if not operator.strip() or not reason.strip() or max(len(operator), len(reason)) > 300:
        raise ValueError("A bounded operator and authorization reason are required")
    await session.execute(text("SELECT pg_advisory_xact_lock(48020260919)"))
    fixture = await session.get(InboxReceipt, FIXTURE_KEY)
    if fixture is None or fixture.payload.get("status") != "active":
        raise ValueError("An active audited live fixture is required")
    scope = fixture.payload
    audit = await session.get(InboxReceipt, STAFF_AUDIT)
    if audit is not None and audit.payload["user_id"] != str(user_id):
        raise ValueError("The singleton staff grant belongs to another user")
    now = datetime.now(UTC)
    if action == "grant":
        if audit is not None:
            if audit.payload["status"] != "active":
                raise ValueError("A revoked staff grant cannot be silently recreated")
            return dict(audit.payload)
        user = await session.get(User, user_id)
        if (
            user is None
            or not user.max_user_id
            or user.max_identity_verified_at is None
            or user.demo_alias is not None
            or user.platform_role is not None
        ):
            raise ValueError("An existing validated non-demo MAX user is required")
        if str(user.id) == scope["user_id"]:
            raise ValueError("The live-test resident stays a resident")
        if await session.scalar(
            select(OrganizationMembership.id).where(OrganizationMembership.user_id == user.id)
        ):
            raise ValueError("The user already has an organization membership")
        management = await session.get(HouseManagement, UUID(scope["management_id"]))
        if (
            management is None
            or management.status != "active"
            or str(management.house_id) != scope["house_id"]
            or str(management.tenant_id) != scope["tenant_id"]
        ):
            raise ValueError("Fixture management mismatch; manual investigation required")
        grant = OrganizationMembership(
            user_id=user.id, tenant_id=management.tenant_id, role=STAFF_ROLE
        )
        assignment = HouseAssignment(user_id=user.id, management_id=management.id, role=STAFF_ROLE)
        session.add_all([grant, assignment])
        await session.flush()
        payload: dict[str, Any] = dict(
            user_id=str(user.id),
            house_id=scope["house_id"],
            tenant_id=scope["tenant_id"],
            management_id=scope["management_id"],
            membership_id=str(grant.id),
            assignment_id=str(assignment.id),
            role=STAFF_ROLE,
            status="active",
            history=[],
        )
        audit = InboxReceipt(event_id=STAFF_AUDIT, event_type="operator.live_staff", payload={})
        session.add(audit)
    else:
        if audit is None:
            raise ValueError("No staff grant exists")
        payload = dict(audit.payload)
        if payload["status"] == "revoked":
            return payload
        grant_row = await session.get(OrganizationMembership, UUID(payload["membership_id"]))
        assignment_row = await session.get(HouseAssignment, UUID(payload["assignment_id"]))
        if (
            grant_row is None
            or assignment_row is None
            or grant_row.user_id != user_id
            or assignment_row.user_id != user_id
        ):
            raise ValueError("Staff grant mismatch; manual investigation required")
        grant_row.status = "revoked"
        assignment_row.status = "revoked"
        payload["status"] = "revoked"
    payload["history"] = [
        *payload["history"],
        dict(action=action, at=now.isoformat(), operator=operator, reason=reason),
    ]
    audit.payload = payload
    await session.flush()
    return payload


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.app_env != AppEnvironment.PRODUCTION or settings.test_session_enabled:
        raise ValueError("Fail-closed production settings required")
    container = build_container(settings)
    try:
        async with container.session_factory() as session, session.begin():
            result = await operate(
                session,
                action=args.action,
                user_id=args.user_id,
                operator=args.operator,
                reason=args.reason,
            )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["grant", "revoke"])
    parser.add_argument("--user-id", dest="user_id", type=UUID, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    try:
        asyncio.run(run(parser.parse_args()))
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
