"""Профиль маршрутизации дома: регион, муниципалитет и территория.

Административный инструмент local/test: профиль — проверяемые данные дома, а
не вывод модели. Каждое изменение записывает `updated_by`.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from domsignal.bootstrap import build_container
from domsignal.db.repositories.routing import RoutingRepository
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools import print_json


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    if settings.app_env is AppEnvironment.PRODUCTION:
        raise SystemExit("House routing profile CLI is disabled in production")
    container = build_container(settings)
    try:
        async with container.session_factory() as session, session.begin():
            repository = RoutingRepository(session)
            if await repository.house(args.house_id) is None:
                raise SystemExit("House was not found")
            profile = await repository.upsert_profile(
                house_id=args.house_id,
                region_code=args.region,
                municipality_code=args.municipality,
                territory_policy=args.territory,
                updated_by=args.actor,
            )
            print_json(
                {
                    "house_id": str(profile.house_id),
                    "region_code": profile.region_code,
                    "municipality_code": profile.municipality_code,
                    "territory_policy": profile.territory_policy,
                    "updated_by": str(profile.updated_by) if profile.updated_by else None,
                }
            )
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
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
