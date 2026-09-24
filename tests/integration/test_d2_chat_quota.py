"""D2 · CHAT-QUOTA-2026-09-26 на PostgreSQL: слоты, гонка активаций, освобождение.

Тот же стенд, что у A-07 (CB-01…CB-22): настоящие вебхуки, PostgreSQL и
детерминированный двойник MAX. Квоту задают сервисом платформы.
"""

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import func, select

from domsignal.bot.chat_provider import ChatMember
from domsignal.db.models import (
    ChatBinding,
    ChatQuotaGrant,
    ConnectionRequest,
    ManagementCompany,
)
from domsignal.services.chat_quota import QUOTA_EXCEEDED, ChatQuotaService, quota_state
from tests.integration.test_chat_bindings import Harness, cb  # noqa: F401 - фикстура стенда A-07

ENTRANCE = {"scope_type": "entrance", "scope_value": "2"}


async def set_quota(harness: Harness, company: str, limit: int | None) -> None:
    async with harness.container.session_factory() as session, session.begin():
        await ChatQuotaService().set_limit(
            session,
            actor_id=harness.ids["alice"],
            company_id=harness.ids[company],
            limit=limit,
            reason="Тестовая квота",
        )


async def state(harness: Harness, company: str = "alpha"):
    async with harness.container.session_factory() as session:
        return await quota_state(session, harness.ids[company])


async def active(harness: Harness) -> int:
    return await harness.scalar(
        select(func.count()).select_from(ChatBinding).where(ChatBinding.status == "active")
    )


async def detected(harness: Harness, chat: str, connector: int, scope=None):
    """Запрос подключения, найденный в MAX и готовый к подтверждению УК."""
    harness.fake.configure(chat, connector=str(connector))
    request = await harness.initiate(scope=scope)
    await harness.detect(request, chat, connector)
    await harness.drain()
    return request


async def test_quota_view_on_initiate_shows_remaining(cb):  # noqa: F811
    await set_quota(cb, "alpha", 2)
    request = await cb.initiate()
    assert request["quota"] == {
        "limit": 2,
        "used": 0,
        "remaining": 2,
        "over_limit": False,
        "exhausted": False,
    }


async def test_race_for_the_last_slot_activates_exactly_one(cb):  # noqa: F811
    await set_quota(cb, "alpha", 1)
    cb.fake.admins["-102"] = (ChatMember("102", True),)
    first = await detected(cb, "-101", 101)
    second = await detected(cb, "-102", 102, ENTRANCE)
    responses = await asyncio.gather(cb.approve(first), cb.approve(second))
    assert sorted(r.status_code for r in responses) == [200, 409]
    refused = next(r for r in responses if r.status_code == 409)
    assert refused.headers["content-type"].startswith("application/problem+json")
    assert refused.json()["code"] == QUOTA_EXCEEDED
    assert "1 из 1" in refused.json()["detail"]
    assert await active(cb) == 1
    async with cb.container.session_factory() as session:
        rows = list(await session.scalars(select(ConnectionRequest)))
    losers = [r for r in rows if r.status != "completed"]
    assert len(losers) == 1 and losers[0].last_error_code == QUOTA_EXCEEDED
    # Запрос не активирован и не сброшен: после расширения его можно подтвердить.
    assert losers[0].status in {"max_verified", "awaiting_approval"}
    await set_quota(cb, "alpha", 2)
    loser = first if str(losers[0].id) == first["id"] else second
    again = await cb.approve(loser)
    assert again.status_code == 200, again.text
    assert await active(cb) == 2


async def test_many_parallel_activations_never_exceed_quota(cb):  # noqa: F811
    await set_quota(cb, "alpha", 2)
    requests = []
    for index, chat in enumerate(("-111", "-112", "-113", "-114")):
        connector = 120 + index
        cb.fake.admins[chat] = (ChatMember(str(connector), True),)
        requests.append(
            await detected(
                cb, chat, connector, {"scope_type": "entrance", "scope_value": str(index)}
            )
        )
    responses = await asyncio.gather(*[cb.approve(r) for r in requests])
    assert sorted(r.status_code for r in responses) == [200, 200, 409, 409]
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {QUOTA_EXCEEDED}
    assert await active(cb) == 2


async def test_repeated_bot_added_and_approve_do_not_spend_a_second_slot(cb):  # noqa: F811
    await set_quota(cb, "alpha", 1)
    request, binding = await cb.bind()
    await cb.webhook("bot_added", chat="-101", actor=101, is_channel=False)
    await cb.webhook("bot_added", chat="-101", actor=101, is_channel=False)
    await cb.drain()
    repeat = await cb.approve(request)
    assert repeat.status_code == 200 and repeat.json()["id"] == binding["id"]
    assert await active(cb) == 1
    current = await state(cb)
    assert (current.used, current.remaining, current.exhausted) == (1, 0, True)
    # Слоты исчерпаны: новый запрос не создаётся, кабинет предлагает расширение.
    response = await cb.client.post(
        f"/api/v1/houses/{cb.ids['a1']}/chat-connections",
        json=ENTRANCE,
        headers=cb.headers["alice"],
    )
    assert response.status_code == 409 and response.json()["code"] == QUOTA_EXCEEDED


