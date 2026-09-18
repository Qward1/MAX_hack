"""Explicit local browser fixture mutations; never mounted as application endpoints.

Requires APP_ENV=test and B14_BROWSER_FIXTURES=1 with a dedicated DATABASE_URL.
No truncation, production tokens, real MAX calls or shared demo reset.
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from domsignal.db.models import (
    House,
    HouseAssignment,
    Incident,
    OrganizationMembership,
    Report,
    ResidentMembership,
    ResultObservation,
    Ticket,
    WorkAttempt,
)
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.management import ManagementService
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools.seed_tickets import seed_id


async def main() -> None:
    settings = get_settings()
    if settings.app_env != AppEnvironment.TEST or os.getenv("B14_BROWSER_FIXTURES") != "1":
        raise RuntimeError("Explicit isolated browser fixture opt-in is required")
    engine = create_engine(settings.database_url)
    result: dict = {}
    try:
        async with create_session_factory(engine)() as session, session.begin():
            command = sys.argv[1]
            if command == "prepare":
                await session.execute(
                    insert(HouseAssignment)
                    .values(
                        id=seed_id("b14-operator-assignment"),
                        user_id=seed_id("operator"),
                        management_id=seed_id("management-a1"),
                        role="operator",
                    )
                    .on_conflict_do_nothing(index_elements=[HouseAssignment.id])
                )
                await session.execute(
                    insert(ResidentMembership)
                    .values(
                        id=seed_id("b14-resident-a2"),
                        user_id=seed_id("resident"),
                        house_id=seed_id("a2"),
                        source="demo",
                    )
                    .on_conflict_do_nothing(index_elements=[ResidentMembership.id])
                )
                result = {name: str(seed_id(name)) for name in ("a1", "a2", "b1")}
            elif command in {"revoke", "restore"}:
                await session.execute(
                    update(OrganizationMembership)
                    .where(OrganizationMembership.user_id == seed_id("operator"))
                    .values(status="revoked" if command == "revoke" else "active")
                )
            elif command == "link":
                incident = await session.get(Incident, UUID(sys.argv[2]))
                assert incident is not None
                session.add(
                    Report(
                        incident_id=incident.id,
                        house_id=incident.house_id,
                        author_id=seed_id("neighbor"),
                        category=incident.category,
                        description="B14 explicitly linked neighbor report",
                        provenance="api",
                    )
                )
            elif command == "new-house":
                house = House(
                    id=uuid4(),
                    name="B14 switch fixture",
                    address=f"B14 дом смены УК {uuid4()}",
                    is_demo=True,
                )
                session.add(house)
                await session.flush()
                management = await ManagementService().create(
                    session,
                    house_id=house.id,
                    tenant_id=seed_id("alpha"),
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    is_demo=True,
                )
                management.ticket_intake_enabled = True
                session.add(
                    ResidentMembership(
                        house_id=house.id,
                        user_id=seed_id("resident"),
                        source="demo",
                    )
                )
                result = {"house": str(house.id), "management": str(management.id)}
            elif command == "switch":
                await ManagementService().switch(
                    session,
                    management_id=UUID(sys.argv[2]),
                    tenant_id=seed_id("beta"),
                    at=datetime.now(UTC),
                    basis_reference="B14 synthetic browser check",
                )
            elif command == "snapshot":
                ticket = await session.get(Ticket, UUID(sys.argv[2]))
                assert ticket is not None
                result = {
                    "id": str(ticket.id),
                    "status": ticket.status,
                    "version": ticket.version,
                    "attempts": await session.scalar(
                        select(func.count())
                        .select_from(WorkAttempt)
                        .where(WorkAttempt.ticket_id == ticket.id)
                    ),
                    "observations": await session.scalar(
                        select(func.count())
                        .select_from(ResultObservation)
                        .join(WorkAttempt)
                        .where(WorkAttempt.ticket_id == ticket.id)
                    ),
                }
            else:
                raise ValueError("Unknown fixture operation")
    finally:
        await engine.dispose()
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
