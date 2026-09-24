"""D2 migration: existing companies keep working (explicit unlimited quota)."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine
from tests.integration.test_migrations import migrate


async def test_existing_companies_get_unlimited_quota_and_round_trip(integration_settings):
    name = "d2_migration_" + uuid4().hex
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
        await migrate(url, "upgrade", "20260925_0011")
        company, second = uuid4(), uuid4()
        async with engine.begin() as c:
            for obj, inn in ((company, "7700000031"), (second, None)):
                await c.execute(
                    text(
                        "INSERT INTO management_companies (id, name, status, inn) "
                        "VALUES (:id, 'Прежняя УК', 'active', :inn)"
                    ),
                    {"id": obj, "inn": inn},
                )
            await c.execute(
                text(
                    "INSERT INTO company_onboarding_requests "
                    "(id, legal_name, short_name, inn, contact_name, status, submitted_at) "
                    "VALUES (:id, 'ООО Прежняя', 'Прежняя', '7700000032', 'Контакт', "
                    "'submitted', now())"
                ),
                {"id": uuid4()},
            )
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.connect() as c:
            grants = (
                await c.execute(
                    text(
                        "SELECT company_id, kind, limit_after, delta FROM chat_quota_grants "
                        "ORDER BY seq"
                    )
                )
            ).all()
            assert {row.company_id for row in grants} == {company, second}
            assert {(row.kind, row.limit_after, row.delta) for row in grants} == {
                ("migration", None, None)
            }
            legacy = (
                await c.execute(
                    text(
                        "SELECT requested_chat_count, status_token_hash, admin_invite_generation "
                        "FROM company_onboarding_requests"
                    )
                )
            ).one()
            assert tuple(legacy) == (None, None, 0)
            # Повтор ИНН теперь допустим на уровне схемы: каждая отправка — своя заявка.
            await c.execute(
                text(
                    "INSERT INTO company_onboarding_requests "
                    "(id, legal_name, short_name, inn, contact_name, status, submitted_at) "
                    "VALUES (:id, 'ООО Прежняя', 'Прежняя', '7700000033', 'Контакт', "
                    "'submitted', now()), (:id2, 'ООО Прежняя', 'Прежняя', '7700000033', "
                    "'Контакт', 'submitted', now())"
                ),
                {"id": uuid4(), "id2": uuid4()},
            )
            await c.rollback()
        await engine.dispose()
        await migrate(url, "downgrade", "20260925_0011")
        async with engine.connect() as c:
            assert (await c.scalar(text("SELECT to_regclass('chat_quota_grants')"))) is None
            assert await c.scalar(text("SELECT count(*) FROM management_companies")) == 2
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
