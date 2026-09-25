"""Populated actual A-16 head upgrade, clean upgrade and guarded delivery history."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.models import NotificationDelivery
from domsignal.db.session import create_engine, create_session_factory
from tests.integration.migration_columns import without_added_columns
from tests.integration.test_migrations import migrate


async def test_nd_migration_populated_a16_and_history_guard(integration_settings):
    name = "nd_migration_" + uuid4().hex
    url = (
        make_url(integration_settings.database_url)
        .set(database=name)
        .render_as_string(
            hide_password=False,
        )
    )
    admin = create_engine(integration_settings.database_url)
    async with admin.connect() as c:
        c = await c.execution_options(isolation_level="AUTOCOMMIT")
        await c.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    ids = {
        key: uuid4()
        for key in (
            "user",
            "house",
            "tenant",
            "management",
            "incident",
            "report",
            "ticket",
            "event",
            "outbox",
        )
    }
    try:
        await migrate(url, "upgrade", "20260918_0004")
        async with engine.begin() as c:
            for sql in [
                "INSERT INTO users(id,display_name,max_user_id) VALUES (:user,'legacy','123')",
                "INSERT INTO houses(id,name,address) VALUES (:house,'fixture','ND migration')",
                "INSERT INTO management_companies(id,name) VALUES (:tenant,'ND fixture')",
                "INSERT INTO house_managements(id,house_id,tenant_id,valid_from) "
                "VALUES (:management,:house,:tenant,now()-interval '1 day')",
                "INSERT INTO incidents(id,management_id,house_id,category,title,description,status)"
                " "
                "VALUES (:incident,:management,:house,'water','original','private','open')",
                "INSERT INTO reports(id,incident_id,house_id,author_id,category,description,"
                "classification_mode,provenance) "
                "VALUES (:report,:incident,:house,:user,'water','original','manual','api')",
                "INSERT INTO tickets(id,incident_id,management_id,house_id,status,version,"
                "resume_status,routing_reason,source,created_by) "
                "VALUES (:ticket,:incident,:management,:house,'new',1,'new',"
                "'unassigned','api',:user)",
                "INSERT INTO ticket_events(id,ticket_id,actor_id,kind,version,to_status,visibility)"
                " "
                "VALUES (:event,:ticket,:user,'created',1,'new','resident')",
                "INSERT INTO outbox_messages(id,kind,aggregate_id,payload,status,dedupe_key) "
                "VALUES (:outbox,'ticket.notification_intent.v1',:ticket,'{}',"
                "'pending','nd-fixture')",
            ]:
                await c.execute(text(sql), ids)
            tables = ["tickets", "ticket_events", "reports", "outbox_messages"]
            before = {
                t: (await c.execute(text(f"SELECT {without_added_columns(t)} FROM {t} t"))).all()
                for t in tables
            }
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.connect() as c:
            for t in tables:
                after = (
                    await c.execute(text(f"SELECT {without_added_columns(t)} FROM {t} t"))
                ).all()
                assert after == before[t]
            assert (
                await c.execute(text("SELECT max_identity_verified_at FROM users"))
            ).scalar() is None
            assert (
                await c.execute(text("SELECT count(*) FROM notification_deliveries"))
            ).scalar() == 0
        await engine.dispose()
        await migrate(url, "downgrade", "20260918_0004")
        await migrate(url, "upgrade", "head")
        async with create_session_factory(engine)() as s, s.begin():
            s.add(
                NotificationDelivery(
                    outbox_message_id=ids["outbox"],
                    recipient_user_id=ids["user"],
                    ticket_id=ids["ticket"],
                    purpose="ticket_accepted",
                    launch_ref="w_" + "m" * 32,
                    desired_version=1,
                )
            )
        await engine.dispose()
        with pytest.raises(AssertionError, match="pre-delivery backup"):
            await migrate(url, "downgrade", "20260918_0004")
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            c = await c.execution_options(isolation_level="AUTOCOMMIT")
            await c.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
