"""Production-shaped A15/A07/A10/A16 history survives additive onboarding migration."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.contracts.chat_connections import ConnectionCreate
from domsignal.db.session import create_engine
from domsignal.main import create_app
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.tools.seed_tickets import seed, seed_id
from tests.fakes.max_chat import FakeMaxChatProvider
from tests.integration.test_migrations import migrate


async def test_populated_onboarding_upgrade_preserves_history_and_guards_downgrade(
    integration_settings,
):
    name = "b09_migration_" + uuid4().hex
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
    config = integration_settings.model_copy(
        update={"database_url": url, "auth_mfa_encryption_key": Fernet.generate_key().decode()}
    )
    app = create_app(config)
    container = app.state.container
    tables = [
        "users",
        "houses",
        "management_companies",
        "house_managements",
        "organization_memberships",
        "house_assignments",
        "resident_memberships",
        "incidents",
        "reports",
        "tickets",
        "work_attempts",
        "ticket_events",
        "app_sessions",
        "employee_credentials",
        "auth_challenges",
        "employee_recovery_codes",
        "max_chats",
        "chat_connection_requests",
        "chat_bindings",
        "notification_deliveries",
        "outbox_messages",
        "inbox_receipts",
    ]
    try:
        await migrate(url, "upgrade", "head")
        await seed(config)
        provider = FakeMaxChatProvider()
        provider.configure("-900009", connector="a16-synthetic-admin")
        container.chat_connections.provider = provider
        async with container.session_factory() as db, db.begin():
            request, token = await container.chat_connections.initiate(
                db, actor_id=seed_id("admin"), house_id=seed_id("a1"), scope=ConnectionCreate()
            )
            await container.chat_connections.claim(
                db, token=token, connector="a16-synthetic-admin", occurred_at=datetime.now(UTC)
            )
            await container.chat_connections.bot_added(
                db,
                chat_id="-900009",
                actor="a16-synthetic-admin",
                occurred_at=datetime.now(UTC),
                is_channel=False,
            )
            await container.chat_connections.approve(
                db, request_id=request.id, actor_id=seed_id("admin")
            )
            await EmployeeAuthService(config).provision(
                db, seed_id("admin"), "create", "migration.b09"
            )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
            session = (
                await c.post("/api/v1/auth/test-session", json={"actor": "a16-resident"})
            ).json()
            c.headers["Authorization"] = "Bearer " + session["access_token"]
            r = await c.post(
                "/api/v1/reports",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "house_id": str(seed_id("a1")),
                    "category": "water",
                    "description": "Migration private report",
                },
            )
            assert r.status_code == 201, r.text
            iid = r.json()["incident"]["id"]
            tid = (await c.get(f"/api/v1/incidents/{iid}/work-status")).json()["ticket_id"]
            session = (
                await c.post("/api/v1/auth/test-session", json={"actor": "a16-responsible"})
            ).json()
            c.headers["Authorization"] = "Bearer " + session["access_token"]
            for action, payload in (
                ("accept", {}),
                ("start", {}),
                ("work-attempts", {"public_description": "Preserved work attempt"}),
            ):
                version = (await c.get(f"/api/v1/tickets/{tid}")).json()["version"]
                r = await c.post(
                    f"/api/v1/tickets/{tid}/{action}",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"expected_version": version, **payload},
                )
                assert r.status_code == 200, r.text
        await container.engine.dispose()
        # Roll back only the empty new administrative schema to obtain a populated actual A10 DB.
        await migrate(url, "downgrade", "1c5baa831ec9")
        async with engine.connect() as c:
            before = {
                t: [
                    row[0]
                    for row in (
                        await c.execute(
                            text(f"SELECT to_jsonb(t) FROM {t} t ORDER BY to_jsonb(t)::text")
                        )
                    ).all()
                ]
                for t in tables
            }
        assert (
            before["chat_bindings"] and before["work_attempts"] and before["employee_credentials"]
        )
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.connect() as c:
            for table in tables:
                after = [
                    row[0]
                    for row in (
                        await c.execute(
                            text(f"SELECT to_jsonb(t) FROM {table} t ORDER BY to_jsonb(t)::text")
                        )
                    ).all()
                ]
                for row in after:
                    extra = (
                        ("legal_name", "inn", "contact_name", "contact_email", "contact_phone")
                        if table == "management_companies"
                        else ("invitation_id",)
                        if table == "auth_challenges"
                        else ()
                    )
                    for key in extra:
                        assert row.pop(key) is None
                assert sorted(after, key=str) == sorted(before[table], key=str), table
            for table in (
                "company_onboarding_requests",
                "employee_invitations",
                "house_management_requests",
            ):
                assert await c.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        async with engine.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO company_onboarding_requests"
                    "(id,legal_name,short_name,inn,contact_name,status,submitted_at) "
                    "VALUES (:id,'Migration company','MC','7700000000','Test','submitted',now())"
                ),
                {"id": uuid4()},
            )
        await engine.dispose()
        with pytest.raises(AssertionError, match="Administrative onboarding history retained"):
            await migrate(url, "downgrade", "1c5baa831ec9")
        async with engine.connect() as c:
            assert await c.scalar(text("SELECT count(*) FROM company_onboarding_requests")) == 1
            assert (
                await c.scalar(text("SELECT count(*) FROM tickets WHERE id=:id"), {"id": UUID(tid)})
                == 1
            )
    finally:
        await container.engine.dispose()
        await engine.dispose()
        async with admin.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
