"""A-16 additive migration over populated A-15/A-07, with guarded downgrade."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine
from tests.integration.test_migrations import migrate


async def test_tk26_populated_a07_migration_retains_all_history(integration_settings) -> None:
    name = f"a16_migration_{uuid4().hex}"
    url = (
        make_url(integration_settings.database_url)
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    admin = create_engine(integration_settings.database_url)
    async with admin.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
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
            "chat",
            "request",
            "binding",
            "ticket",
        )
    }
    tables = [
        "users",
        "houses",
        "management_companies",
        "house_managements",
        "incidents",
        "reports",
        "resident_memberships",
        "organization_memberships",
        "house_assignments",
        "max_chats",
        "chat_connection_requests",
        "chat_bindings",
    ]
    try:
        await migrate(url, "upgrade", "20260918_0003")
        async with engine.begin() as conn:
            for sql in [
                "INSERT INTO users(id,display_name) VALUES (:user,'A16 fixture')",
                "INSERT INTO houses(id,name,address) "
                "VALUES (:house,'A16','A16 migration synthetic')",
                "INSERT INTO management_companies(id,name) VALUES (:tenant,'A16 fixture company')",
                "INSERT INTO house_managements(id,tenant_id,house_id,valid_from) "
                "VALUES (:management,:tenant,:house,now()-interval '1 day')",
                "INSERT INTO resident_memberships(id,user_id,house_id) "
                "VALUES (:report,:user,:house)",
                "INSERT INTO organization_memberships(id,user_id,tenant_id,role) "
                "VALUES (:report,:user,:tenant,'operator')",
                "INSERT INTO house_assignments(id,user_id,management_id,role) "
                "VALUES (:report,:user,:management,'responsible')",
                "INSERT INTO "
                "incidents(id,management_id,house_id,category,title,description,status) "
                "VALUES (:incident,:management,:house,'water','Original',"
                "'Private original','open')",
                "INSERT INTO reports(id,incident_id,house_id,author_id,category,description,"
                "classification_mode,provenance) "
                "VALUES (:report,:incident,:house,:user,'water','Original report',"
                "'manual','max_group')",
                "INSERT INTO max_chats(id,max_chat_id,type,last_seen_at,binding_version) "
                "VALUES (:chat,'-900001','chat',now(),1)",
                "INSERT INTO "
                "chat_connection_requests(id,management_id,house_id,initiated_by_user_id,"
                "token_hash,expires_at,status,scope_type) "
                "VALUES (:request,:management,:house,:user,repeat('a',64),now(),"
                "'completed','house')",
                "INSERT INTO "
                "chat_bindings(id,max_chat_id,connection_request_id,house_id,management_id,"
                "scope_type,status,binding_version,activated_at) "
                "VALUES (:binding,'-900001',:request,:house,:management,'house','active',1,now())",
            ]:
                await conn.execute(text(sql), ids)
            before = {
                table: (await conn.execute(text(f"SELECT row_to_json(t) FROM {table} t"))).all()
                for table in tables
            }
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.begin() as conn:
            for table in tables:
                expr = (
                    "to_jsonb(t) - 'ticket_intake_enabled'"
                    if table == "house_managements"
                    else "to_jsonb(t) - 'max_identity_verified_at'"
                    if table == "users"
                    else "row_to_json(t)"
                )
                after = (await conn.execute(text(f"SELECT {expr} FROM {table} t"))).all()
                if table == "management_companies":
                    for row in after:
                        for key in (
                            "legal_name",
                            "inn",
                            "contact_name",
                            "contact_email",
                            "contact_phone",
                        ):
                            assert row[0].pop(key) is None
                assert after == before[table]
            assert await conn.scalar(text("SELECT count(*) FROM tickets")) == 0
            assert (
                await conn.scalar(text("SELECT ticket_intake_enabled FROM house_managements"))
                is False
            )
            assert await conn.scalar(text("SELECT count(*) FROM outbox_messages")) == 0
            await conn.execute(
                text(
                    "INSERT INTO tickets(id,incident_id,management_id,house_id,status,version,"
                    "resume_status,routing_reason,source,created_by) "
                    "VALUES "
                    "(:ticket,:incident,:management,:house,'new',1,'new','test','max_group',:user)"
                ),
                ids,
            )
        await engine.dispose()
        with pytest.raises(AssertionError, match="pre-A16 backup"):
            await migrate(url, "downgrade", "20260918_0003")
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM tickets")) == 1
            assert await conn.scalar(text("SELECT count(*) FROM chat_bindings")) == 1
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
