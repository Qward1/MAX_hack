"""Профиль маршрутизации дома: регион, муниципалитет и территория.

Административный инструмент: профиль — проверяемые данные дома, а не вывод
модели. Каждое изменение записывает `updated_by`. В production инструмент
ограничен домом активного аудированного live-стенда (`live_fixture`) и
требует оператора и основание: изменение оставляет квитанцию оператора
`operator.house_routing_profile` с прежним и новым профилем.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bootstrap import build_container
from domsignal.db.models import InboxReceipt
from domsignal.services.house_region import (
    PROFILE_AUDIT_PREFIX,
    PROFILE_AUDIT_TYPE,
    write_profile,
)
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools import print_json
from domsignal.tools.live_fixture import AUDIT_KEY as LIVE_FIXTURE_KEY

__all__ = ["PROFILE_AUDIT_PREFIX", "PROFILE_AUDIT_TYPE", "operate"]


async def operate(
    session: AsyncSession,
    *,
    house_id: UUID,
    region: str | None,
    municipality: str | None,
    territory: str,
    actor: UUID | None,
    production: bool,
    operator: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Записать профиль дома тем же сервисом, что у платформы (D4). Транзакцией
    владеет вызывающий; событие аудита пишется всегда."""
    if production:
        if not (operator or "").strip() or not (reason or "").strip():
            raise ValueError("Production profile changes need --operator and --reason")
        if max(len(operator or ""), len(reason or "")) > 300:
            raise ValueError("Operator and reason must be at most 300 characters")
        # Тот же замок, что у live_fixture: стенд не меняется посреди записи.
        await session.execute(text("SELECT pg_advisory_xact_lock(48020260919)"))
        fixture = await session.get(InboxReceipt, LIVE_FIXTURE_KEY)
        if (
            fixture is None
            or fixture.payload.get("status") != "active"
            or fixture.payload.get("house_id") != str(house_id)
        ):
            raise ValueError("In production only the active audited live-test house is allowed")
    return await write_profile(
        session,
        house_id=house_id,
        region=region,
        municipality=municipality,
        territory=territory,
        actor=actor,
        operator=operator,
        reason=reason,
    )


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    container = build_container(settings)
    try:
        async with container.session_factory() as session, session.begin():
            try:
                result = await operate(
                    session,
                    house_id=args.house_id,
                    region=args.region,
                    municipality=args.municipality,
                    territory=args.territory,
                    actor=args.actor,
                    production=settings.app_env is AppEnvironment.PRODUCTION,
                    operator=getattr(args, "operator", None),
                    reason=getattr(args, "reason", None),
                )
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
        print_json(result)
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Set the routing profile of a house")
    parser.add_argument("--house-id", dest="house_id", type=UUID, required=True)
    parser.add_argument("--region", default=None, help="Например, RU-TA")
    parser.add_argument("--municipality", default=None, help="Например, kazan")
    parser.add_argument(
        "--territory",
        choices=["uk", "municipal", "mixed", "unknown"],
        default="unknown",
    )
    parser.add_argument(
        "--actor", type=UUID, default=None, help="Администратор, выполняющий изменение"
    )
    parser.add_argument("--operator", default=None, help="Обязателен в production")
    parser.add_argument("--reason", default=None, help="Обязателен в production")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
