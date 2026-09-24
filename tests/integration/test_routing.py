"""Профиль дома, текущее управление и предпросмотр карточки на реальной PostgreSQL."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url

from domsignal.bootstrap import build_container
from domsignal.db.models import (
    House,
    HouseManagement,
    HouseRoutingProfile,
    InboxReceipt,
    ManagementCompany,
    User,
)
from domsignal.db.repositories.routing import RoutingRepository
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import Settings
from domsignal.tools import house_routing_profile, live_fixture, route_preview
from domsignal.tools.seed_demo import DEMO_HOUSE_ID, MOSCOW_HOUSE_ID, OTHER_HOUSE_ID, seed
from tests.integration.migration_columns import without_added_columns
from tests.integration.test_migrations import migrate


def container_for(settings: Settings):
    return build_container(settings)


async def test_seed_creates_routing_profiles_idempotently(
    integration_settings: Settings,
) -> None:
    await seed(integration_settings)
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(HouseRoutingProfile)) == 3
            )
            moscow = await session.get(HouseRoutingProfile, MOSCOW_HOUSE_ID)
            assert moscow is not None
            assert (moscow.region_code, moscow.municipality_code, moscow.territory_policy) == (
                "RU-MOW",
                "moscow",
                "mixed",
            )
            demo = await session.get(HouseRoutingProfile, DEMO_HOUSE_ID)
            other = await session.get(HouseRoutingProfile, OTHER_HOUSE_ID)
            assert demo is not None and other is not None
            assert (demo.region_code, demo.municipality_code) == ("RU-TA", "kazan")
            assert demo.territory_policy == "unknown"
            assert other.territory_policy == "uk"
            assert demo.updated_by is None
    finally:
        await engine.dispose()


async def test_seed_enables_ticket_intake_for_both_demo_houses(
    integration_settings: Settings,
) -> None:
    """Решение владельца: на демонстрации виден полный путь до заявки."""
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    try:
        # Выключаем флаг и повторяем seed: он обязан включить его обратно.
        async with factory() as session, session.begin():
            await session.execute(update(HouseManagement).values(ticket_intake_enabled=False))
        await seed(integration_settings)
        await seed(integration_settings)
        async with factory() as session:
            enabled = list(
                await session.scalars(
                    select(HouseManagement.ticket_intake_enabled).where(
                        HouseManagement.house_id.in_([DEMO_HOUSE_ID, OTHER_HOUSE_ID])
                    )
                )
            )
            assert enabled == [True, True]
            # Повторный seed не размножает периоды управления.
            assert await session.scalar(select(func.count()).select_from(HouseManagement)) == 3
    finally:
        await engine.dispose()


async def test_house_context_uses_only_the_current_management(
    integration_settings: Settings,
) -> None:
    container = container_for(integration_settings)
    now = datetime.now(UTC)
    house_id, tenant_id = uuid4(), uuid4()
    try:
        async with container.session_factory() as session, session.begin():
            session.add(ManagementCompany(id=tenant_id, name="Прошлая УК"))
            session.add(
                House(id=house_id, name="Дом без текущего управления", address=f"Тест {house_id}")
            )
            await session.flush()
            session.add(
                HouseManagement(
                    house_id=house_id,
                    tenant_id=tenant_id,
                    valid_from=now - timedelta(days=400),
                    valid_to=now - timedelta(days=30),
                )
            )
        async with container.session_factory() as session:
            past = await container.routing.house_context(session, house_id)
            assert past.has_active_connected_uk is False
            route = container.routing.route(
                subtype="elevator.doors", location_scope="house_common", house=past
            )
            assert route.route_type == "unknown"
        async with container.session_factory() as session, session.begin():
            session.add(
                HouseManagement(
                    house_id=house_id,
                    tenant_id=tenant_id,
                    valid_from=now - timedelta(days=1),
                )
            )
        async with container.session_factory() as session:
            current = await container.routing.house_context(session, house_id)
            assert current.has_active_connected_uk is True
            route = container.routing.route(
                subtype="elevator.doors", location_scope="house_common", house=current
            )
            assert route.route_type == "uk_internal"
            assert route.can_create_ticket is True
    finally:
        await container.engine.dispose()


async def test_missing_profile_keeps_the_federal_layer_only(
    integration_settings: Settings,
) -> None:
    container = container_for(integration_settings)
    house_id = uuid4()
    try:
        async with container.session_factory() as session, session.begin():
            session.add(House(id=house_id, name="Дом без профиля", address=f"Тест {house_id}"))
        async with container.session_factory() as session:
            house = await container.routing.house_context(session, house_id)
            assert house.region_code is None
            assert house.municipality_code is None
            assert house.territory_policy == "unknown"
            municipal = container.routing.route(
                subtype="street_lighting.failure",
                location_scope="municipal_territory",
                house=house,
            )
            assert municipal.route_type == "municipality"
            assert [channel.id for channel in municipal.channels] == ["pos_gosuslugi"]
            assert municipal.directory_version == "_federal@2"
            yard = container.routing.route(
                subtype="playground.damaged", location_scope="house_territory", house=house
            )
            assert yard.requires_operator_choice is True
    finally:
        await container.engine.dispose()


async def test_unknown_house_never_produces_a_route(integration_settings: Settings) -> None:
    container = container_for(integration_settings)
    try:
        async with container.session_factory() as session:
            house = await container.routing.house_context(session, uuid4())
            assert house.has_active_connected_uk is False
            assert house.region_code is None
            assert house.territory_policy == "unknown"
            route = container.routing.route(
                subtype="elevator.doors", location_scope="house_common", house=house
            )
            assert route.route_type == "unknown"
    finally:
        await container.engine.dispose()


async def test_profile_cli_writes_region_and_audit(
    integration_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    await seed(integration_settings)
    actor, house_id = uuid4(), uuid4()
    container = container_for(integration_settings)
    try:
        async with container.session_factory() as session, session.begin():
            session.add(House(id=house_id, name="Новый дом", address=f"Тест {house_id}"))
            session.add(User(id=actor, display_name="Администратор"))
    finally:
        await container.engine.dispose()
    await house_routing_profile.run(
        argparse.Namespace(
            house_id=house_id,
            region="RU-TA",
            municipality="kazan",
            territory="municipal",
            actor=actor,
        )
    )
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["region_code"] == "RU-TA"
    assert payload["territory_policy"] == "municipal"
    assert payload["updated_by"] == str(actor)
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            stored = await RoutingRepository(session).profile(house_id)
            assert stored is not None
            assert stored.territory_policy == "municipal"
            assert stored.updated_by == actor
    finally:
        await engine.dispose()


async def test_production_profile_is_confined_to_the_audited_live_house(
    integration_settings: Settings,
) -> None:
    """P7a: в production профиль задаётся только дому live-стенда, с квитанцией."""
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    resident = uuid4()
    change = dict(region="RU-TA", municipality="kazan", territory="mixed", actor=None)
    try:
        async with factory() as session, session.begin():
            session.add(
                User(
                    id=resident,
                    display_name="Synthetic resident",
                    max_user_id=f"profile-{resident}",
                    max_identity_verified_at=datetime.now(UTC),
                )
            )
        # Без стенда production ничего не пишет, даже для существующего дома.
        async with factory() as session, session.begin():
            with pytest.raises(ValueError, match="live-test house"):
                await house_routing_profile.operate(
                    session,
                    house_id=DEMO_HOUSE_ID,
                    production=True,
                    operator="pytest",
                    reason="deterministic test",
                    **change,
                )
        async with factory() as session, session.begin():
            fixture = await live_fixture.operate(
                session,
                action="create",
                user_id=resident,
                operator="pytest",
                reason="deterministic test",
            )
        live_house = UUID(fixture["house_id"])
        for operator, reason in ((None, "reason"), ("pytest", None), ("  ", "reason")):
            async with factory() as session, session.begin():
                with pytest.raises(ValueError, match="--operator and --reason"):
                    await house_routing_profile.operate(
                        session,
                        house_id=live_house,
                        production=True,
                        operator=operator,
                        reason=reason,
                        **change,
                    )
        async with factory() as session, session.begin():
            with pytest.raises(ValueError, match="live-test house"):
                await house_routing_profile.operate(
                    session,
                    house_id=OTHER_HOUSE_ID,
                    production=True,
                    operator="pytest",
                    reason="deterministic test",
                    **change,
                )
            # Отказ ничего не записал.
            assert await session.scalar(
                select(func.count())
                .select_from(InboxReceipt)
                .where(InboxReceipt.event_type == house_routing_profile.PROFILE_AUDIT_TYPE)
            ) == 0
        async with factory() as session, session.begin():
            result = await house_routing_profile.operate(
                session,
                house_id=live_house,
                production=True,
                operator="pytest",
                reason="deterministic test",
                **change,
            )
        assert result["territory_policy"] == "mixed" and result["region_code"] == "RU-TA"
        async with factory() as session:
            stored = await RoutingRepository(session).profile(live_house)
            assert stored is not None
            assert (stored.region_code, stored.municipality_code) == ("RU-TA", "kazan")
            receipts = list(
                await session.scalars(
                    select(InboxReceipt).where(
                        InboxReceipt.event_type == house_routing_profile.PROFILE_AUDIT_TYPE
                    )
                )
            )
            assert len(receipts) == 1
            audit = receipts[0].payload
            assert audit["house_id"] == str(live_house)
            assert audit["previous"] is None
            assert audit["profile"] == {
                "region_code": "RU-TA",
                "municipality_code": "kazan",
                "territory_policy": "mixed",
            }
            assert (audit["operator"], audit["reason"]) == ("pytest", "deterministic test")
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("subtype", "scope", "danger", "expected"),
    [
        ("elevator.doors", "house_common", [], "uk_internal"),
        ("street_lighting.failure", "municipal_territory", [], "municipality"),
        ("gas.smell", "house_common", ["gas"], "emergency_service"),
        ("playground.damaged", "house_territory", [], "unknown"),
        ("other.unspecified", "unknown", [], "unknown"),
    ],
)
async def test_route_preview_prints_a_valid_card_for_the_demo_house(
    integration_settings: Settings,
    capsys: pytest.CaptureFixture[str],
    subtype: str,
    scope: str,
    danger: list[str],
    expected: str,
) -> None:
    await seed(integration_settings)
    await route_preview.run(
        argparse.Namespace(
            house_id=DEMO_HOUSE_ID,
            subtype=subtype,
            scope=scope,
            danger=danger,
            audience="resident",
            source="chat",
            existing_ticket=None,
        )
    )
    card = json.loads(capsys.readouterr().out)
    assert card["route"]["route_type"] == expected
    assert card["generated_by"] == "rules"
    assert card["demo_notice"] == "Тестовые данные"
    assert card["actions"]
    if subtype == "playground.damaged":
        assert card["route"]["requires_operator_choice"] is True
    if danger:
        assert card["safety"]["phone"] == "112"
        assert card["actions"][0]["phone"] == "112"


async def test_routing_profile_migration_is_additive_and_guards_downgrade(
    integration_settings: Settings,
) -> None:
    name = f"p3a_migration_{uuid4().hex}"
    url = (
        make_url(integration_settings.database_url)
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    admin = create_engine(integration_settings.database_url)
    async with admin.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    try:
        await migrate(url, "upgrade", "e107a3cff433")
        house, tenant = uuid4(), uuid4()
        values = {"house": house, "tenant": tenant}
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO houses(id,name,address) VALUES (:house,'P3a','P3a synthetic')"),
                values,
            )
            await connection.execute(
                text("INSERT INTO management_companies(id,name) VALUES (:tenant,'P3a company')"),
                values,
            )
            await connection.execute(
                text(
                    "INSERT INTO house_managements(id,house_id,tenant_id,valid_from) "
                    "VALUES (:management,:house,:tenant,now()-interval '1 day')"
                ),
                {**values, "management": uuid4()},
            )
            before = (await connection.execute(text("SELECT row_to_json(t) FROM houses t"))).all()
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.connect() as connection:
            assert (
                await connection.execute(
                    text(f"SELECT {without_added_columns('houses')} FROM houses t")
                )
            ).all() == before
            assert (
                await connection.scalar(text("SELECT count(*) FROM house_routing_profiles")) == 0
            )
        await engine.dispose()
        await migrate(url, "downgrade", "e107a3cff433")  # пустая таблица откатывается
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO house_routing_profiles"
                    "(house_id,region_code,municipality_code,territory_policy) "
                    "VALUES (:house,'RU-TA','kazan','uk')"
                ),
                values,
            )
        await engine.dispose()
        with pytest.raises(AssertionError, match="House routing profiles retained"):
            await migrate(url, "downgrade", "e107a3cff433")
        async with engine.connect() as connection:
            assert (
                await connection.scalar(text("SELECT count(*) FROM house_routing_profiles")) == 1
            )
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
