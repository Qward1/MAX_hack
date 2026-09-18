"""A-15 MT-01..MT-10: real PostgreSQL, independent Alpha/Beta security dataset."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from domsignal.db.models import (
    House,
    HouseAssignment,
    HouseManagement,
    Incident,
    ManagementCompany,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.main import create_app
from domsignal.services.context import ScopeState
from domsignal.services.management import ManagementService
from domsignal.settings import Settings


@pytest_asyncio.fixture
async def dataset(integration_settings: Settings) -> AsyncIterator[dict]:
    app = create_app(integration_settings)
    container = app.state.container
    ids = {
        name: uuid4()
        for name in (
            "alpha",
            "beta",
            "a1",
            "a2",
            "b1",
            "ma1",
            "ma2",
            "mb1",
            "alice",
            "bob",
            "carol",
            "dave",
            "eve",
            "unassigned",
            "beta_admin",
            "superadmin",
        )
    }
    async with container.session_factory() as session, session.begin():
        for name in ("alpha", "beta"):
            session.add(ManagementCompany(id=ids[name], name=name))
        for name in ("a1", "a2", "b1"):
            session.add(House(id=ids[name], name=name, address=f"Synthetic {name}"))
        for name in (
            "alice",
            "bob",
            "carol",
            "dave",
            "eve",
            "unassigned",
            "beta_admin",
            "superadmin",
        ):
            session.add(
                User(
                    id=ids[name],
                    display_name=name,
                    demo_alias=name,
                    max_user_id=f"test-{name}",
                    platform_role="superadmin" if name == "superadmin" else None,
                )
            )
        await session.flush()
        for house, tenant in (("a1", "alpha"), ("a2", "alpha"), ("b1", "beta")):
            session.add(
                HouseManagement(
                    id=ids[f"m{house}"],
                    house_id=ids[house],
                    tenant_id=ids[tenant],
                    valid_from=datetime.now(UTC) - timedelta(days=30),
                    basis_type="test_fixture",
                )
            )
        for user, tenant, role in (
            ("alice", "alpha", "company_admin"),
            ("bob", "alpha", "operator"),
            ("unassigned", "alpha", "operator"),
            ("beta_admin", "beta", "company_admin"),
        ):
            session.add(OrganizationMembership(user_id=ids[user], tenant_id=ids[tenant], role=role))
        await session.flush()
        session.add(
            HouseAssignment(user_id=ids["bob"], management_id=ids["ma1"], role="responsible")
        )
        for user, house in (("carol", "a1"), ("dave", "b1"), ("eve", "a1"), ("eve", "b1")):
            session.add(ResidentMembership(user_id=ids[user], house_id=ids[house], source="manual"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {}
        for name in (
            "alice",
            "bob",
            "carol",
            "dave",
            "eve",
            "unassigned",
            "beta_admin",
            "superadmin",
        ):
            async with container.session_factory() as session:
                token = await container.session_service.issue_test_session(session, alias=name)
            headers[name] = {"Authorization": f"Bearer {token.access_token}"}
        incidents = {}
        for house, user in (("a1", "carol"), ("a2", "alice"), ("b1", "dave")):
            response = await client.post(
                "/api/v1/reports",
                json={
                    "house_id": str(ids[house]),
                    "category": "water",
                    "description": f"Private synthetic description for {house}",
                },
                headers={**headers[user], "Idempotency-Key": f"fixture-report-{house}"},
            )
            assert response.status_code == 201, response.text
            incidents[house] = response.json()["incident"]["id"]
        yield {
            "ids": ids,
            "headers": headers,
            "incidents": incidents,
            "client": client,
            "container": container,
        }
    await container.engine.dispose()


async def board(d: dict, user: str, house: str):
    return await d["client"].get(
        f"/api/v1/houses/{d['ids'][house]}/incidents", headers=d["headers"][user]
    )


async def detail(d: dict, user: str, house: str):
    return await d["client"].get(
        f"/api/v1/incidents/{d['incidents'][house]}", headers=d["headers"][user]
    )


async def test_mt01_tenant_isolation(dataset: dict) -> None:
    d = dataset
    assert (await board(d, "alice", "a1")).status_code == 200
    assert (await board(d, "alice", "a2")).status_code == 200
    assert (await board(d, "alice", "b1")).status_code == 404
    assert (await detail(d, "alice", "b1")).status_code == 404
    me = (await d["client"].get("/api/v1/me", headers=d["headers"]["alice"])).json()
    assert {h["id"] for h in me["houses"]} == {str(d["ids"]["a1"]), str(d["ids"]["a2"])}


async def test_mt02_same_tenant_assignment(dataset: dict) -> None:
    assert (await detail(dataset, "bob", "a1")).status_code == 200
    assert (await board(dataset, "bob", "a2")).status_code == 404
    assert (await detail(dataset, "bob", "a2")).status_code == 404
    assert (await board(dataset, "unassigned", "a1")).status_code == 404
    for user in ("unassigned", "superadmin"):
        me = (await dataset["client"].get("/api/v1/me", headers=dataset["headers"][user])).json()
        assert me["houses"] == []  # Platform role is deliberately no read-all grant.


async def test_mt03_resident(dataset: dict) -> None:
    assert (await board(dataset, "carol", "a1")).status_code == 200
    assert (await detail(dataset, "carol", "a1")).status_code == 200
    assert (await board(dataset, "carol", "b1")).status_code == 404
    denied = await dataset["client"].post(
        "/api/v1/reports",
        json={
            "house_id": str(dataset["ids"]["b1"]),
            "category": "water",
            "description": "Attempt to write into a foreign house",
        },
        headers={**dataset["headers"]["carol"], "Idempotency-Key": "foreign-write-test"},
    )
    assert denied.status_code == 404
    assert (await board(dataset, "dave", "b1")).json()["page"]["total"] == 1


async def test_mt04_multi_house_context(dataset: dict) -> None:
    d = dataset
    for house, tenant in (("a1", "alpha"), ("b1", "beta"), ("a1", "alpha")):
        assert (await board(d, "eve", house)).status_code == 200
        assert (await detail(d, "eve", house)).status_code == 200
        async with d["container"].session_factory() as session:
            ctx = await d["container"].membership_service.require_house(
                session,
                user_id=d["ids"]["eve"],
                house_id=d["ids"][house],
            )
            assert ctx.tenant_id.value == d["ids"][tenant]
            assert ctx.management_id.value == d["ids"][f"m{house}"]
            assert ctx.resident_access
            assert ctx.chat_binding_id.state == ScopeState.NOT_APPLICABLE


async def test_mt05_idor(dataset: dict) -> None:
    denied = await detail(dataset, "carol", "b1")
    missing = await dataset["client"].get(
        f"/api/v1/incidents/{uuid4()}", headers=dataset["headers"]["carol"]
    )
    assert denied.status_code == missing.status_code == 404
    assert "Private synthetic" not in denied.text
    assert {k: v for k, v in denied.json().items() if k != "trace_id"} == {
        k: v for k, v in missing.json().items() if k != "trace_id"
    }


async def test_mt06_client_context_is_not_authority(dataset: dict) -> None:
    d = dataset
    for user in ("carol", "alice", "bob"):
        response = await d["client"].get(
            f"/api/v1/incidents/{d['incidents']['b1']}",
            params={
                "tenant_id": str(d["ids"]["beta"]),
                "management_id": str(d["ids"]["mb1"]),
                "chat_id": "123",
                "role": "company_admin",
                "permissions": "incident.read",
            },
            headers=d["headers"][user],
        )
        assert response.status_code == 404
    for extra in ("tenant_id", "management_id", "role", "permissions", "chat_id"):
        response = await d["client"].post(
            "/api/v1/reports",
            json={
                "house_id": str(d["ids"]["a1"]),
                "category": "water",
                "description": "Another report",
                extra: str(d["ids"]["beta"]),
            },
            headers={**d["headers"]["carol"], "Idempotency-Key": "spoofing-test-key"},
        )
        assert response.status_code == 422
    # Even with two legitimate houses a mismatching house selector is not authority.
    response = await d["client"].get(
        f"/api/v1/incidents/{d['incidents']['a1']}",
        params={"house_id": str(d["ids"]["b1"])},
        headers=d["headers"]["eve"],
    )
    assert response.status_code == 404


async def test_mt07_management_switch(dataset: dict) -> None:
    d = dataset
    async with d["container"].session_factory() as session, session.begin():
        new = await ManagementService().switch(
            session, management_id=d["ids"]["ma1"], tenant_id=d["ids"]["beta"], at=datetime.now(UTC)
        )
        new_id = new.id
    assert (await detail(d, "beta_admin", "a1")).status_code == 404
    assert (await board(d, "beta_admin", "a1")).json()["items"] == []
    assert (await board(d, "alice", "a1")).status_code == 404
    assert (await board(d, "bob", "a1")).status_code == 404
    assert (await board(d, "carol", "a1")).status_code == 200
    # Retry of an old receipt never leaks or silently creates a second effect.
    retry = await d["client"].post(
        "/api/v1/reports",
        json={
            "house_id": str(d["ids"]["a1"]),
            "category": "water",
            "description": "Private synthetic description for a1",
        },
        headers={**d["headers"]["carol"], "Idempotency-Key": "fixture-report-a1"},
    )
    assert retry.status_code == 404
    created = await d["client"].post(
        "/api/v1/reports",
        json={
            "house_id": str(d["ids"]["a1"]),
            "category": "water",
            "description": "New management report",
        },
        headers={**d["headers"]["carol"], "Idempotency-Key": "after-management-switch"},
    )
    assert created.status_code == 201
    async with d["container"].session_factory() as session:
        old = await session.get(Incident, d["incidents"]["a1"])
        current = await session.get(Incident, created.json()["incident"]["id"])
        assert old.management_id == d["ids"]["ma1"]
        assert current.management_id == new_id
        assert (
            await session.scalar(
                select(HouseAssignment).where(HouseAssignment.management_id == new_id)
            )
            is None
        )
    items = (await board(d, "beta_admin", "a1")).json()["items"]
    assert [i["id"] for i in items] == [created.json()["incident"]["id"]]


async def test_mt08_revoke_without_login(dataset: dict) -> None:
    d = dataset
    assert (await detail(d, "bob", "a1")).status_code == 200
    async with d["container"].session_factory() as session, session.begin():
        await session.execute(
            update(HouseAssignment)
            .where(HouseAssignment.user_id == d["ids"]["bob"])
            .values(status="revoked")
        )
    assert (await board(d, "bob", "a1")).status_code == 404
    assert (await detail(d, "bob", "a1")).status_code == 404


async def test_mt09_composite_fk_and_immutable_history(dataset: dict) -> None:
    d = dataset
    async with d["container"].session_factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    Incident(
                        house_id=d["ids"]["a1"],
                        management_id=d["ids"]["mb1"],
                        category="water",
                        title="bad",
                        description="bad",
                    )
                )
                await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(
                    update(Incident)
                    .where(Incident.id == d["incidents"]["a1"])
                    .values(house_id=d["ids"]["b1"], management_id=d["ids"]["mb1"])
                )
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(
                    update(HouseManagement)
                    .where(HouseManagement.id == d["ids"]["ma1"])
                    .values(tenant_id=d["ids"]["beta"])
                )


async def test_mt10_overlap_domain_and_database(dataset: dict) -> None:
    d = dataset
    async with d["container"].session_factory() as session:
        with pytest.raises(ValueError, match="overlap"):
            async with session.begin():
                await ManagementService().create(
                    session,
                    house_id=d["ids"]["a1"],
                    tenant_id=d["ids"]["beta"],
                    valid_from=datetime.now(UTC),
                )
        for end in (None, datetime.now(UTC) + timedelta(days=1)):
            with pytest.raises(IntegrityError):
                async with session.begin():
                    session.add(
                        HouseManagement(
                            house_id=d["ids"]["a1"],
                            tenant_id=d["ids"]["beta"],
                            valid_from=datetime.now(UTC),
                            valid_to=end,
                        )
                    )
                    await session.flush()
        # Half-open adjacent finite/future periods are valid; not current yet.
        at = datetime.now(UTC) + timedelta(days=1)
        async with session.begin():
            await ManagementService().switch(
                session, management_id=d["ids"]["ma1"], tenant_id=d["ids"]["beta"], at=at
            )
    assert (await board(d, "alice", "a1")).status_code == 200
    assert (await board(d, "beta_admin", "a1")).status_code == 404


@pytest.mark.parametrize(
    "change", ["resident_revoked", "resident_expired", "org_revoked", "tenant_suspended"]
)
async def test_access_bases_are_rechecked(dataset: dict, change: str) -> None:
    d = dataset
    user = "carol" if change.startswith("resident") else "bob"
    async with d["container"].session_factory() as session, session.begin():
        if change.startswith("resident"):
            values = (
                {"status": "revoked"}
                if change == "resident_revoked"
                else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
            await session.execute(
                update(ResidentMembership)
                .where(ResidentMembership.user_id == d["ids"][user])
                .values(**values)
            )
        elif change == "org_revoked":
            await session.execute(
                update(OrganizationMembership)
                .where(OrganizationMembership.user_id == d["ids"][user])
                .values(status="revoked")
            )
        else:
            await session.execute(
                update(ManagementCompany)
                .where(ManagementCompany.id == d["ids"]["alpha"])
                .values(status="suspended")
            )
    assert (await detail(d, user, "a1")).status_code == 404


async def test_worker_rechecks_revoked_access(dataset: dict) -> None:
    d = dataset
    event = {
        "event_id": "revoke-worker",
        "event_type": "diagnostic.report",
        "external_user_id": "test-bob",
        "house_id": str(d["ids"]["a1"]),
        "category": "water",
        "description": "Pending report before revoke",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    assert (
        await d["client"].post("/max/replay", json=event, headers=d["headers"]["bob"])
    ).status_code == 202
    async with d["container"].session_factory() as session, session.begin():
        await session.execute(
            update(HouseAssignment)
            .where(HouseAssignment.user_id == d["ids"]["bob"])
            .values(status="revoked")
        )
    from domsignal.services.errors import ResourceNotFound
    from domsignal.worker.handlers import WorkerHandlers

    handler = WorkerHandlers(
        session_factory=d["container"].session_factory,
        report_service=d["container"].report_service,
        transport=d["container"].transport,
    )
    with pytest.raises(ResourceNotFound):
        await handler.inbound_report(event)


async def test_concurrent_management_insert_cannot_bypass_exclusion(dataset: dict) -> None:
    d = dataset
    house = uuid4()
    factory = d["container"].session_factory
    async with factory() as session, session.begin():
        session.add(House(id=house, name="race", address=f"Synthetic race {house}"))
    async with factory() as first, factory() as second:
        first.add(
            HouseManagement(
                house_id=house, tenant_id=d["ids"]["alpha"], valid_from=datetime.now(UTC)
            )
        )
        await first.flush()
        second.add(
            HouseManagement(
                house_id=house, tenant_id=d["ids"]["beta"], valid_from=datetime.now(UTC)
            )
        )
        pending = asyncio.create_task(second.flush())
        await first.commit()
        with pytest.raises(IntegrityError):
            await asyncio.wait_for(pending, timeout=5)
        await second.rollback()
