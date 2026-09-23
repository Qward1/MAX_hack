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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bootstrap import build_container
from domsignal.db.models import HouseRoutingProfile, InboxReceipt
from domsignal.db.repositories.routing import RoutingRepository
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools import print_json
from domsignal.tools.live_fixture import AUDIT_KEY as LIVE_FIXTURE_KEY

PROFILE_AUDIT_PREFIX = "operator:house-routing-profile:v1"
PROFILE_AUDIT_TYPE = "operator.house_routing_profile"


def _view(profile: HouseRoutingProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "region_code": profile.region_code,
        "municipality_code": profile.municipality_code,
        "territory_policy": profile.territory_policy,
    }


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
    """Записать профиль дома. Транзакцией владеет вызывающий."""
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
    repository = RoutingRepository(session)
    if await repository.house(house_id) is None:
        raise ValueError("House was not found")
    previous = _view(await repository.profile(house_id))
    profile = await repository.upsert_profile(
        house_id=house_id,
        region_code=region,
        municipality_code=municipality,
        territory_policy=territory,
        updated_by=actor,
    )
    result: dict[str, Any] = {
        "house_id": str(profile.house_id),
        **(_view(profile) or {}),
        "updated_by": str(profile.updated_by) if profile.updated_by else None,
    }
    if production:
        now = datetime.now(UTC)
        session.add(
            InboxReceipt(
                event_id=f"{PROFILE_AUDIT_PREFIX}:{house_id}:{now:%Y%m%dT%H%M%S%fZ}",
                event_type=PROFILE_AUDIT_TYPE,
                payload={
                    "house_id": str(house_id),
                    "previous": previous,
                    "profile": _view(profile),
                    "updated_by": result["updated_by"],
                    "operator": operator,
                    "reason": reason,
                    "at": now.isoformat(),
                },
            )
        )
        await session.flush()
    return result


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
