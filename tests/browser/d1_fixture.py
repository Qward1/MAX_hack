"""Explicit local browser fixture for D1 access; never an application endpoint.

Requires APP_ENV=test and B14_BROWSER_FIXTURES=1 with a dedicated DATABASE_URL.
Commands: `guest` (a verified MAX user without houses; its open-access
memberships are ended, history kept), `open` / `close` (the open access switch
of the seeded house — the same service the company cabinet uses). Synthetic
data only; nothing is truncated.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update

from domsignal.bootstrap import build_container
from domsignal.db.models import House, ResidentMembership, User
from domsignal.services.resident_access import ResidentAccessService
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools.seed_demo import DEMO_HOUSE_ID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

GUEST_ALIAS = "d1-guest"
GUEST_MAX_ID = "990001"


async def main(command: str) -> dict[str, str]:
    settings = get_settings()
    if settings.app_env != AppEnvironment.TEST or os.getenv("B14_BROWSER_FIXTURES") != "1":
        raise RuntimeError("Isolated D1 browser fixture opt-in required")
    container = build_container(settings)
    try:
        async with container.session_factory() as db, db.begin():
            if command == "guest":
                user = await db.scalar(select(User).where(User.demo_alias == GUEST_ALIAS))
                if user is None:
                    user = User(
                        display_name="Житель без дома",
                        demo_alias=GUEST_ALIAS,
                        max_user_id=GUEST_MAX_ID,
                        max_identity_verified_at=datetime.now(UTC),
                    )
                    db.add(user)
                    await db.flush()
                await db.execute(
                    update(ResidentMembership)
                    .where(
                        ResidentMembership.user_id == user.id,
                        ResidentMembership.source == "open_access",
                        ResidentMembership.status == "active",
                    )
                    .values(
                        status="revoked",
                        ended_at=datetime.now(UTC),
                        end_reason="open_access_closed",
                    )
                )
                return {"user_id": str(user.id)}
            if command in {"open", "close"}:
                house = await db.get(House, DEMO_HOUSE_ID, with_for_update=True)
                assert house is not None, "seed_demo is required"
                await ResidentAccessService.set_open_access(
                    db, house=house, enabled=command == "open", actor_id=None
                )
                return {"house_id": str(house.id), "address": house.address}
            raise SystemExit(f"unknown command: {command}")
    finally:
        await container.aclose()


if __name__ == "__main__":
    # ASCII: вывод читает Node на любой кодировке консоли (Windows — cp1251).
    print(json.dumps(asyncio.run(main(sys.argv[1]))))
