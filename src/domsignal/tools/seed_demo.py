from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert

from domsignal.db.models import (
    House,
    HouseManagement,
    HouseRoutingProfile,
    ManagementCompany,
    ResidentMembership,
    User,
)
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import AppEnvironment, Settings, get_settings

DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OUTSIDER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
DEMO_HOUSE_ID = UUID("00000000-0000-0000-0000-000000000101")
DEMO_TENANT_ID = UUID("00000000-0000-0000-0000-000000000301")
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
                insert(ManagementCompany)
                .values(
                    id=DEMO_TENANT_ID,
                    name="Demo ManagementCompany",
                    is_demo=True,
                )
                .on_conflict_do_nothing(index_elements=[ManagementCompany.id])
            )
            # Решение владельца по итогам P3a: на демонстрации показываем полный
            # путь «сообщение → разбор → Ticket → статус», поэтому демо-дома
            # принимают заявки. Идемпотентно: повторный seed только включает флаг.
            for house_id in (DEMO_HOUSE_ID, OTHER_HOUSE_ID):
                await session.execute(
                    insert(HouseManagement)
                    .values(
                        id=house_id,
                        house_id=house_id,
                        tenant_id=DEMO_TENANT_ID,
                        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
                        basis_type="demo",
                        is_demo=True,
                        ticket_intake_enabled=True,
                    )
                    .on_conflict_do_update(
                        index_elements=[HouseManagement.id],
                        set_={"ticket_intake_enabled": True},
                    )
                )
            # Профиль маршрутизации: демо-дом с неопределённой территорией
            # показывает выбор диспетчера, второй дом — территорию УК.
            await session.execute(
                insert(HouseRoutingProfile)
                .values(
                    [
                        {
                            "house_id": DEMO_HOUSE_ID,
                            "region_code": "RU-TA",
                            "municipality_code": "kazan",
                            "territory_policy": "unknown",
                        },
                        {
                            "house_id": OTHER_HOUSE_ID,
                            "region_code": "RU-TA",
                            "municipality_code": "kazan",
                            "territory_policy": "uk",
                        },
                    ]
                )
                .on_conflict_do_nothing(index_elements=[HouseRoutingProfile.house_id])
            )
            await session.execute(
                insert(ResidentMembership)
                .values(
                    [
                        {
                            "id": UUID("00000000-0000-0000-0000-000000000201"),
                            "user_id": DEMO_USER_ID,
                            "house_id": DEMO_HOUSE_ID,
                            "source": "demo",
                            "evidence_source": "demo_seed",
                        },
                        {
                            "id": UUID("00000000-0000-0000-0000-000000000202"),
                            "user_id": OUTSIDER_USER_ID,
                            "house_id": OTHER_HOUSE_ID,
                            "source": "demo",
                            "evidence_source": "demo_seed",
                        },
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[ResidentMembership.user_id, ResidentMembership.house_id]
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
