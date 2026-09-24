"""D1 §2: открытый доступ к дому (OPEN-HOUSE-ACCESS-2026-09-25).

Переключатель дома включает администратор УК с подтверждением; пока он
включён, любой вошедший через MAX выбирает дом и действует как житель.
Выключение сразу прекращает такой доступ, история и заявки остаются у УК.
"""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import func, select

from domsignal.db.models import (
    House,
    InboxReceipt,
    OrganizationMembership,
    Report,
    ResidentMembership,
    Ticket,
    User,
)
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.onboarding import AdministrationService
from tests.integration.passive_harness import build_harness, passive_settings
from tests.integration.test_d1_chat_membership import houses, login

OUTSIDER = 751
CONFIRM = {"enabled": True, "confirm": True}


@pytest_asyncio.fixture
async def oa(integration_settings: Any) -> Any:
    harness, _ = await build_harness(passive_settings(integration_settings))
    try:
        yield harness
    finally:
        await harness.client.aclose()
        await harness.container.aclose()


def open_url(h: Any, *, company: str = "t1", house: str = "h1") -> str:
    return f"/api/v1/companies/{h.ids[company]}/houses/{h.ids[house]}/open-access"


async def test_open_access_lets_an_outsider_in_and_closing_it_stops_access(oa: Any) -> None:
    outsider = await login(oa, OUTSIDER)
    assert await houses(oa, outsider) == []
    assert (await oa.client.get("/api/v1/open-houses", headers=outsider)).json()["items"] == []

    enabled = await oa.client.post(open_url(oa), json=CONFIRM, headers=oa.headers["admin1"])
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["open_resident_access"] is True
    card = await oa.client.get(
        f"/api/v1/companies/{oa.ids['t1']}/houses/{oa.ids['h1']}", headers=oa.headers["admin1"]
    )
    assert card.json()["open_resident_access"] is True

    listed = (await oa.client.get("/api/v1/open-houses", headers=outsider)).json()["items"]
    assert [(item["id"], item["joined"]) for item in listed] == [(str(oa.ids["h1"]), False)]
    joined = await oa.client.post(f"/api/v1/open-houses/{oa.ids['h1']}/join", headers=outsider)
    assert joined.status_code == 200 and joined.json()["joined"] is True
    again = await oa.client.post(f"/api/v1/open-houses/{oa.ids['h1']}/join", headers=outsider)
    assert again.status_code == 200
    assert await houses(oa, outsider) == [str(oa.ids["h1"])]

    # Житель по открытому доступу сообщает о проблеме: заявка у УК.
    submitted = await oa.client.post(
        f"/api/v1/houses/{oa.ids['h1']}/reports/submit",
        json={"description": "В первом подъезде не работает лифт"},
        headers={**outsider, "Idempotency-Key": "open-access-report-1"},
    )
    assert submitted.status_code in {200, 201}, submitted.text
    ticket_count = await oa.scalar(select(func.count()).select_from(Ticket))
    assert ticket_count == 1

    closed = await oa.client.post(
        open_url(oa), json={"enabled": False}, headers=oa.headers["admin1"]
    )
    assert closed.status_code == 200 and closed.json()["ended_memberships"] == 1
    assert await houses(oa, outsider) == []
    board = await oa.client.get(f"/api/v1/houses/{oa.ids['h1']}/incidents", headers=outsider)
    assert board.status_code == 404
    # Заявка и сообщение остались у УК, членство — в истории.
    assert await oa.scalar(select(func.count()).select_from(Ticket)) == 1
    assert await oa.scalar(select(func.count()).select_from(Report)) == 1
    [row] = await oa.all(
        select(ResidentMembership).where(ResidentMembership.source == "open_access")
    )
    assert (row.status, row.end_reason) == ("revoked", "open_access_closed")
    events = await oa.all(
        select(InboxReceipt.event_type).where(
            InboxReceipt.event_type.like("administration.house.open_access%")
        )
    )
    assert sorted(events) == [
        "administration.house.open_access_disabled",
        "administration.house.open_access_enabled",
    ]

    # Повторное включение не возвращает прежний доступ: дом выбирают заново.
    await oa.client.post(open_url(oa), json=CONFIRM, headers=oa.headers["admin1"])
    assert await houses(oa, outsider) == []


