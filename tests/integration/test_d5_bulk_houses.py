"""D5 §4.1 (аудит Р-1): дома УК пачкой — PostgreSQL и HTTP. Данные синтетические."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from domsignal.db.models import (
    HouseManagement,
    HouseManagementRequest,
    HouseRoutingProfile,
    ManagementCompany,
)
from domsignal.tools.seed_tickets import seed_id
from tests.integration.test_administration import APP, application, env, post  # noqa: F401

BATCH = "/api/v1/platform/house-management-requests/approve-batch"
REGION = {"region_code": "RU-TA", "municipality_code": "kazan", "territory_policy": "mixed"}
#: Одна дата на модуль: повтор с тем же ключом отправляет то же тело.
VALID_FROM = datetime.now(UTC).isoformat()


def addresses(count: int) -> list[str]:
    tag = uuid4().hex[:6]
    return [f"Казань, Пакетная улица {tag}, {number}" for number in range(1, count + 1)]


async def submit(ctx, items: list[str], key: str | None = None, expected: int = 201):
    return await post(
        ctx["admin"],
        f"/api/v1/companies/{seed_id('alpha')}/house-management-requests/batch",
        {
            "addresses": items,
            "requested_valid_from": VALID_FROM,
            "basis_text": "Договоры управления, список из реестра УК",
        },
        expected,
        key=key,
    )


def batch(ids: list[str], **changes: object) -> dict[str, object]:
    return {
        "request_ids": ids,
        "valid_from": datetime.now(UTC).isoformat(),
        "reason": "Управление проверено по реестру",
        **REGION,
        **changes,
    }


async def test_admin_pastes_a_list_and_platform_approves_it_in_one_action(env):  # noqa: F811
    listed = addresses(12)
    submitted = await submit(env, [*listed, listed[0].upper(), "  "])
    assert submitted["created"] == 12
    outcomes = [item["outcome"] for item in submitted["items"]]
    assert outcomes.count("duplicate") == 1, "регистр и пробелы не различаются"
    ids = [item["request_id"] for item in submitted["items"] if item["request_id"]]

    result = await post(env["platform"], BATCH, batch(ids))
    assert (result["approved"], result["already_approved"], result["failed"]) == (12, 0, 0)
    houses = {UUID(item["house_id"]) for item in result["items"]}
    assert len(houses) == 12
    async with env["container"].session_factory() as db:
        profiles = list(
            await db.scalars(
                select(HouseRoutingProfile).where(HouseRoutingProfile.house_id.in_(houses))
            )
        )
        assert {(p.region_code, p.municipality_code) for p in profiles} == {("RU-TA", "kazan")}
        assert len(profiles) == 12
        managed = await db.scalar(
            select(func.count())
            .select_from(HouseManagement)
            .where(HouseManagement.house_id.in_(houses))
        )
        assert managed == 12

    # Повтор с тем же регионом — «уже одобрена», без новых домов и управлений.
    again = await post(env["platform"], BATCH, batch(ids))
    assert (again["approved"], again["already_approved"], again["failed"]) == (0, 12, 0)
    assert {UUID(item["house_id"]) for item in again["items"]} == houses
    # Дома уже под управлением УК — вторая вставка того же списка их пропускает.
    repeat = await submit(env, listed[:3])
    assert [item["outcome"] for item in repeat["items"]] == ["already_managed"] * 3


async def test_partial_failure_keeps_the_rest_of_the_batch(env):  # noqa: F811
    listed = addresses(3)
    submitted = await submit(env, listed)
    ids = [item["request_id"] for item in submitted["items"]]
    # Одну заявку платформа уже отклонила — одобрить её пачкой нельзя.
    await post(
        env["platform"],
        f"/api/v1/platform/house-management-requests/{ids[1]}/reject",
        {"reason": "Нет договора управления"},
    )
    missing = str(uuid4())
    result = await post(env["platform"], BATCH, batch([*ids, missing]))
    by_id = {item["request_id"]: item for item in result["items"]}
    assert by_id[ids[0]]["outcome"] == "approved"
    assert by_id[ids[2]]["outcome"] == "approved"
    assert by_id[ids[1]]["outcome"] == "conflict"
    assert by_id[missing]["outcome"] == "not_found"
    assert (result["approved"], result["failed"]) == (2, 2)


async def test_management_period_conflict_is_reported_per_house(env):  # noqa: F811
    # Дом уже под управлением другой УК — пересечение периода, как при одиночном одобрении.
    listed = addresses(2)
    first = await submit(env, listed)
    ids = [item["request_id"] for item in first["items"]]
    await post(env["platform"], BATCH, batch(ids[:1]))
    other = await post(
        env["foreign"],
        f"/api/v1/companies/{seed_id('beta')}/house-management-requests/batch",
        {
            "addresses": [listed[0]],
            "requested_valid_from": datetime.now(UTC).isoformat(),
            "basis_text": "Спорный адрес",
        },
        201,
    )
    foreign_id = other["items"][0]["request_id"]
    result = await post(env["platform"], BATCH, batch([foreign_id, ids[1]]))
    by_id = {item["request_id"]: item for item in result["items"]}
    assert by_id[foreign_id]["outcome"] == "conflict"
    assert "Период пересекается" in by_id[foreign_id]["message"]
    assert by_id[ids[1]]["outcome"] == "approved"


async def test_batch_needs_a_known_region_and_is_platform_only(env):  # noqa: F811
    submitted = await submit(env, addresses(1))
    ids = [item["request_id"] for item in submitted["items"]]
    problem = await post(env["platform"], BATCH, batch(ids, region_code="RU-XX"), 422)
    assert [error["field"] for error in problem["field_errors"]] == ["region_code"]
    for client in ("admin", "operator"):
        response = await env[client].post(
            BATCH, json=batch(ids), headers={"Idempotency-Key": str(uuid4())}
        )
        assert response.status_code in {401, 403}
    old = batch(ids, valid_from=(datetime.now(UTC) - timedelta(days=5)).isoformat())
    await post(env["platform"], BATCH, old, 409)
    # Ничего не одобрено.
    async with env["container"].session_factory() as db:
        row = await db.get(HouseManagementRequest, UUID(ids[0]))
        assert row is not None and row.status == "submitted"


async def test_idempotent_list_submission(env):  # noqa: F811
    listed = addresses(4)
    key = str(uuid4())
    first = await submit(env, listed, key=key)
    second = await submit(env, listed, key=key)
    assert first == second
    other = await env["admin"].post(
        f"/api/v1/companies/{seed_id('alpha')}/house-management-requests/batch",
        json={
            "addresses": listed[:1],
            "requested_valid_from": datetime.now(UTC).isoformat(),
            "basis_text": "Другое тело",
        },
        headers={"Idempotency-Key": key},
    )
    assert other.status_code == 409
    too_many = await env["admin"].post(
        f"/api/v1/companies/{seed_id('alpha')}/house-management-requests/batch",
        json={
            "addresses": addresses(201),
            "requested_valid_from": datetime.now(UTC).isoformat(),
            "basis_text": "Слишком длинный список",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert too_many.status_code == 422


async def test_addresses_of_an_approved_company_application_become_house_requests(env):  # noqa: F811
    listed = addresses(3)
    obj = await application(
        env,
        {**APP, "inn": "7709876543", "house_addresses": [*listed, listed[0]]},
    )
    await post(
        env["platform"],
        f"/api/v1/platform/company-applications/{obj}/approve",
        {"reason": "Проверено вручную"},
    )
    async with env["container"].session_factory() as db:
        company = await db.scalar(
            select(ManagementCompany).where(ManagementCompany.inn == "7709876543")
        )
        assert company is not None
        rows = list(
            await db.scalars(
                select(HouseManagementRequest).where(
                    HouseManagementRequest.source_application_id == UUID(obj)
                )
            )
        )
    assert sorted(row.requested_address for row in rows) == sorted(listed)
    assert {row.company_id for row in rows} == {company.id}
    assert {row.status for row in rows} == {"submitted"}
    views = (await env["platform"].get("/api/v1/platform/house-management-requests")).json()
    imported = [view for view in views if view.get("source_application_id") == obj]
    assert len(imported) == 3
    # Платформа одобряет все дома УК одним действием.
    result = await post(env["platform"], BATCH, batch([str(row.id) for row in rows]))
    assert result["approved"] == 3
