"""Explicit A-16 synthetic seed; no HTTP seed/reset endpoint, no historical backfill.

Run only against a dedicated test/demo DB. Existing records are never overwritten.
The separate namespace keeps the established B-02 demo dataset unchanged.
"""

import asyncio
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert

from domsignal.db.models import (
    House,
    HouseAssignment,
    HouseManagement,
    ManagementCompany,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import AppEnvironment, Settings, get_settings


def seed_id(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"domsignal:a16-demo:{name}")


async def seed(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.app_env == AppEnvironment.PRODUCTION or not settings.demo_seed:
        raise RuntimeError("A-16 seed is restricted to explicit local/test demo environments")
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session, session.begin():
            for company in ("alpha", "beta"):
                await session.execute(
                    insert(ManagementCompany)
                    .values(
                        id=seed_id(company),
                        name=f"A16 synthetic {company}",
                        is_demo=True,
                    )
                    .on_conflict_do_nothing(index_elements=[ManagementCompany.id])
                )
            for name in (
                "admin",
                "responsible",
                "operator",
                "revoked",
                "resident",
                "neighbor",
                "outsider",
                "beta-admin",
            ):
                await session.execute(
                    insert(User)
                    .values(
                        id=seed_id(name),
                        display_name=f"A16 {name}",
                        demo_alias=f"a16-{name}",
                        max_user_id=f"a16-synthetic-{name}",
                    )
                    .on_conflict_do_nothing(index_elements=[User.id])
                )
            for house, company in (("a1", "alpha"), ("a2", "alpha"), ("b1", "beta")):
                await session.execute(
                    insert(House)
                    .values(
                        id=seed_id(house),
                        name=f"A16 {house}",
                        address=f"A16 synthetic house {house}",
                        is_demo=True,
                    )
                    .on_conflict_do_nothing(index_elements=[House.id])
                )
                await session.execute(
                    insert(HouseManagement)
                    .values(
                        id=seed_id(f"management-{house}"),
                        house_id=seed_id(house),
                        tenant_id=seed_id(company),
                        valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                        basis_type="synthetic_demo",
                        is_demo=True,
                        ticket_intake_enabled=True,
                    )
                    .on_conflict_do_nothing(index_elements=[HouseManagement.id])
                )
            for name, company, role, status in (
                ("admin", "alpha", "company_admin", "active"),
                ("responsible", "alpha", "operator", "active"),
                ("operator", "alpha", "operator", "active"),
                ("revoked", "alpha", "operator", "revoked"),
                ("beta-admin", "beta", "company_admin", "active"),
            ):
                await session.execute(
                    insert(OrganizationMembership)
                    .values(
                        id=seed_id(f"org-{name}"),
                        user_id=seed_id(name),
                        tenant_id=seed_id(company),
                        role=role,
                        status=status,
                    )
                    .on_conflict_do_nothing(index_elements=[OrganizationMembership.id])
                )
            for name, status in (("responsible", "active"), ("revoked", "revoked")):
                await session.execute(
                    insert(HouseAssignment)
                    .values(
                        id=seed_id(f"assignment-{name}"),
                        user_id=seed_id(name),
                        management_id=seed_id("management-a1"),
                        role="responsible",
                        status=status,
                    )
                    .on_conflict_do_nothing(index_elements=[HouseAssignment.id])
                )
            for user, house in (
                ("resident", "a1"),
                ("neighbor", "a1"),
                ("neighbor", "b1"),
                ("outsider", "b1"),
            ):
                await session.execute(
                    insert(ResidentMembership)
                    .values(
                        id=seed_id(f"resident-{user}-{house}"),
                        user_id=seed_id(user),
                        house_id=seed_id(house),
                        source="demo",
                        evidence_source="a16_seed",
                    )
                    .on_conflict_do_nothing(index_elements=[ResidentMembership.id])
                )
    finally:
        await engine.dispose()
    print("A16 synthetic roles and 3 houses ready; real organization connection is not verified")


if __name__ == "__main__":
    asyncio.run(seed())
