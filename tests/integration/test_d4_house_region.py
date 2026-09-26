"""D4, В-1: регион дома задаётся при подключении — PostgreSQL и HTTP."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select

from domsignal.db.models import House, HouseManagement, HouseRoutingProfile, InboxReceipt
from domsignal.services.house_region import PROFILE_AUDIT_TYPE
from domsignal.tools.seed_tickets import seed_id
from tests.integration.test_administration import env, post  # noqa: F401 - фикстура

PACKS = "/api/v1/platform/region-packs"


async def house_request(ctx, address: str) -> str:
    request = await post(
        ctx["admin"],
        f"/api/v1/companies/{seed_id('alpha')}/house-management-requests",
        {
            "requested_address": address,
            "requested_valid_from": datetime.now(UTC).isoformat(),
            "basis_text": "Договор управления",
        },
        201,
    )
    return str(request["id"])


def approval(**region: str | None) -> dict[str, object]:
    return {
        "resolution": "new",
        "valid_from": datetime.now(UTC).isoformat(),
        "reason": "Управление проверено",
        **region,
    }


async def approve(ctx, request: str, body: dict[str, object], expected: int = 200):
    return await post(
        ctx["platform"],
        f"/api/v1/platform/house-management-requests/{request}/approve",
        body,
        expected,
    )


async def audits(ctx, house: UUID) -> list[dict[str, object]]:
    async with ctx["container"].session_factory() as db:
        rows = await db.scalars(
            select(InboxReceipt).where(
                InboxReceipt.event_type == PROFILE_AUDIT_TYPE,
                InboxReceipt.payload["house_id"].astext == str(house),
            )
        )
        return [row.payload for row in rows]


async def test_region_packs_come_from_the_loaded_directory(env):  # noqa: F811
    packs = (await env["platform"].get(PACKS)).json()
    by_code = {pack["region_code"]: pack for pack in packs}
    assert {"RU-TA", "RU-MOW"} <= set(by_code)
    assert by_code["RU-MOW"]["timezone"] == "Europe/Moscow"
    assert by_code["RU-MOW"]["municipalities"] == [{"code": "moscow", "name": "Москва"}]
    assert by_code["RU-TA"]["name"] == "Республика Татарстан"
    # Список — только платформе.
    for client in ("admin", "operator", "public"):
        assert (await env[client].get(PACKS)).status_code in {401, 403}


async def test_moscow_house_approved_with_its_region_routes_to_nash_gorod(env):  # noqa: F811
    request = await house_request(env, f"Москва, ул. Проверочная, {uuid4().hex[:6]}")
    result = await approve(
        env, request, approval(region_code="RU-MOW", municipality_code="moscow")
    )
    async with env["container"].session_factory() as db:
        management = await db.get(HouseManagement, UUID(result["management_id"]))
        assert management is not None
        house = management.house_id
        profile = await db.get(HouseRoutingProfile, house)
        assert profile is not None
        assert (profile.region_code, profile.municipality_code, profile.territory_policy) == (
            "RU-MOW",
            "moscow",
            "mixed",
        )
        route, _ = await env["container"].routing.route_for_house(
            db,
            house_id=house,
            subtype="street_lighting.failure",
            location_scope="municipal_territory",
        )
    channels = [channel.id for channel in route.channels]
    assert channels == ["ru_mow_nash_gorod"], channels  # «Наш город», а не ПОС
    [record] = await audits(env, house)
    assert record["previous"] is None
    assert record["profile"] == {
        "region_code": "RU-MOW",
        "municipality_code": "moscow",
        "territory_policy": "mixed",
    }
    assert record["operator"] == "platform:house_request"
    assert record["updated_by"] == str(env["platform_id"])
    # Повтор того же одобрения — тот же ответ, без второго профиля и аудита.
    again = await approve(
        env, request, approval(region_code="RU-MOW", municipality_code="moscow")
    )
    assert again["management_id"] == result["management_id"]
    assert len(await audits(env, house)) == 1


async def test_approval_without_a_known_region_is_refused_and_changes_nothing(env):  # noqa: F811
    request = await house_request(env, f"Без региона, {uuid4().hex[:6]}")
    cases = [
        ({}, "region_code", "Выберите регион дома из справочника"),
        ({"region_code": "RU-XX"}, "region_code", "Такого региона нет"),
        (
            {"region_code": "RU-MOW", "municipality_code": "kazan"},
            "municipality_code",
            "Такого муниципалитета нет",
        ),
    ]
    for region, field, text in cases:
        problem = await approve(env, request, approval(**region), 422)
        assert text in problem["detail"], problem
        assert [error["field"] for error in problem["field_errors"]] == [field]
    async with env["container"].session_factory() as db:
        created = await db.scalar(
            select(func.count()).select_from(HouseManagement).where(
                HouseManagement.basis_reference == request
            )
        )
        assert created == 0
    view = (
        await env["platform"].get(f"/api/v1/platform/house-management-requests/{request}")
    ).json()
    assert view["status"] == "submitted"


async def test_set_region_for_an_existing_house_is_platform_only(env):  # noqa: F811
    house = uuid4()
    async with env["container"].session_factory() as db, db.begin():
        db.add(House(id=house, name="Дом без профиля", address=f"Дом без профиля, {house.hex[:6]}"))
    listed = (await env["platform"].get("/api/v1/platform/houses?offset=0")).json()
    row = next(item for item in listed if item["id"] == str(house))
    assert row["region_code"] is None  # «регион не задан»
    totals = (await env["platform"].get("/api/v1/platform/dashboard?days=7")).json()["totals"]
    assert "houses_without_region" in totals
    path = f"/api/v1/platform/houses/{house}/region"
    body = {"region_code": "RU-TA", "municipality_code": "kazan", "reason": "Адрес в Казани"}
    # Изоляция: сотрудники УК, в том числе администратор, регион дома не задают.
    for client in ("admin", "operator", "foreign"):
        response = await env[client].post(path, json=body, headers={"Idempotency-Key": "k" * 8})
        assert response.status_code in {401, 403}, response.text
    assert await audits(env, house) == []
    await post(env["platform"], path, {**body, "region_code": None}, 422)
    view = await post(env["platform"], path, body)
    assert (view["region_code"], view["municipality_code"], view["territory_policy"]) == (
        "RU-TA",
        "kazan",
        "mixed",
    )
    [record] = await audits(env, house)
    assert (record["operator"], record["reason"]) == ("platform:set_region", "Адрес в Казани")
    missing = await env["platform"].post(
        f"/api/v1/platform/houses/{uuid4()}/region",
        json=body,
        headers={"Idempotency-Key": "k" * 8},
    )
    assert missing.status_code == 404


async def test_version_lists_the_loaded_directory_layers(env):  # noqa: F811
    body = (await env["public"].get("/version")).json()
    assert "region_pack" not in body
    assert body["region_packs"]["_federal"] and body["region_packs"]["RU-MOW"]
    assert set(body["region_packs"]) >= {"_federal", "RU-TA", "RU-MOW"}
