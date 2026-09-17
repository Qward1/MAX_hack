from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from domsignal.db.models import House, HouseMembership, User
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import AppEnvironment, Settings, get_settings

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OUTSIDER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
DEMO_HOUSE_ID = UUID("00000000-0000-0000-0000-000000000101")
OTHER_HOUSE_ID = UUID("00000000-0000-0000-0000-000000000102")


async def seed(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.app_env is AppEnvironment.PRODUCTION or not settings.demo_seed:
        print("Demo seed is disabled for this environment")
        return
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            await session.execute(
                insert(User)
                .values(
                    [
                        {
                            "id": DEMO_USER_ID,
                            "display_name": "Тестовый житель",
                            "demo_alias": "demo",
                            "max_user_id": "demo-max-user",
                        },
                        {
                            "id": OUTSIDER_USER_ID,
                            "display_name": "Житель другого дома",
                            "demo_alias": "outsider",
                            "max_user_id": "outsider-max-user",
                        },
                    ]
                )
                .on_conflict_do_nothing(index_elements=[User.id])
            )
            await session.execute(
                insert(House)
                .values(
                    [
                        {
                            "id": DEMO_HOUSE_ID,
                            "name": "Демо-дом на Чистопольской",
                            "address": "Казань, Чистопольская улица, 1 (демо)",
                            "is_demo": True,
                        },
                        {
                            "id": OTHER_HOUSE_ID,
                            "name": "Другой тестовый дом",
                            "address": "Казань, Другая улица, 2 (демо)",
                            "is_demo": True,
                        },
                    ]
                )
                .on_conflict_do_nothing(index_elements=[House.id])
            )
            await session.execute(
                insert(HouseMembership)
                .values(
                    [
                        {
                            "id": UUID("00000000-0000-0000-0000-000000000201"),
                            "user_id": DEMO_USER_ID,
                            "house_id": DEMO_HOUSE_ID,
                            "role": "resident",
                            "evidence_source": "demo_seed",
                        },
                        {
                            "id": UUID("00000000-0000-0000-0000-000000000202"),
                            "user_id": OUTSIDER_USER_ID,
                            "house_id": OTHER_HOUSE_ID,
                            "role": "resident",
                            "evidence_source": "demo_seed",
                        },
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[HouseMembership.user_id, HouseMembership.house_id]
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
