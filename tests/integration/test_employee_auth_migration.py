"""A10 populated pre-auth upgrade and explicit credential-history downgrade guard."""

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.tools.seed_tickets import seed, seed_id
from tests.integration.test_migrations import migrate

#: Столбцы, добавленные после A10 (D1), и их значение у прежних строк.
LATER_COLUMNS = {
    "houses": {
        "open_resident_access": False,
        "open_access_changed_at": None,
        "open_access_changed_by": None,
    },
    "users": {"max_dialog_at": None, "max_dialog_stopped_at": None, "group_ack_at": None},
    "resident_memberships": {
        "chat_binding_id": None,
        "binding_version": None,
        "checked_at": None,
        "ended_at": None,
        "end_reason": None,
    },
}


async def test_employee_migration_preserves_domain_and_guards_history(integration_settings):
    name = "a10_migration_" + uuid4().hex
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
    settings = integration_settings.model_copy(
        update={
            "database_url": url,
            "auth_mfa_encryption_key": Fernet.generate_key().decode(),
        }
    )
    try:
        await migrate(url, "upgrade", "2aea407269aa")
        await seed(settings)
        tables = [
            "users",
            "resident_memberships",
            "houses",
            "management_companies",
            "house_managements",
            "organization_memberships",
            "house_assignments",
        ]
        async with engine.connect() as c:
            before = {
                t: (await c.execute(text(f"SELECT row_to_json(t) FROM {t} t ORDER BY id"))).all()
                for t in tables
            }
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.connect() as c:
            for t in tables:
                after = (
                    await c.execute(text(f"SELECT row_to_json(t) FROM {t} t ORDER BY id"))
                ).all()
                if t == "management_companies":
                    for row in after:
                        for key in (
                            "legal_name",
                            "inn",
                            "contact_name",
                            "contact_email",
                            "contact_phone",
                        ):
                            assert row[0].pop(key) is None
                # Аддитивные столбцы D1 появляются с пустыми значениями.
                for row in after:
                    for key, empty in LATER_COLUMNS.get(t, {}).items():
                        assert row[0].pop(key) == empty, (t, key)
                assert after == before[t]
            assert (
                await c.execute(text("SELECT count(*) FROM employee_credentials"))
            ).scalar() == 0
        await engine.dispose()
        await migrate(url, "downgrade", "2aea407269aa")
        await migrate(url, "upgrade", "head")
        async with create_session_factory(engine)() as db, db.begin():
            await EmployeeAuthService(settings).provision(
                db, seed_id("admin"), "create", "migration.employee"
            )
        await engine.dispose()
        with pytest.raises(AssertionError, match="credential/audit history retained"):
            await migrate(url, "downgrade", "2aea407269aa")
        async with engine.connect() as c:
            assert (
                await c.execute(text("SELECT count(*) FROM employee_credentials"))
            ).scalar() == 1
            assert (
                await c.execute(
                    text(
                        "SELECT count(*) FROM inbox_receipts "
                        "WHERE event_type='employee_auth.credential_provisioned'"
                    )
                )
            ).scalar() == 1
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
