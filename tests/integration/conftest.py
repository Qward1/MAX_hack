from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import text

from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import AppEnvironment, Settings
from domsignal.tools.seed_demo import seed


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.fail("DATABASE_URL is required for PostgreSQL integration tests")
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url=database_url,
        session_secret="integration-session-secret",
        max_transport="recording",
        static_dir="missing",
        _env_file=None,
    )


@pytest_asyncio.fixture(autouse=True)
async def reset_database(integration_settings: Settings) -> None:
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    async with factory() as session, session.begin():
        await session.execute(
            text(
                # `ai_call_budget` перечислен явно: у него нет внешних ключей,
                # поэтому CASCADE его не захватывает и счётчик протёк бы между тестами.
                "TRUNCATE auth_rate_limits, max_destination_limits, chat_bindings, "
                "chat_connection_requests, max_chats, "
                "outbox_messages, jobs, inbox_receipts, idempotency_records, "
                "ai_call_budget, appeal_drafts, route_outcomes, explicit_intakes, "
                "app_sessions, reports, incidents, resident_memberships, "
                "house_assignments, organization_memberships, "
                "house_managements, management_companies, houses, users CASCADE"
            )
        )
    await engine.dispose()
    await seed(integration_settings)
