"""Operator-only, singleton live smoke scope; never an authentication or HTTP path."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.base import Base
from domsignal.db.models import (
    House,
    HouseManagement,
    InboxReceipt,
    ManagementCompany,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.management import ManagementService
from domsignal.settings import AppEnvironment, Settings

AUDIT_KEY = "operator:live-smoke-house:v1"
LABEL = "ДомСигнал — LIVE TEST"


async def operate(
    session: AsyncSession, *, action: str, user_id: UUID, operator: str, reason: str
) -> dict[str, Any]:
    """Caller owns transaction. Audit is an operator receipt, never a MAX event."""
    if action not in {"create", "revoke", "delete-empty"}:
        raise ValueError("Unsupported fixture action")
    if not operator.strip() or not reason.strip() or max(len(operator), len(reason)) > 300:
        raise ValueError("A bounded operator and authorization reason are required")
    await session.execute(text("SELECT pg_advisory_xact_lock(48020260919)"))
    audit = await session.get(InboxReceipt, AUDIT_KEY)
    if audit and audit.payload["user_id"] != str(user_id):
        raise ValueError("The singleton fixture belongs to another user")
    if action == "create" and audit:
        if audit.payload["status"] != "active":
            raise ValueError("A retired fixture cannot be silently recreated")
        return audit.payload
    now = datetime.now(UTC)
    house: House | None
    company: ManagementCompany | None
    management: HouseManagement | None
    membership: ResidentMembership | None
    if action == "create":
        user = await session.get(User, user_id)
        if (
            user is None
            or not user.max_user_id
            or user.max_identity_verified_at is None
            or user.demo_alias is not None
            or user.platform_role is not None
        ):
            raise ValueError("An existing validated non-demo MAX resident is required")
        company = ManagementCompany(name=LABEL, is_demo=False)
        house = House(name=LABEL, address="Изолированный тестовый дом LIVE MAX", is_demo=False)
        session.add_all([company, house])
        await session.flush()
        management = await ManagementService().create(
            session,
            house_id=house.id,
            tenant_id=company.id,
            valid_from=now,
            basis_type="operator_live_smoke",
            basis_reference=AUDIT_KEY,
            created_by=user.id,
        )
        management.ticket_intake_enabled = True
        membership = ResidentMembership(
            user_id=user.id,
            house_id=house.id,
            source="operator_live_smoke",
            evidence_source=AUDIT_KEY,
            verification_level="test_scope_authorized",
            verified_at=now,
        )
        session.add(membership)
        await session.flush()
        payload: dict[str, Any] = dict(
            user_id=str(user.id),
            house_id=str(house.id),
            tenant_id=str(company.id),
            management_id=str(management.id),
            membership_id=str(membership.id),
            status="active",
            history=[],
        )
        audit = InboxReceipt(event_id=AUDIT_KEY, event_type="operator.live_fixture", payload={})
        session.add(audit)
    else:
        if audit is None:
            raise ValueError("No operator fixture exists")
        payload = dict(audit.payload)
        if payload["status"] == "deleted":
            return payload
        house = await session.get(House, UUID(payload["house_id"]), with_for_update=True)
        company = await session.get(ManagementCompany, UUID(payload["tenant_id"]))
        management = await session.get(HouseManagement, UUID(payload["management_id"]))
        membership = await session.get(ResidentMembership, UUID(payload["membership_id"]))
        if (
            house is None
            or company is None
            or management is None
            or membership is None
            or management.house_id != house.id
            or management.tenant_id != company.id
            or management.basis_reference != AUDIT_KEY
            or membership.house_id != house.id
            or membership.user_id != user_id
            or membership.evidence_source != AUDIT_KEY
        ):
            raise ValueError("Fixture identity mismatch; manual investigation required")
        if action == "revoke":
            membership.status = "revoked"
            management.status = "ended"
            company.status = "archived"
            if payload.get("operator_membership_id"):
                grant = await session.get(
                    OrganizationMembership, UUID(payload["operator_membership_id"])
                )
                if grant is None or grant.tenant_id != company.id:
                    raise ValueError("Operator grant mismatch")
                grant.status = "revoked"
            payload["status"] = "revoked"
        else:
            # Check every FK in metadata, including cascading ones: no product,
            # connection history, employee grant or extra resident may be deleted.
            owned = {
                "houses": house.id,
                "management_companies": company.id,
                "house_managements": management.id,
                "resident_memberships": membership.id,
            }
            for table in Base.metadata.sorted_tables:
                for fk in table.foreign_keys:
                    target = fk.column.table.name
                    if target not in owned:
                        continue
                    target_value = house.id if fk.column.name == "house_id" else owned[target]
                    query = select(func.count()).select_from(table).where(fk.parent == target_value)
                    if table.name in owned:
                        query = query.where(table.c.id != owned[table.name])
                    if await session.scalar(query):
                        raise ValueError("Fixture has dependent data; revoke instead")
            for row in (membership, management, house, company):
                await session.delete(row)
                await session.flush()
            payload["status"] = "deleted"
    payload["history"] = [
        *payload["history"],
        dict(
            action=action,
            at=now.isoformat(),
            operator=operator,
            reason=reason,
        ),
    ]
    audit.payload = payload
    await session.flush()
    return payload


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.app_env != AppEnvironment.PRODUCTION or settings.test_session_enabled:
        raise ValueError("This CLI requires fail-closed production settings")
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session, session.begin():
            result = await operate(
                session,
                action=args.action,
                user_id=args.user_id,
                operator=args.operator,
                reason=args.reason,
            )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "revoke", "delete-empty"])
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
