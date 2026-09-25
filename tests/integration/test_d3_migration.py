"""D3 migration: additive, prior rows keep working, downgrade guards retained history."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine
from tests.integration.test_migrations import migrate


async def test_prior_rows_get_safe_defaults_and_the_migration_round_trips(integration_settings):
    name = "d3_migration_" + uuid4().hex
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
        await migrate(url, "upgrade", "20260926_0012")
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
                text("INSERT INTO users (id, display_name) VALUES (:id, 'Сотрудник')"),
                {"id": user},
            )
            await c.execute(
                text(
                    "INSERT INTO organization_memberships (id, user_id, tenant_id, role) "
                    "VALUES (:id, :user, :company, 'company_admin')"
                ),
                {"id": uuid4(), "user": user, "company": company},
            )
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.connect() as c:
            row = (
                await c.execute(
                    text("SELECT entrance_count, floor_count, facts_updated_at FROM houses")
                )
            ).one()
            assert tuple(row) == (None, None, None)
            assert await c.scalar(text("SELECT broadcast_opt_out_at FROM users")) is None
            assert (
                await c.scalar(text("SELECT daily_digest_enabled FROM organization_memberships"))
                is False
            )
            rows = await c.execute(
                text(
                    "SELECT column_name, column_default FROM information_schema.columns "
                    "WHERE table_name = 'chat_bindings' "
                    "AND (column_name LIKE 'post_%' OR column_name LIKE 'quiet_%')"
                )
            )
            defaults = {row[0]: row[1] for row in rows}
            assert defaults == {
                "post_ticket_status": "true",
                "post_company_messages": "true",
                "post_polls": "true",
                "post_platform_messages": "false",
                "quiet_start_minute": "1320",
                "quiet_end_minute": "480",
            }
        async with engine.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO broadcasts (id, origin, tenant_id, kind, title, body, audience, "
                    "channels, author_id) VALUES (:id, 'company', :company, 'mailing', 'Т', 'Т', "
                    "'{}', '[]', :user)"
                ),
                {"id": uuid4(), "company": company, "user": user},
            )
        await engine.dispose()
        with pytest.raises(Exception, match="restore a pre-D3 backup"):
            await migrate(url, "downgrade", "20260926_0012")
        async with engine.begin() as c:
            await c.execute(text("DELETE FROM broadcasts"))
        await engine.dispose()
        await migrate(url, "downgrade", "20260926_0012")
        async with engine.connect() as c:
            assert (await c.scalar(text("SELECT to_regclass('broadcasts')"))) is None
            assert await c.scalar(text("SELECT count(*) FROM houses")) == 1
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
