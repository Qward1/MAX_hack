from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
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
#: Соседи демо-дома. Без них нельзя показать честный выбор при дубле:
#: «это та же проблема» и «нет, это другое» делают разные люди.
NEIGHBOUR_USER_ID = UUID("00000000-0000-0000-0000-000000000003")
THIRD_USER_ID = UUID("00000000-0000-0000-0000-000000000004")
DEMO_HOUSE_ID = UUID("00000000-0000-0000-0000-000000000101")
DEMO_TENANT_ID = UUID("00000000-0000-0000-0000-000000000301")
OTHER_HOUSE_ID = UUID("00000000-0000-0000-0000-000000000102")
#: Второй регион (D2, REGION-MOW-2026-09-26): тот же код, другой пакет данных.
MOSCOW_HOUSE_ID = UUID("00000000-0000-0000-0000-000000000103")


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
                            "display_name": "Анна Соколова",
                            "demo_alias": "demo",
                            "max_user_id": "demo-max-user",
                        },
                        {
                            "id": OUTSIDER_USER_ID,
                            "display_name": "Олег Васильев",
                            "demo_alias": "outsider",
                            "max_user_id": "outsider-max-user",
                        },
                        {
                            "id": NEIGHBOUR_USER_ID,
                            "display_name": "Игорь Петров",
                            "demo_alias": "demo-neighbour",
                            "max_user_id": "demo-neighbour-max-user",
                        },
                        {
                            "id": THIRD_USER_ID,
                            "display_name": "Мария Ильина",
                            "demo_alias": "demo-third",
                            "max_user_id": "demo-third-max-user",
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
                            "name": "Пилотная, 7",
                            "address": "Казань, ул. Пилотная, 7",
                            "is_demo": True,
                        },
                        {
                            "id": OTHER_HOUSE_ID,
                            "name": "Садовая, 2",
                            "address": "Казань, ул. Садовая, 2",
                            "is_demo": True,
                        },
                        {
                            "id": MOSCOW_HOUSE_ID,
                            "name": "Лесная, 3",
                            "address": "Москва, ул. Лесная, 3",
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
                    name="УК «Пилотная, 7»",
                    is_demo=True,
                )
                .on_conflict_do_nothing(index_elements=[ManagementCompany.id])
            )
            # Решение владельца по итогам P3a: на демонстрации показываем полный
            # путь «сообщение → разбор → Ticket → статус», поэтому демо-дома
            # принимают заявки. Идемпотентно: повторный seed только включает флаг.
            for house_id in (DEMO_HOUSE_ID, OTHER_HOUSE_ID, MOSCOW_HOUSE_ID):
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
                        # Москва: смешанная территория — двор решает диспетчер,
                        # городская территория ведёт в «Наш город», а не в ПОС.
                        {
                            "house_id": MOSCOW_HOUSE_ID,
                            "region_code": "RU-MOW",
                            "municipality_code": "moscow",
                            "territory_policy": "mixed",
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
                        {
                            "id": UUID("00000000-0000-0000-0000-000000000203"),
                            "user_id": NEIGHBOUR_USER_ID,
                            "house_id": DEMO_HOUSE_ID,
                            "source": "demo",
                            "evidence_source": "demo_seed",
                        },
                        {
                            "id": UUID("00000000-0000-0000-0000-000000000204"),
                            "user_id": THIRD_USER_ID,
                            "house_id": DEMO_HOUSE_ID,
                            "source": "demo",
                            "evidence_source": "demo_seed",
                        },
                    ]
                )
                .on_conflict_do_nothing(
                    index_elements=[ResidentMembership.user_id, ResidentMembership.house_id],
                    # Уникальность «житель — дом» частичная: у членства по чату
                    # и открытому доступу действующая запись одна, история — нет.
                    index_where=text("source NOT IN ('chat_member', 'open_access')"),
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
