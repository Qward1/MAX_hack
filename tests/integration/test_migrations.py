"""Upgrade an actual C0.1 schema, preserve records, and exercise rollback safely."""

import asyncio
import os
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine
from domsignal.settings import Settings
from tests.integration.migration_columns import without_added_columns


async def migrate(url: str, *args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *args,
        env={**os.environ, "DATABASE_URL": url},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0, output.decode(errors="replace")


async def test_c01_upgrade_backfill_downgrade_and_clean_upgrade(
    integration_settings: Settings,
) -> None:
    name = f"a15_migration_{uuid4().hex}"
    base_url = make_url(integration_settings.database_url)
    url = base_url.set(database=name).render_as_string(hide_password=False)
    admin = create_engine(integration_settings.database_url)
    async with admin.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    try:
        await migrate(url, "upgrade", "20260917_0001")
        user, house, other, incident, report, membership = [uuid4() for _ in range(6)]
        values = dict(
            user=user,
            house=house,
            other=other,
            incident=incident,
            report=report,
            membership=membership,
        )
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO users(id, display_name) VALUES (:user, 'legacy')"), values
            )
            await conn.execute(
                text("""
                INSERT INTO houses(id, name, address, is_demo) VALUES
                (:house, 'legacy demo', 'synthetic demo address', true),
                (:other, 'legacy unverified', 'synthetic unverified address', false)
            """),
                values,
            )
            await conn.execute(
                text("""
                INSERT INTO house_memberships(id,user_id,house_id,role,evidence_source)
                VALUES (:membership,:user,:house,'admin','demo_seed')
            """),
                values,
            )
            await conn.execute(
                text("""
                INSERT INTO incidents(id,house_id,category,title,description,status)
                VALUES (:incident,:house,'water','original title','original text','open')
            """),
                values,
            )
            await conn.execute(
                text("""
                INSERT INTO reports(id,incident_id,house_id,author_id,category,description,
                                    classification_mode,provenance)
                VALUES (:report,:incident,:house,:user,'water','original report','manual','api')
            """),
                values,
            )
        await migrate(url, "upgrade", "head")
        await migrate(url, "upgrade", "head")  # reproducible/idempotent
        await migrate(url, "check")
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("""
                SELECT i.id, i.description, i.management_id, hm.house_id, hm.is_demo, mc.is_demo
                FROM incidents i JOIN house_managements hm ON hm.id=i.management_id
                JOIN management_companies mc ON mc.id=hm.tenant_id WHERE i.id=:incident
            """),
                    values,
                )
            ).one()
            assert row == (incident, "original text", house, house, True, True)
            resident = (
                await conn.execute(
                    text("""
                SELECT id, source, legacy_role, evidence_source, verification_level, verified_at
                FROM resident_memberships
            """)
                )
            ).one()
            assert resident == (membership, "demo", "admin", "demo_seed", "unverified", None)
            assert await conn.scalar(text("SELECT count(*) FROM organization_memberships")) == 0
            assert (
                await conn.execute(
                    text("""
                SELECT status, basis_type, is_demo FROM house_managements WHERE house_id=:other
            """),
                    values,
                )
            ).one() == ("suspended", "legacy_unverified", False)
            assert (
                await conn.scalar(text("SELECT description FROM reports WHERE id=:report"), values)
                == "original report"
            )
        await engine.dispose()  # Alembic schema changes invalidate pooled statement caches.
        await migrate(url, "downgrade", "20260917_0001")
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT id, role, evidence_source FROM house_memberships"))
            ).one() == (membership, "admin", "demo_seed")
            assert await conn.scalar(text("SELECT count(*) FROM reports")) == 1
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "downgrade", "base")
        await migrate(url, "upgrade", "head")  # fresh schema too
        await migrate(url, "check")
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


async def test_a15_upgrade_preserves_grants_and_guards_a07_history(
    integration_settings: Settings,
) -> None:
    name = f"a07_migration_{uuid4().hex}"
    base_url = make_url(integration_settings.database_url)
    url = base_url.set(database=name).render_as_string(hide_password=False)
    admin = create_engine(integration_settings.database_url)
    async with admin.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    try:
        await migrate(url, "upgrade", "20260918_0002")
        user, house, tenant, management, grant = [uuid4() for _ in range(5)]
        values = dict(user=user, house=house, tenant=tenant, management=management, grant=grant)
        async with engine.begin() as conn:
            for sql in [
                "INSERT INTO users(id,display_name) VALUES (:user,'A15 preserved')",
                "INSERT INTO houses(id,name,address) VALUES (:house,'A15','A15 synthetic')",
                "INSERT INTO management_companies(id,name) VALUES (:tenant,'A15 company')",
                "INSERT INTO house_managements(id,house_id,tenant_id,valid_from) "
                "VALUES (:management,:house,:tenant,now()-interval '1 day')",
                "INSERT INTO organization_memberships(id,user_id,tenant_id,role) "
                "VALUES (:grant,:user,:tenant,'company_admin')",
            ]:
                await conn.execute(text(sql), values)
            before = (
                await conn.execute(
                    text(
                        f"SELECT {without_added_columns('organization_memberships')} "
                        "FROM organization_memberships t"
                    )
                )
            ).all()
        await engine.dispose()
        await migrate(url, "upgrade", "head")
        await migrate(url, "check")
        async with engine.begin() as conn:
            assert (
                await conn.execute(
                    text(
                        f"SELECT {without_added_columns('organization_memberships')} "
                        "FROM organization_memberships t"
                    )
                )
            ).all() == before
            assert await conn.scalar(text("SELECT count(*) FROM chat_bindings")) == 0
            await conn.execute(
                text(
                    "INSERT INTO max_chats(id,max_chat_id,type,last_seen_at) "
                    "VALUES (:id,'-999','chat',now())"
                ),
                {"id": uuid4()},
            )
        await engine.dispose()
        with pytest.raises(AssertionError, match="pre-A07 backup"):
            await migrate(url, "downgrade", "20260918_0002")
        async with engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM max_chats")) == 1
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
