from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
from sqlalchemy import func, select

from domsignal.db.models import House, IdempotencyRecord, Job, Report, ResidentMembership
from domsignal.main import create_app
from domsignal.services.context import ScopeState
from domsignal.services.errors import AccessDenied
from domsignal.settings import Settings
from domsignal.tools.seed_demo import DEMO_HOUSE_ID, DEMO_USER_ID, OTHER_HOUSE_ID, OUTSIDER_USER_ID


async def auth(client: AsyncClient, actor: str = "demo") -> dict[str, str]:
    response = await client.post("/api/v1/auth/test-session", json={"actor": actor})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def payload() -> dict[str, str]:
    return {
        "house_id": str(DEMO_HOUSE_ID),
        "category": "water",
        "description": "Water in entrance 2 floor 5 (free text is not structured location)",
    }


async def test_counts_provenance_and_runtime_schema(integration_settings: Settings) -> None:
    app = create_app(integration_settings)
    container = app.state.container
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {**await auth(client), "Idempotency-Key": "counts-unique-actors"}
        created = await client.post("/api/v1/reports", headers=headers, json=payload())
        assert created.status_code == 201
        incident = created.json()["incident"]
        async with container.session_factory() as session, session.begin():
            # Four reports by one actor must still be one participant.
            for _ in range(3):
                session.add(
                    Report(
                        incident_id=incident["id"],
                        house_id=DEMO_HOUSE_ID,
                        author_id=DEMO_USER_ID,
                        category="water",
                        description="Another report",
                        provenance="api",
                    )
                )
        for path, model in (
            (f"/api/v1/incidents/{incident['id']}", "IncidentDetail"),
            (f"/api/v1/houses/{DEMO_HOUSE_ID}/incidents", "IncidentList"),
        ):
            response = await client.get(path, headers=headers)
            data = response.json()
            Draft202012Validator(
                {
                    "$ref": f"#/components/schemas/{model}",
                    "components": app.openapi()["components"],
                }
            ).validate(data)
            item = data["items"][0] if model == "IncidentList" else data
            assert item["report_count"] == 4
            assert item["participant_count"] == 1
            assert item["allowed_actions"] == []
            assert item["provenance"]["origin"] == "demo" and item["is_demo"]
            assert item["location"] is item["updated_at"] is item["due_at"] is None
            assert not {"route", "appeal", "history"} & item.keys()
        async with container.session_factory() as session, session.begin():
            session.add(
                Report(
                    incident_id=incident["id"],
                    house_id=DEMO_HOUSE_ID,
                    author_id=OUTSIDER_USER_ID,
                    category="water",
                    description="Previously participating actor",
                    provenance="api",
                )
            )
            house = await session.get(House, DEMO_HOUSE_ID)
            assert house is not None
            house.is_demo = False
        detail = (await client.get(f"/api/v1/incidents/{incident['id']}", headers=headers)).json()
        assert detail["participant_count"] == 2 and detail["report_count"] == 5
        assert detail["provenance"]["origin"] == "user_reported"
        # D-03: заглушка DemoRule — только у демо-дома; настоящему дому основание
        # не выдумывается и «Пример данных» не показывается.
        assert detail["rule"] is None
        board = (
            await client.get(f"/api/v1/houses/{DEMO_HOUSE_ID}/incidents", headers=headers)
        ).json()
        assert board["items"][0]["participant_count"] == 2
        capabilities = (await client.get("/api/v1/capabilities")).json()
        me = (await client.get("/api/v1/me", headers=headers)).json()
        assert me["capabilities"] == capabilities["features"]
        assert {
            key: me["capabilities"][key]
            for key in ("group_mode", "miniapp", "photo_analysis", "voice", "admin")
        } == {
            "group_mode": False,
            "miniapp": True,
            "photo_analysis": False,
            "voice": False,
            "admin": True,
        }
    await container.engine.dispose()