async def test_bot_removed_and_revoke_release_the_slot(cb):  # noqa: F811
    await set_quota(cb, "alpha", 1)
    await cb.bind()
    await cb.webhook("bot_removed")
    assert (await state(cb)).used == 0
    cb.fake.admins["-102"] = (ChatMember("102", True),)
    request = await detected(cb, "-102", 102, ENTRANCE)
    response = await cb.approve(request)
    assert response.status_code == 200, response.text
    assert (await state(cb)).used == 1
    async with cb.container.session_factory() as session, session.begin():
        await cb.container.chat_connections.revoke(
            session, binding_id=UUID(response.json()["id"]), actor_id=cb.ids["alice"]
        )
    assert (await state(cb)).used == 0
    assert (await state(cb)).remaining == 1


async def test_lowering_quota_keeps_chats_and_blocks_new_ones(cb):  # noqa: F811
    await set_quota(cb, "alpha", 2)
    await cb.bind()
    cb.fake.admins["-102"] = (ChatMember("102", True),)
    await cb.approve(await detected(cb, "-102", 102, ENTRANCE))
    assert await active(cb) == 2
    await set_quota(cb, "alpha", 1)
    assert await active(cb) == 2  # снижение не отключает чаты
    current = await state(cb)
    assert current.over_limit and current.exhausted and current.remaining == 0
    view = await cb.client.get(
        f"/api/v1/companies/{cb.ids['alpha']}/chat-quota", headers=cb.headers["alice"]
    )
    assert view.status_code == 200
    assert view.json()["quota"] == {
        "limit": 1,
        "used": 2,
        "remaining": 0,
        "over_limit": True,
        "exhausted": True,
    }
    assert [g["kind"] for g in view.json()["grants"]][:2] == ["adjustment", "adjustment"]
    response = await cb.client.post(
        f"/api/v1/houses/{cb.ids['a1']}/chat-connections",
        json={"scope_type": "entrance", "scope_value": "9"},
        headers=cb.headers["alice"],
    )
    assert response.status_code == 409 and response.json()["code"] == QUOTA_EXCEEDED


async def test_quota_is_isolated_between_companies(cb):  # noqa: F811
    await set_quota(cb, "alpha", 1)
    await set_quota(cb, "beta", 1)
    await cb.bind()
    # Чат beta занимает слот beta, а не alpha.
    await cb.bind("-102", "b1", "bob", 102)
    assert (await state(cb, "alpha")).used == 1
    assert (await state(cb, "beta")).used == 1
    foreign = await cb.client.get(
        f"/api/v1/companies/{cb.ids['alpha']}/chat-quota", headers=cb.headers["bob"]
    )
    assert foreign.status_code == 404
    assert str(cb.ids["a1"]) not in foreign.text


async def test_suspended_company_connects_no_new_chats(cb):  # noqa: F811
    cb.fake.configure("-101")
    request = await cb.initiate()
    await cb.detect(request)
    await cb.drain()
    async with cb.container.session_factory() as session, session.begin():
        company = await session.get(ManagementCompany, cb.ids["alpha"])
        company.status = "suspended"
    response = await cb.approve(request)
    assert response.status_code in {403, 404, 409}
    assert await active(cb) == 0
    blocked = await cb.client.post(
        f"/api/v1/houses/{cb.ids['a1']}/chat-connections",
        json=ENTRANCE,
        headers=cb.headers["alice"],
    )
    assert blocked.status_code in {403, 404, 409}


@pytest.mark.parametrize("limit", [0])
async def test_zero_quota_blocks_the_first_chat(cb, limit):  # noqa: F811
    await set_quota(cb, "alpha", limit)
    response = await cb.client.post(
        f"/api/v1/houses/{cb.ids['a1']}/chat-connections", json={}, headers=cb.headers["alice"]
    )
    assert response.status_code == 409 and response.json()["code"] == QUOTA_EXCEEDED
    assert "0 из 0" in response.json()["detail"]


async def test_company_without_grants_is_unlimited(cb):  # noqa: F811
    assert await cb.scalar(select(func.count()).select_from(ChatQuotaGrant)) == 0
    current = await state(cb)
    assert current.limit is None and not current.exhausted
    await cb.bind()
    await cb.bind("-102")
    assert await active(cb) == 2
