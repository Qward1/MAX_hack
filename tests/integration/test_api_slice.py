from __future__ import annotations

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from domsignal.db.models import House, HouseMembership, User
from domsignal.db.session import create_engine, create_session_factory
from domsignal.main import create_app
from domsignal.settings import Settings
from domsignal.tools.seed_demo import DEMO_HOUSE_ID, OTHER_HOUSE_ID, seed


async def token(client: AsyncClient, actor: str = "demo") -> str:
    response = await client.post("/api/v1/auth/test-session", json={"actor": actor})
    assert response.status_code == 200
    return response.json()["access_token"]


async def test_seed_is_idempotent(integration_settings: Settings) -> None:
    await seed(integration_settings)
    engine = create_engine(integration_settings.database_url)
    factory = create_session_factory(engine)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 2
        assert await session.scalar(select(func.count()).select_from(House)) == 2
        assert await session.scalar(select(func.count()).select_from(HouseMembership)) == 2
    await engine.dispose()


async def test_report_persists_idempotently_and_is_house_scoped(
    integration_settings: Settings,
) -> None:
    app = create_app(integration_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        auth = {"Authorization": f"Bearer {await token(client)}"}
        payload = {
            "house_id": str(DEMO_HOUSE_ID),
            "category": "elevator",
            "description": "Лифт не открывает двери на первом этаже",
            "classification_mode": "manual",
        }
        headers = {**auth, "Idempotency-Key": "report-test-0001"}
        created = await client.post("/api/v1/reports", json=payload, headers=headers)
        assert created.status_code == 201
        repeated = await client.post("/api/v1/reports", json=payload, headers=headers)
        assert repeated.status_code == 201
        assert repeated.json()["report_id"] == created.json()["report_id"]

        changed = {**payload, "description": "У этой же команды уже другое тело"}
        conflict = await client.post("/api/v1/reports", json=changed, headers=headers)
        assert conflict.status_code == 409
        assert conflict.headers["content-type"].startswith("application/problem+json")

        incident_id = created.json()["incident"]["id"]
        detail = await client.get(f"/api/v1/incidents/{incident_id}", headers=auth)
        assert detail.status_code == 200
        board = await client.get(f"/api/v1/houses/{DEMO_HOUSE_ID}/incidents", headers=auth)
        assert board.json()["page"]["total"] == 1

        outsider_auth = {"Authorization": f"Bearer {await token(client, 'outsider')}"}
        forbidden = await client.get(
            f"/api/v1/houses/{DEMO_HOUSE_ID}/incidents", headers=outsider_auth
        )
        assert forbidden.status_code == 403
        query_cannot_grant_access = await client.get(
            f"/api/v1/houses/{OTHER_HOUSE_ID}/incidents?house_id={DEMO_HOUSE_ID}",
            headers=auth,
        )
        assert query_cannot_grant_access.status_code == 403

    restarted = create_app(integration_settings)
    async with AsyncClient(
        transport=ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        auth = {"Authorization": f"Bearer {await token(client)}"}
        board = await client.get(f"/api/v1/houses/{DEMO_HOUSE_ID}/incidents", headers=auth)
        assert board.json()["page"]["total"] == 1