async def test_enabling_requires_the_confirmation(oa: Any) -> None:
    response = await oa.client.post(
        open_url(oa), json={"enabled": True}, headers=oa.headers["admin1"]
    )
    assert response.status_code == 422
    assert (
        await oa.scalar(select(House.open_resident_access).where(House.id == oa.ids["h1"])) is False
    )


async def test_a_foreign_company_cannot_switch_and_gets_a_masked_404(oa: Any) -> None:
    # Администратор второй УК: чужая компания и чужой дом неотличимы от несуществующих.
    foreign = await oa.client.post(open_url(oa), json=CONFIRM, headers=oa.headers["admin2"])
    assert foreign.status_code == 404
    other_house = await oa.client.post(
        open_url(oa, company="t2", house="h1"), json=CONFIRM, headers=oa.headers["admin2"]
    )
    assert other_house.status_code == 404
    # Житель — не сотрудник: 404, а не 403.
    resident = await oa.client.post(open_url(oa), json=CONFIRM, headers=oa.headers["resident"])
    assert resident.status_code == 404
    assert (
        await oa.scalar(select(House.open_resident_access).where(House.id == oa.ids["h1"])) is False
    )


async def test_an_operator_of_the_same_company_gets_403(oa: Any) -> None:
    async with oa.container.session_factory() as session, session.begin():
        session.add(
            OrganizationMembership(
                user_id=oa.ids["resident"], tenant_id=oa.ids["t1"], role="operator"
            )
        )
    response = await oa.client.post(open_url(oa), json=CONFIRM, headers=oa.headers["resident"])
    assert response.status_code == 403


async def test_joining_a_closed_or_unknown_house_is_a_masked_404(oa: Any) -> None:
    outsider = await login(oa, OUTSIDER)
    closed = await oa.client.post(f"/api/v1/open-houses/{oa.ids['h2']}/join", headers=outsider)
    assert closed.status_code == 404
    unknown = await oa.client.post(f"/api/v1/open-houses/{oa.ids['t1']}/join", headers=outsider)
    assert unknown.status_code == 404
    assert closed.json()["code"] == unknown.json()["code"]


async def test_the_platform_sees_all_open_houses_and_can_close_one(oa: Any) -> None:
    await oa.client.post(open_url(oa), json=CONFIRM, headers=oa.headers["admin1"])
    outsider = await login(oa, OUTSIDER)
    await oa.client.post(f"/api/v1/open-houses/{oa.ids['h1']}/join", headers=outsider)
    service = AdministrationService(oa.container.settings)
    async with oa.container.session_factory() as session, session.begin():
        superadmin = User(display_name="Платформа", platform_role="superadmin")
        session.add(superadmin)
        await session.flush()
        listed = await service.platform_open_houses(session)
        assert [(item.house_id, item.company_id) for item in listed] == [
            (oa.ids["h1"], oa.ids["t1"])
        ]
        view = await service.platform_close_open_access(
            session, superadmin.id, oa.ids["h1"], "Проверка платформы"
        )
        assert view.open_resident_access is False and view.ended_memberships == 1
        assert await service.platform_open_houses(session) == []
    assert await houses(oa, outsider) == []
    audit = await oa.scalar(
        select(InboxReceipt).where(
            InboxReceipt.event_type == "administration.house.open_access_closed_by_platform"
        )
    )
    assert audit is not None and audit.payload["reason"] == "Проверка платформы"


async def test_only_a_superadmin_closes_from_the_platform(oa: Any) -> None:
    service = AdministrationService(oa.container.settings)
    async with oa.container.session_factory() as session, session.begin():
        try:
            await service.platform_close_open_access(
                session, oa.ids["admin1"], oa.ids["h1"], "Не платформа"
            )
        except AccessDenied:
            pass
        else:  # pragma: no cover - проверка выше обязана отказать
            raise AssertionError("company admin closed open access from the platform")
    async with oa.container.session_factory() as session, session.begin():
        superadmin = User(display_name="Платформа", platform_role="superadmin")
        session.add(superadmin)
        await session.flush()
        try:
            await service.platform_close_open_access(
                session, superadmin.id, oa.ids["t1"], "Нет такого дома"
            )
        except ResourceNotFound:
            pass
        else:  # pragma: no cover
            raise AssertionError("unknown house was closed")
