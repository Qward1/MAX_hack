"""Explicit A-07 operator commands, confined to the audited singleton smoke scope."""

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
from domsignal.contracts.chat_connections import ConnectionCreate
from domsignal.db.models import (
    ConnectionRequest,
    InboxReceipt,
    MAXChat,
    OrganizationMembership,
    User,
)
from domsignal.services.chat_connections import ChatConnectionService
from domsignal.services.errors import ServiceError
from domsignal.services.membership import MembershipService
from domsignal.settings import AppEnvironment, Settings
from domsignal.tools.live_fixture import AUDIT_KEY

CONNECTION_AUDIT = "operator:live-smoke-connection:v1"


async def operate(
    session: AsyncSession,
    connections: ChatConnectionService,
    *,
    action: str,
    chat_id: str,
    operator: str,
    reason: str,
    confirm: bool = False,
) -> dict[str, Any]:
    if action not in {"prepare", "approve"} or not operator.strip() or not reason.strip():
        raise ValueError("Explicit operator, reason and supported action required")
    if max(len(operator), len(reason)) > 300 or (action == "approve" and not confirm):
        raise ValueError("Approval requires explicit --confirm; audit text must be bounded")
    await session.execute(text("SELECT pg_advisory_xact_lock(48020260919)"))
    fixture = await session.get(InboxReceipt, AUDIT_KEY)
    if fixture is None or fixture.payload["status"] != "active":
        raise ValueError("An active audited live fixture is required")
    scope = dict(fixture.payload)
    resident = await session.get(User, UUID(scope["user_id"]))
    if resident is None or resident.max_identity_verified_at is None or not resident.max_user_id:
        raise ValueError("Existing validated resident identity is required")
    context = await MembershipService().require_house(
        session,
        user_id=resident.id,
        house_id=UUID(scope["house_id"]),
        for_write=True,
    )
    if str(context.management_id.value) != scope["management_id"]:
        raise ValueError("Fixture management changed")
    chat = await session.scalar(select(MAXChat).where(MAXChat.max_chat_id == chat_id))
    receipt = await session.scalar(
        select(InboxReceipt).where(
            InboxReceipt.event_type == "bot_added",
            InboxReceipt.payload["chat_id"].astext == chat_id,
        )
    )
    if chat is None or receipt is None or not chat.bot_present or chat.type != "chat":
        raise ValueError("A real persisted bot_added for this group is required")
    audit = await session.get(InboxReceipt, CONNECTION_AUDIT)
    if audit is not None and audit.payload["chat_id"] != chat_id:
        raise ValueError("The connection is pinned to a different chat")
    if action == "prepare" and audit is not None:
        return {**audit.payload, "launch_url": None}
    now = datetime.now(UTC).isoformat()
    request: ConnectionRequest | None
    if action == "prepare":
        # A service principal, not a fabricated MAX person; no session/credential.
        staff = User(display_name="LIVE TEST — CLI operator")
        session.add(staff)
        await session.flush()
        grant = OrganizationMembership(
            user_id=staff.id,
            tenant_id=UUID(scope["tenant_id"]),
            role="company_admin",
        )
        session.add(grant)
        await session.flush()
        request, token = await connections.initiate(
            session,
            actor_id=staff.id,
            house_id=UUID(scope["house_id"]),
            scope=ConnectionCreate(),
        )
        scope["operator_user_id"] = str(staff.id)
        scope["operator_membership_id"] = str(grant.id)
        scope["history"] = [
            *scope["history"],
            dict(
                action="provision_scoped_cli_operator",
                at=now,
                operator=operator,
                reason=reason,
            ),
        ]
        fixture.payload = scope
        data: dict[str, Any] = dict(
            chat_id=chat_id,
            request_id=str(request.id),
            operator_user_id=str(staff.id),
            expected_connector=resident.max_user_id,
            house_id=scope["house_id"],
            management_id=scope["management_id"],
            status="prepared",
            history=[],
        )
        audit = InboxReceipt(
            event_id=CONNECTION_AUDIT, event_type="operator.live_connection", payload={}
        )
        session.add(audit)
        launch_url = f"https://max.ru/t480_hakaton_max_bot?start={token}"
    else:
        if audit is None:
            raise ValueError("Prepare the connection first")
        data = dict(audit.payload)
        request = await session.get(ConnectionRequest, UUID(data["request_id"]))
        if (
            request is None
            or request.candidate_max_chat_id != chat_id
            or request.connector_max_user_id != data["expected_connector"]
            or str(request.management_id) != scope["management_id"]
        ):
            raise ValueError("Waiting for the real correlated bot_started and bot_added")
        binding = await connections.approve(
            session,
            request_id=request.id,
            actor_id=UUID(data["operator_user_id"]),
        )
        data.update(status="active", binding_id=str(binding.id), version=binding.binding_version)
        launch_url = None
    data["history"] = [
        *data["history"],
        dict(
            action=action,
            at=now,
            operator=operator,
            reason=reason,
        ),
    ]
    audit.payload = data
    await session.flush()
    # The one-time raw token is returned only to the operator, never in DB/audit.
    return {**data, "launch_url": launch_url}


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    if settings.app_env != AppEnvironment.PRODUCTION or settings.test_session_enabled:
        raise ValueError("Fail-closed production settings required")
    container = build_container(settings)
    try:
        async with container.session_factory() as session, session.begin():
            result = await operate(
                session,
                container.chat_connections,
                action=args.action,
                chat_id=args.chat_id,
                operator=args.operator,
                reason=args.reason,
                confirm=args.confirm,
            )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "approve"])
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--confirm", action="store_true")
    try:
        asyncio.run(run(parser.parse_args()))
    except (ValueError, ServiceError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
