"""Ручной запуск ежедневной сводки сотрудникам (D3) — то же, что задача в 09:00 МСК.

Сводку получают только сотрудники, которые включили её в кабинете и которым
бот может написать; пустой день — без сообщения. Повтор в тот же день не
дублирует: одна сводка на сотрудника, УК и день. Доставляет воркер.

    python -m domsignal.tools.daily_digest
    python -m domsignal.tools.daily_digest --company <id УК>

Сотруднику без входа в кабинет (например, оператору, получившему роль через
`live_staff`) сводку включает оператор платформы — с автором и основанием в
журнале аудита, как у `live_staff`:

    python -m domsignal.tools.daily_digest --enable-for <user id> --company <id УК> \\
        --operator <name> --reason <основание>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import OrganizationMembership
from domsignal.services.onboarding import audit
from domsignal.settings import get_settings
from domsignal.tools import print_json


async def enable(user: UUID, company: UUID, operator: str, reason: str) -> int:
    container = build_container(get_settings())
    try:
        async with container.session_factory() as session, session.begin():
            membership = await session.scalar(
                select(OrganizationMembership)
                .where(
                    OrganizationMembership.user_id == user,
                    OrganizationMembership.tenant_id == company,
                    OrganizationMembership.status == "active",
                )
                .with_for_update()
            )
            if membership is None:
                print_json({"error": "membership_not_found"})
                return 2
            membership.daily_digest_enabled = True
            audit(
                session,
                "staff_digest.enabled_by_operator",
                None,
                membership.id,
                f"{operator}: {reason}"[:500],
            )
        print_json({"daily_digest_enabled": True})
        return 0
    finally:
        await container.aclose()


async def run(company: UUID | None) -> int:
    container = build_container(get_settings())
    try:
        queued = await container.digest.run(company_id=company)
        print_json({"queued": queued})
        return 0
    finally:
        await container.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue today's staff digest now")
    parser.add_argument("--company", type=UUID, default=None)
    parser.add_argument("--enable-for", type=UUID, default=None)
    parser.add_argument("--operator")
    parser.add_argument("--reason")
    args = parser.parse_args()
    if args.enable_for is not None:
        if not (args.company and args.operator and args.reason):
            parser.error("--enable-for needs --company, --operator and --reason")
        sys.exit(asyncio.run(enable(args.enable_for, args.company, args.operator, args.reason)))
    sys.exit(asyncio.run(run(args.company)))


if __name__ == "__main__":
    main()
