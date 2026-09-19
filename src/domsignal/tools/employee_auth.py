"""Operator-only employee credentials; never creates users or domain permissions."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import func, select

from domsignal.bootstrap import build_container
from domsignal.db.models import AppSession, EmployeeCredential
from domsignal.services.employee_auth import SOURCE, EmployeeAuthService
from domsignal.services.errors import ServiceError
from domsignal.settings import get_settings


async def run(args: argparse.Namespace) -> None:
    container = build_container(get_settings())
    service = EmployeeAuthService(container.settings)
    try:
        async with container.session_factory() as db, db.begin():
            if args.action == "status":
                credential = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.user_id == args.user_id)
                )
                if credential is None:
                    raise ValueError("Credential does not exist")
                count = await db.scalar(
                    select(func.count())
                    .select_from(AppSession)
                    .where(
                        AppSession.user_id == args.user_id,
                        AppSession.source == SOURCE,
                        AppSession.revoked_at.is_(None),
                        AppSession.expires_at > func.now(),
                        AppSession.idle_expires_at > func.now(),
                    )
                )
                output = {
                    "login_name": credential.login_name,
                    "revoked": credential.revoked_at is not None,
                    "mfa_enabled": credential.mfa_enabled,
                    "password_change_required": credential.password_change_required,
                    "active_employee_sessions": count,
                }
            else:
                temporary = await service.provision(db, args.user_id, args.action, args.login_name)
                output = {"action": args.action, "user_id": str(args.user_id)}
                if temporary:
                    output["temporary_password"] = temporary
        # After commit only. Deliberate operator output, never application logging.
        print(json.dumps(output, ensure_ascii=False))
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["create", "reset-password", "reset-mfa", "revoke", "status"]
    )
    parser.add_argument("--user-id", required=True, type=UUID)
    parser.add_argument("--login-name")
    try:
        asyncio.run(run(parser.parse_args()))
    except (ValueError, ServiceError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
