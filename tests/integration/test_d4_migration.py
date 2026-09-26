"""D4 migration: additive, council broadcasts need a tenant, downgrade guards history."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine
from tests.integration.test_migrations import migrate


async def test_the_council_migration_round_trips_and_guards_retained_rows(integration_settings):
    name = "d4_migration_" + uuid4().hex
    url = (
        make_url(integration_settings.database_url)
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    admin = create_engine(integration_settings.database_url)
    async with admin.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    try:
        await migrate(url, "upgrade", "20260927_0013")
        company, house, user = uuid4(), uuid4(), uuid4()
        async with engine.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO management_companies (id, name, status) "
                    "VALUES (:id, 'УК', 'active')"
                ),
                {"id": company},
            )
            await c.execute(
                text("INSERT INTO houses (id, name, address) VALUES (:id, 'Дом', 'Казань, д. 1')"),
                {"id": house},
            )
            await c.execute(
                text("INSERT INTO users (id, display_name) VALUES (:id, 'Житель')"), {"id": user}
            )
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        council_post = (
            "INSERT INTO broadcasts (id, origin, tenant_id, kind, title, body, audience, "
            "channels, author_id) VALUES (:id, 'council', :company, 'announcement', 'Т', 'Т', "
            "'{}', '[]', :user)"
        )
        # Сообщение совета, как и УК, привязано к УК дома.
        with pytest.raises(Exception, match="origin_tenant"):
            async with engine.begin() as c:
                await c.execute(
                    text(council_post.replace(":company", "NULL")), {"id": uuid4(), "user": user}
                )
        async with engine.begin() as c:
            await c.execute(text(council_post), {"id": uuid4(), "company": company, "user": user})
            await c.execute(
                text(
                    "INSERT INTO house_council_members (id, house_id, user_id) "
                    "VALUES (:id, :house, :user)"
                ),
                {"id": uuid4(), "house": house, "user": user},
            )
        await engine.dispose()
        with pytest.raises(Exception, match="restore a pre-D4 backup"):
            await migrate(url, "downgrade", "20260927_0013")
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM house_council_members"))
            await c.execute(text("DELETE FROM broadcasts"))
        await engine.dispose()
        await migrate(url, "downgrade", "20260927_0013")
        async with engine.connect() as c:
            assert (await c.scalar(text("SELECT to_regclass('house_proposals')"))) is None
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
