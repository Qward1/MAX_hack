"""Витрина и проверочные аккаунты жюри — штатный инструмент (F1 §5.5).

    python -m domsignal.tools.showcase status
    python -m domsignal.tools.showcase mark-company --company-id … --operator … --reason …
    python -m domsignal.tools.showcase mark-reviewer --user-id … --operator … --reason …
    python -m domsignal.tools.showcase create-platform-reviewer --login-name jury.platform
        [--display-name "Проверяющий (платформа)"] --operator … --reason …

`--off` снимает признак. `create-platform-reviewer` создаёт отдельный аккаунт
платформы для жюри (не аккаунт владельца): суперадмин с признаком
проверочного аккаунта и временным паролем; первый вход — смена пароля и TOTP.
Каждая смена оставляет квитанцию `operator.platform_ops` (как `platform_ops`)
с прежним и новым значением.
Что защищено и как — `domsignal.services.showcase`.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import EmployeeCredential, ManagementCompany, User
from domsignal.db.repositories.reliability import authority_lock
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.services.onboarding import audit
from domsignal.settings import get_settings
from domsignal.tools import print_json
from domsignal.tools.platform_ops import check_operator, receipt


async def run(args: argparse.Namespace) -> None:
    container = build_container(get_settings())
    try:
        async with container.session_factory() as session, session.begin():
            if args.command == "status":
                companies = (
                    await session.execute(
                        select(ManagementCompany.id, ManagementCompany.name).where(
                            ManagementCompany.showcase.is_(True)
                        )
                    )
                ).all()
                reviewers = (
                    await session.execute(
                        select(User.id, User.display_name).where(User.reviewer.is_(True))
                    )
                ).all()
                print_json(
                    {
                        "showcase_companies": [{"id": str(i), "name": n} for i, n in companies],
                        "reviewers": [{"id": str(i), "name": n} for i, n in reviewers],
                    }
                )
                return
            check_operator(args.operator, args.reason)
            if args.command == "create-platform-reviewer":
                await authority_lock(db := session, exclusive=True)
                taken = await db.scalar(
                    select(EmployeeCredential.id).where(
                        EmployeeCredential.login_name == args.login_name.lower()
                    )
                )
                if taken:
                    raise SystemExit("login name is taken")
                user = User(
                    display_name=args.display_name, platform_role="superadmin", reviewer=True
                )
                db.add(user)
                await db.flush()
                audit(db, "platform.reviewer_created", user.id, user.id)
                temporary = await EmployeeAuthService(container.settings).provision(
                    db, user.id, "create", args.login_name
                )
                receipt(
                    db,
                    action="showcase.platform_reviewer",
                    object_id=user.id,
                    before=None,
                    after={"platform_role": "superadmin", "reviewer": True},
                    operator=args.operator,
                    reason=args.reason,
                )
                print_json({"user_id": str(user.id), "temporary_password": temporary})
                return
            value = not args.off
            if args.command == "mark-company":
                company = await session.get(ManagementCompany, UUID(args.company_id))
                if company is None:
                    raise SystemExit("company not found")
                before = company.showcase
                company.showcase = value
                receipt(
                    session,
                    action="showcase.company",
                    object_id=company.id,
                    before={"showcase": before},
                    after={"showcase": value},
                    operator=args.operator,
                    reason=args.reason,
                )
                print_json({"company_id": str(company.id), "showcase": value})
            else:
                target = await session.get(User, UUID(args.user_id))
                if target is None:
                    raise SystemExit("user not found")
                before = target.reviewer
                target.reviewer = value
                receipt(
                    session,
                    action="showcase.reviewer",
                    object_id=target.id,
                    before={"reviewer": before},
                    after={"reviewer": value},
                    operator=args.operator,
                    reason=args.reason,
                )
                print_json({"user_id": str(target.id), "reviewer": value})
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    create = commands.add_parser("create-platform-reviewer")
    create.add_argument("--login-name", required=True)
    create.add_argument("--display-name", default="Проверяющий (платформа)")
    create.add_argument("--operator", required=True)
    create.add_argument("--reason", required=True)
    for name, key in (("mark-company", "--company-id"), ("mark-reviewer", "--user-id")):
        command = commands.add_parser(name)
        command.add_argument(key, required=True)
        command.add_argument("--operator", required=True)
        command.add_argument("--reason", required=True)
        command.add_argument("--off", action="store_true", help="снять признак")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
