"""D1 §1: житель — участник домового чата (RESIDENT-BY-CHAT-2026-09-25).

Основание — текущее участие в чате с активной привязкой: событие `user_added`
или точечная проверка `GET /chats/{id}/members?user_ids=`. Данные синтетические,
MAX — детерминированный двойник.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import select, update

from domsignal.db.models import ChatMemberCheck, NotificationDelivery, ResidentMembership, User
from tests.integration.passive_harness import (
    CHAT_1,
    CHAT_2,
    build_harness,
    ms,
    passive_settings,
)

#: Новые люди из домовых чатов: у ДомСигнала о них ничего нет.
NEWCOMER, STRANGER = 731, 732


@pytest_asyncio.fixture
async def d1(integration_settings: Any) -> Any:
    harness, _ = await build_harness(passive_settings(integration_settings))
    try:
        yield harness
    finally:
        await harness.client.aclose()
        await harness.container.aclose()


async def login(h: Any, max_id: int) -> dict[str, str]:
    """Проверенный вход в mini app: пользователь с MAX id и тестовой сессией."""
    alias = f"d1-{max_id}"
    async with h.container.session_factory() as session, session.begin():
        user = await session.scalar(select(User).where(User.max_user_id == str(max_id)))
        if user is None:
            user = User(id=uuid4(), display_name="Синтетический житель", max_user_id=str(max_id))
            session.add(user)
        user.demo_alias = alias
        user.max_identity_verified_at = datetime.now(UTC)
    async with h.container.session_factory() as session:
        auth = await h.container.session_service.issue_test_session(session, alias=alias)
    return {"Authorization": "Bearer " + auth.access_token}


async def houses(h: Any, headers: dict[str, str]) -> list[str]:
    response = await h.client.get("/api/v1/me", headers=headers)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["houses"]]


async def member_event(
    h: Any, kind: str, *, chat: str, actor: int, at: datetime | None = None
) -> Any:
    return await h.webhook(
        {
            "update_type": kind,
            "timestamp": ms(at or datetime.now(UTC)),
            "chat_id": int(chat),
            "user": {"user_id": actor},
            "is_channel": False,
        }
    )


async def rows(h: Any, max_id: int) -> list[ResidentMembership]:
    return await h.all(
        select(ResidentMembership)
        .join(User, User.id == ResidentMembership.user_id)
        .where(User.max_user_id == str(max_id))
        .order_by(ResidentMembership.created_at)
    )


def calls(h: Any, chat: str) -> int:
    return sum(1 for method, chat_id in h.fake.calls if method == "members" and chat_id == chat)


# ------------------------------------------------------------------ проверка


async def test_a_chat_member_gets_the_house_and_a_leaver_loses_it(d1: Any) -> None:
    binding = await d1.bind()
    d1.fake.members[CHAT_1] = {str(NEWCOMER)}
    headers = await login(d1, NEWCOMER)

    assert await houses(d1, headers) == [str(d1.ids["h1"])]
    [row] = await rows(d1, NEWCOMER)
    assert (row.source, row.chat_binding_id, row.status) == ("chat_member", binding, "active")
    assert row.expires_at - row.checked_at == timedelta(hours=24)
    board = await d1.client.get(f"/api/v1/houses/{d1.ids['h1']}/incidents", headers=headers)
    assert board.status_code == 200

    await member_event(d1, "user_removed", chat=CHAT_1, actor=NEWCOMER)
    assert await houses(d1, headers) == []
    [row] = await rows(d1, NEWCOMER)
    assert (row.status, row.end_reason) == ("revoked", "user_removed")  # история остаётся
    board = await d1.client.get(f"/api/v1/houses/{d1.ids['h1']}/incidents", headers=headers)
    assert board.status_code == 404


async def test_user_added_creates_the_membership_without_any_api_call(d1: Any) -> None:
    await d1.bind()
    before = calls(d1, CHAT_1)
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER)
    headers = await login(d1, NEWCOMER)
    assert await houses(d1, headers) == [str(d1.ids["h1"])]
    assert calls(d1, CHAT_1) == before  # событие — основание, проверка не нужна


async def test_a_repeated_event_keeps_one_membership(d1: Any) -> None:
    await d1.bind()
    at = datetime.now(UTC)
    first = await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER, at=at)
    again = await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER, at=at)
    assert again["duplicate"] is True and first["event_id"] == again["event_id"]
    later = at + timedelta(seconds=5)
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER, at=later)
    [row] = await rows(d1, NEWCOMER)
    # Время события MAX — в миллисекундах.
    assert row.status == "active" and row.checked_at == later.replace(
        microsecond=later.microsecond // 1000 * 1000
    )


async def test_a_late_join_event_does_not_undo_a_newer_leave(d1: Any) -> None:
    await d1.bind()
    now = datetime.now(UTC)
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER, at=now - timedelta(minutes=2))
    await member_event(d1, "user_removed", chat=CHAT_1, actor=NEWCOMER, at=now)
    # Событие вступления, пришедшее позже выхода, но датированное раньше.
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER, at=now - timedelta(minutes=1))
    assert [row.status for row in await rows(d1, NEWCOMER)] == ["revoked"]


async def test_a_max_error_grants_nothing_new_and_is_not_repeated_for_15_minutes(d1: Any) -> None:
    await d1.bind()
    d1.fake.members[CHAT_1] = {str(NEWCOMER)}
    d1.fake.failures[CHAT_1] = "5xx"
    headers = await login(d1, NEWCOMER)
    assert await houses(d1, headers) == []
    assert await houses(d1, headers) == []
    assert calls(d1, CHAT_1) == 1  # не чаще одного вызова на пару за 15 минут
    check = await d1.scalar(select(ChatMemberCheck))
    assert check.outcome == "error"

    # Через 15 минут — новая проверка; MAX ответил — доступ есть.
    del d1.fake.failures[CHAT_1]
    async with d1.container.session_factory() as session, session.begin():
        await session.execute(
            update(ChatMemberCheck).values(checked_at=datetime.now(UTC) - timedelta(minutes=16))
        )
    assert await houses(d1, headers) == [str(d1.ids["h1"])]


async def test_a_max_error_keeps_the_previous_result_until_it_expires(d1: Any) -> None:
    await d1.bind()
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER)
    headers = await login(d1, NEWCOMER)
    d1.fake.failures[CHAT_1] = "5xx"
    assert await houses(d1, headers) == [str(d1.ids["h1"])]  # срок не истёк — вызова нет
    assert calls(d1, CHAT_1) == 0

    # Срок истёк, MAX недоступен: нового доступа нет, запись не удаляется.
    async with d1.container.session_factory() as session, session.begin():
        await session.execute(
            update(ResidentMembership).values(
                checked_at=datetime.now(UTC) - timedelta(hours=25),
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
        await session.execute(
            update(ChatMemberCheck).values(checked_at=datetime.now(UTC) - timedelta(hours=25))
        )
    assert await houses(d1, headers) == []
    assert [row.status for row in await rows(d1, NEWCOMER)] == ["active"]


async def test_two_houses_are_isolated(d1: Any) -> None:
    await d1.bind()
    await d1.bind(chat=CHAT_2, house="h2", admin="admin2")
    d1.fake.members[CHAT_2] = {str(NEWCOMER)}
    headers = await login(d1, NEWCOMER)
    assert await houses(d1, headers) == [str(d1.ids["h2"])]
    foreign = await d1.client.get(f"/api/v1/houses/{d1.ids['h1']}/incidents", headers=headers)
    assert foreign.status_code == 404
    # Событие в чате второго дома не даёт доступ к первому.
    await member_event(d1, "user_added", chat=CHAT_2, actor=STRANGER)
    stranger = await login(d1, STRANGER)
    assert await houses(d1, stranger) == [str(d1.ids["h2"])]


async def test_a_suspended_or_revoked_binding_stops_chat_membership_at_once(d1: Any) -> None:
    binding = await d1.bind()
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER)
    headers = await login(d1, NEWCOMER)
    assert await houses(d1, headers) == [str(d1.ids["h1"])]

    await d1.lifecycle("bot_removed", chat=CHAT_1, actor=701)
    assert await houses(d1, headers) == []
    [row] = await rows(d1, NEWCOMER)
    assert row.status == "active" and row.chat_binding_id == binding  # основание просто не в силе


async def test_a_revoked_binding_stops_chat_membership(d1: Any) -> None:
    binding = await d1.bind()
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER)
    headers = await login(d1, NEWCOMER)
    async with d1.container.session_factory() as session, session.begin():
        await d1.container.chat_connections.revoke(
            session, binding_id=binding, actor_id=d1.ids["admin1"]
        )
    assert await houses(d1, headers) == []


async def test_a_button_from_another_chat_grants_nothing(d1: Any) -> None:
    b1 = await d1.bind()
    b2 = await d1.bind(chat=CHAT_2, house="h2", admin="admin2")
    await d1.deliver()
    refs = {
        row.chat_binding_id: row.launch_ref
        for row in await d1.all(
            select(NotificationDelivery).where(
                NotificationDelivery.purpose == "chat_reading_notice"
            )
        )
    }
    assert set(refs) == {b1, b2}
    d1.container.resident_access.check_all_max_chats = 0  # только подсказанный чат
    d1.fake.members[CHAT_1] = {str(NEWCOMER)}
    await login(d1, NEWCOMER)
    user_id = (await rows_user(d1, NEWCOMER)).id

    # Кнопка из чужого чата: проверяется чат №2, где человека нет.
    await d1.container.resident_access.refresh(user_id, launch_ref=refs[b2])
    assert calls(d1, CHAT_2) == 1 and calls(d1, CHAT_1) == 0
    assert await rows(d1, NEWCOMER) == []
    # Кнопка своего чата: доступ дал ответ MAX, а не ссылка.
    await d1.container.resident_access.refresh(user_id, launch_ref=refs[b1])
    [row] = await rows(d1, NEWCOMER)
    assert row.chat_binding_id == b1
    # Выдуманная ссылка — ничего не проверяется.
    await d1.container.resident_access.refresh(user_id, launch_ref="c_" + "x" * 32)
    assert calls(d1, CHAT_2) == 1


async def test_over_the_limit_only_known_chats_are_checked(d1: Any) -> None:
    await d1.bind()
    await d1.bind(chat=CHAT_2, house="h2", admin="admin2")
    d1.container.resident_access.check_all_max_chats = 1
    d1.fake.members[CHAT_1] = {str(NEWCOMER)}
    headers = await login(d1, NEWCOMER)
    assert await houses(d1, headers) == []  # две привязки > 1: чаты не угадываются
    assert calls(d1, CHAT_1) == calls(d1, CHAT_2) == 0
    # Автор реплики в чате №1 — кандидат по псевдониму дома (без новых текстов).
    await d1.say("Добрый день, соседи", chat=CHAT_1, actor=NEWCOMER)
    assert await houses(d1, headers) == [str(d1.ids["h1"])]
    assert calls(d1, CHAT_1) == 1 and calls(d1, CHAT_2) == 0


async def rows_user(h: Any, max_id: int) -> User:
    user = await h.scalar(select(User).where(User.max_user_id == str(max_id)))
    assert user is not None
    return user


async def test_the_webhook_never_creates_access_for_a_bot_or_an_unbound_chat(d1: Any) -> None:
    await member_event(d1, "user_added", chat=CHAT_1, actor=NEWCOMER)  # чат не подключён
    assert await rows(d1, NEWCOMER) == []
    await d1.bind()
    await d1.webhook(
        {
            "update_type": "user_added",
            "timestamp": ms(datetime.now(UTC)),
            "chat_id": int(CHAT_1),
            "user": {"user_id": 799, "is_bot": True},
        }
    )
    assert await rows(d1, 799) == []
    assert isinstance(d1.ids["h1"], UUID)


async def test_a_category_report_from_a_chat_member_is_accepted(d1: Any) -> None:
    """Прежний `/report <код> <текст>`: автор — участник чата по ответу MAX."""
    from domsignal.db.models import Report

    await d1.bind()
    d1.fake.members[CHAT_1] = {str(NEWCOMER)}
    await d1.say("/report elevator Лифт во втором подъезде стоит", actor=NEWCOMER)
    await d1.say("/report elevator Лифт в третьем подъезде стоит", actor=STRANGER)
    await d1.drain_all()
    reports = await d1.all(select(Report))
    assert len(reports) == 1  # не участник чата — сообщение не принято
    [row] = await rows(d1, NEWCOMER)
    assert row.source == "chat_member"
    assert await rows(d1, STRANGER) == []