async def test_house_context_direct_id_and_untrusted_selectors(
    integration_settings: Settings,
) -> None:
    app = create_app(integration_settings)
    container = app.state.container
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {**await auth(client), "Idempotency-Key": "context-create-key"}
        created = (await client.post("/api/v1/reports", headers=headers, json=payload())).json()
        path = f"/api/v1/incidents/{created['incident']['id']}"
        outsider = await auth(client, "outsider")
        for suffix in (
            "",
            f"?house_id={OTHER_HOUSE_ID}",
            f"?tenant_id={uuid4()}&chat_id=123&start_param=admin&actor_user_id={DEMO_USER_ID}",
        ):
            denied = await client.get(path + suffix, headers=outsider)
            assert denied.status_code in {403, 404}
            assert "description" not in denied.json()
        assert (
            await client.get(path + f"?house_id={OTHER_HOUSE_ID}", headers=headers)
        ).status_code == 404
        async with container.session_factory() as session, session.begin():
            session.add(ResidentMembership(user_id=DEMO_USER_ID, house_id=OTHER_HOUSE_ID))
        # Even access to both houses does not make a mismatched house selector valid.
        assert (
            await client.get(path + f"?house_id={OTHER_HOUSE_ID}", headers=headers)
        ).status_code == 404
        assert (
            await client.get(path + f"?house_id={DEMO_HOUSE_ID}", headers=headers)
        ).status_code == 200
        assert (await client.get(path + f"?house_id={uuid4()}", headers=headers)).status_code == 404
        for extra in (
            {"tenant_id": str(uuid4())},
            {"roles": ["admin"]},
            {"chat_id": "123"},
            {"start_param": "admin"},
        ):
            assert (
                await client.post("/api/v1/reports", headers=headers, json={**payload(), **extra})
            ).status_code == 422
        missing_house = payload()
        del missing_house["house_id"]
        assert (
            await client.post("/api/v1/reports", headers=headers, json=missing_house)
        ).status_code == 422
        async with container.session_factory() as session:
            with pytest.raises(AccessDenied):
                await container.membership_service.require_house(
                    session, user_id=DEMO_USER_ID, house_id=None
                )
            context = await container.membership_service.require_house(
                session, user_id=DEMO_USER_ID, house_id=DEMO_HOUSE_ID
            )
            assert context.actor_user_id == DEMO_USER_ID and context.house_id == DEMO_HOUSE_ID
            assert context.tenant_id.state == context.management_id.state == ScopeState.KNOWN
            assert context.chat_binding_id.state == ScopeState.NOT_APPLICABLE
            assert context.source_chat_id.value is context.binding_version.value is None
            assert context.roles == frozenset({"resident"})
            assert context.permissions == frozenset(
                {"incident.read", "report.create", "work.read", "work.observe"}
            )
        # Current membership is rechecked on direct reads and idempotent retries.
        async with container.session_factory() as session, session.begin():
            membership = await session.scalar(
                select(ResidentMembership).where(
                    ResidentMembership.user_id == DEMO_USER_ID,
                    ResidentMembership.house_id == DEMO_HOUSE_ID,
                )
            )
            await session.delete(membership)
        assert (await client.get(path, headers=headers)).status_code == 404
        assert (
            await client.post("/api/v1/reports", headers=headers, json=payload())
        ).status_code == 404
    await container.engine.dispose()


async def test_legacy_receipt_is_represented_without_legacy_actions(
    integration_settings: Settings,
) -> None:
    app = create_app(integration_settings)
    container = app.state.container
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {**await auth(client), "Idempotency-Key": "legacy-receipt-key"}
        original = (await client.post("/api/v1/reports", headers=headers, json=payload())).json()
        async with container.session_factory() as session, session.begin():
            record = await session.scalar(select(IdempotencyRecord))
            assert record is not None
            record.response_body = {
                "report_id": original["report_id"],
                "incident": {"id": original["incident"]["id"], "allowed_actions": ["view"]},
            }
        retry = await client.post("/api/v1/reports", headers=headers, json=payload())
        assert retry.status_code == 201
        assert retry.json() == original
        async with container.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Report)) == 1
    await container.engine.dispose()


async def test_replay_cannot_impersonate_or_authorize_by_event_metadata(
    integration_settings: Settings,
) -> None:
    app = create_app(integration_settings)
    container = app.state.container
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await auth(client, "outsider")
        event = {
            "event_id": "spoofed-replay",
            "event_type": "diagnostic.report",
            "external_user_id": "demo-max-user",
            **payload(),
            "occurred_at": "2026-09-17T12:00:00Z",
        }
        assert (await client.post("/max/replay", headers=headers, json=event)).status_code == 403
        event["external_user_id"] = "outsider-max-user"
        assert (await client.post("/max/replay", headers=headers, json=event)).status_code == 404
        async with container.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Job)) == 0
    await container.engine.dispose()
