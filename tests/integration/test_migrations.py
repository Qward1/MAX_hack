"""Upgrade an actual C0.1 schema, preserve records, and exercise rollback safely."""

import asyncio
import os
import sys
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url

from domsignal.db.session import create_engine
from domsignal.settings import Settings


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
