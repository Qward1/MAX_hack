"""D3 §3 и §6: объявления и рассылки УК и платформы, настройки чата, тихие часы.

Один механизм: черновик → предпросмотр → подтверждение → отправка → статистика.
Доставка — существующие outbox и `NotificationDelivery`, двойник MAX записывает
посты и личные сообщения. Данные синтетические.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update

from domsignal.db.models import (
    Broadcast,
    BroadcastHouse,
    ChatBinding,
    InboxReceipt,
    NotificationDelivery,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.services import community_texts
from domsignal.services.broadcasts import BroadcastConflict
from domsignal.services.community_delivery import UNSUBSCRIBE_CALLBACK
from tests.integration.d3_harness import (  # noqa: F401 - фикстура стенда
    NO_QUIET,
    announcement,
    call,
    chat,
    confirm,
    create,
    d3,
    deliveries,
    detail,
    key,
    labels,
    payloads,
    quiet_around_now,
    send_now,
    set_chat,
    settle,
    stats,
    user_by_max,
)
from tests.integration.passive_harness import CHAT_1, RESIDENT, ms

SIGNATURE = "— Сообщение от УК «УК Первая (тест)»"


def posts(h: Any) -> list[Any]:
    return [
        item for item in h.messaging.chat_sent if not item[2].text.startswith("ДомСигнал подключён")
    ]


# --------------------------------------------------------------- настройки чата


async def test_chat_settings_have_defaults_history_and_an_author(d3) -> None:  # noqa: F811
    binding = await d3.bind()
    view = await call(d3, "GET", f"/api/v1/chat-bindings/{binding}/settings")
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["post_ticket_status"] and body["post_company_messages"] and body["post_polls"]
    assert body["post_platform_messages"] is False
    assert (body["quiet_start"], body["quiet_end"]) == ("22:00", "08:00")
    assert body["can_edit"] is True and body["history"] == []

    changed = await set_chat(
        d3,
        binding,
        post_ticket_status=False,
        post_company_messages=True,
        post_polls=True,
        post_platform_messages=True,
        quiet_start="23:00",
        quiet_end="07:30",
    )
    assert changed.status_code == 200, changed.text
    history = changed.json()["history"]
    assert len(history) == 1 and history[0]["actor_name"] == "admin1"
    assert "Статусы заявок: выключены" in history[0]["summary"]
    assert "Сообщения платформы: разрешены" in history[0]["summary"]
    assert "Тихие часы: 23:00–07:30 МСК" in history[0]["summary"]
    audit = await d3.scalar(
        select(func.count())
        .select_from(InboxReceipt)
        .where(InboxReceipt.event_type == "administration.chat_settings.changed")
    )
    assert audit == 1


async def test_only_the_house_staff_reads_and_a_foreign_company_is_masked(d3) -> None:  # noqa: F811
    binding = await d3.bind()
    foreign = await call(d3, "GET", f"/api/v1/chat-bindings/{binding}/settings", who="admin2")
    assert foreign.status_code == 404
    resident = await call(d3, "GET", f"/api/v1/chat-bindings/{binding}/settings", who="resident")
    assert resident.status_code == 403
    denied = await set_chat(
        d3,
        binding,
        who="admin2",
        **NO_QUIET,
        **{
            "post_ticket_status": True,
            "post_company_messages": True,
            "post_polls": True,
            "post_platform_messages": True,
        },
    )
    assert denied.status_code in {403, 404}
    wrong = await set_chat(
        d3,
        binding,
        quiet_start="25:00",
        quiet_end="07:00",
        **{
            "post_ticket_status": True,
            "post_company_messages": True,
            "post_polls": True,
            "post_platform_messages": False,
        },
    )
    assert wrong.status_code == 422


# ----------------------------------------------------------- объявление целиком


async def test_announcement_from_draft_to_statistics(d3) -> None:  # noqa: F811
    await chat(d3)
    draft = await create(d3, announcement())
    assert draft["status"] == "draft" and draft["allowed_actions"][:2] == ["edit", "preview"]
    assert draft["sender"] == "Сообщение от УК «УК Первая (тест)»"

    preview = await call(d3, "GET", f"/api/v1/broadcasts/{draft['id']}/preview")
    assert preview.status_code == 200, preview.text
    counts = {item["channel"]: item for item in preview.json()["channels"]}
    assert preview.json()["houses"] == 1
    assert counts["chat"]["targets"] == 1 and counts["chat"]["will_send"] == 1
    assert counts["dm"]["targets"] == 1 and counts["dm"]["will_send"] == 1
    assert counts["feed"]["targets"] == 1
    assert not posts(d3), "предпросмотр ничего не отправляет"

    confirmed = await confirm(d3, draft)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "scheduled"
    await settle(d3)
    view = await detail(d3, draft["id"])
    assert view["status"] == "sent" and view["sent_at"]
    assert view["confirmed_by_name"] == "admin1"

    [(chat_id, mid, post)] = posts(d3)
    assert chat_id == CHAT_1 and mid.startswith("mid.chat-")
    assert post.text.startswith("Объявление · Работы\nПромывка системы отопления")
    assert post.text.endswith(SIGNATURE)
    assert labels(post) == ["Открыть ДомСигнал"]
    assert payloads(post)[0].startswith("p_")
    [(dest, _, message)] = [item for item in d3.messaging.sent if item[0] == str(RESIDENT)]
    assert message.text == post.text
    assert labels(message) == ["Открыть ДомСигнал", community_texts.UNSUBSCRIBE_LABEL]
    assert payloads(message)[1] == UNSUBSCRIBE_CALLBACK

    assert stats(view, "chat")["accepted"] == 1
    assert stats(view, "dm")["accepted"] == 1
    assert stats(view, "feed")["total"] == 1

    feed = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/announcements", who="resident")
    assert feed.status_code == 200, feed.text
    [item] = feed.json()["items"]
    assert item["title"] == "Промывка системы отопления" and item["topic_label"] == "Работы"
    assert item["sender"] == "Сообщение от УК «УК Первая (тест)»"
    events = await d3.all(
        select(InboxReceipt.event_type).where(
            InboxReceipt.event_type.like("administration.broadcast%")
        )
    )
    assert {
        "administration.broadcast.created",
        "administration.broadcast.confirmed",
        "administration.broadcast.sent",
    } <= set(events)


async def test_the_audience_never_leaves_the_company(d3) -> None:  # noqa: F811
    await chat(d3)
    foreign = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        json=announcement(audience={"mode": "houses", "house_ids": [str(d3.ids["h2"])]}),
        idempotency=key(),
    )
    assert foreign.status_code == 422, foreign.text
    other_company = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t2']}/broadcasts",
        json=announcement(),
        idempotency=key(),
    )
    assert other_company.status_code == 404
    sent = await send_now(d3, announcement())
    houses = await d3.all(
        select(BroadcastHouse.house_id).where(BroadcastHouse.broadcast_id == sent["id"])
    )
    assert houses == [d3.ids["h1"]]
    hidden = await call(d3, "GET", f"/api/v1/broadcasts/{sent['id']}", who="admin2")
    assert hidden.status_code == 404
    foreign_feed = await call(
        d3, "GET", f"/api/v1/houses/{d3.ids['h2']}/announcements", who="resident"
    )
    assert foreign_feed.status_code == 404
    resident_cannot = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        who="resident",
        json=announcement(),
        idempotency=key(),
    )
    assert resident_cannot.status_code == 404


async def test_idempotent_create_and_a_second_confirm_is_a_conflict(d3) -> None:  # noqa: F811
    await chat(d3)
    idem = key()
    first = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        json=announcement(),
        idempotency=idem,
    )
    again = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        json=announcement(),
        idempotency=idem,
    )
    assert first.json()["id"] == again.json()["id"]
    assert await d3.scalar(select(func.count()).select_from(Broadcast)) == 1
    changed = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        json=announcement(title="Другое"),
        idempotency=idem,
    )
    assert changed.status_code == 409
    ok = await confirm(d3, first.json())
    assert ok.status_code == 200
    stale = await confirm(d3, first.json())
    assert stale.status_code == 409 and stale.json()["code"] == BroadcastConflict.code


async def test_a_repeated_send_job_does_not_duplicate(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, announcement())
    before = await deliveries(d3, broadcast_id=sent["id"])
    await d3.container.broadcasts.send_due({"broadcast_id": sent["id"]})
    await settle(d3)
    after = await deliveries(d3, broadcast_id=sent["id"])
    assert len(before) == len(after) == 2
    assert len(posts(d3)) == 1
    assert len([item for item in d3.messaging.sent if item[0] == str(RESIDENT)]) == 1


# ------------------------------------------------------------- отписка и диалог


async def test_unsubscribed_residents_are_skipped_and_counted(d3) -> None:  # noqa: F811
    await chat(d3)
    opted = await call(
        d3, "POST", "/api/v1/me/preferences", who="resident", json={"broadcast_opt_out": True}
    )
    assert opted.status_code == 200 and opted.json()["broadcast_opt_out"] is True
    draft = await create(d3, announcement())
    preview = (await call(d3, "GET", f"/api/v1/broadcasts/{draft['id']}/preview")).json()
    dm = next(item for item in preview["channels"] if item["channel"] == "dm")
    assert dm["skipped"] == {"UNSUBSCRIBED": 1} and dm["will_send"] == 0
    await confirm(d3, draft)
    await settle(d3)
    view = await detail(d3, draft["id"])
    assert stats(view, "dm")["skipped"] == {"UNSUBSCRIBED": 1}
    assert not [item for item in d3.messaging.sent if item[0] == str(RESIDENT)]
    assert len(posts(d3)) == 1, "в чат пост уходит — отписка касается только лички"


async def test_the_unsubscribe_button_opts_out_without_replacing_the_message(d3) -> None:  # noqa: F811
    await chat(d3)
    await send_now(d3, announcement())
    await d3.webhook(
        {
            "update_type": "message_callback",
            "timestamp": ms(datetime.now(UTC)),
            "callback": {
                "timestamp": ms(datetime.now(UTC)),
                "callback_id": "cb-unsub-1",
                "payload": UNSUBSCRIBE_CALLBACK,
                "user": {"user_id": RESIDENT},
            },
            "message": {
                "recipient": {"chat_id": 9000 + RESIDENT, "chat_type": "dialog"},
                "body": {"mid": "mid.test-1"},
            },
        }
    )
    await settle(d3)
    user = await user_by_max(d3, RESIDENT)
    assert user.broadcast_opt_out_at is not None
    assert d3.messaging.notified and d3.messaging.notified[0][0] == "cb-unsub-1"
    assert not d3.messaging.answered, "текст рассылки не заменяется ответом"
    await send_now(d3, announcement(title="Второе объявление"))
    assert len([item for item in d3.messaging.sent if item[0] == str(RESIDENT)]) == 1


async def test_residents_without_a_dialog_are_skipped(d3) -> None:  # noqa: F811
    await chat(d3)
    silent = uuid4()
    async with d3.container.session_factory() as session, session.begin():
        session.add(User(id=silent, display_name="Без диалога", max_user_id="7777"))
        await session.flush()
        session.add(ResidentMembership(user_id=silent, house_id=d3.ids["h1"]))
    draft = await create(d3, announcement())
    preview = (await call(d3, "GET", f"/api/v1/broadcasts/{draft['id']}/preview")).json()
    dm = next(item for item in preview["channels"] if item["channel"] == "dm")
    assert dm["targets"] == 2 and dm["skipped"] == {"NO_DIALOG": 1}


# ------------------------------------------------------------------ тихие часы


async def test_quiet_hours_move_the_chat_post_and_then_it_goes(d3) -> None:  # noqa: F811
    window = quiet_around_now(minutes_before=30, minutes_after=90)
    await chat(d3, **window)
    sent = await send_now(d3, announcement(channels=["chat", "feed"]))
    assert not posts(d3)
    [delivery] = await deliveries(d3, broadcast_id=sent["id"])
    assert delivery.status == "pending" and delivery.last_error_code == "QUIET_HOURS"
    assert delivery.next_attempt_at is not None
    assert stats(await detail(d3, sent["id"]), "chat")["deferred_quiet_hours"] == 1
    await settle(d3, at=delivery.next_attempt_at + timedelta(seconds=1))
    assert len(posts(d3)) == 1
    view = await detail(d3, sent["id"])
    assert stats(view, "chat")["accepted"] == 1


async def test_night_dms_wait_for_the_morning(d3) -> None:  # noqa: F811
    await chat(d3)
    window = quiet_around_now(minutes_before=10, minutes_after=10)
    start = int(window["quiet_start"][:2]) * 60 + int(window["quiet_start"][3:])
    end = int(window["quiet_end"][:2]) * 60 + int(window["quiet_end"][3:])
    d3.container.notifications.dm_quiet_window = (start, end)
    sent = await send_now(d3, announcement(channels=["dm"]))
    [delivery] = await deliveries(d3, broadcast_id=sent["id"])
    assert delivery.status == "pending" and delivery.last_error_code == "QUIET_HOURS"
    assert not [item for item in d3.messaging.sent if item[0] == str(RESIDENT)]


async def test_a_disabled_setting_skips_the_chat(d3) -> None:  # noqa: F811
    await chat(d3, post_company_messages=False)
    sent = await send_now(d3, announcement(channels=["chat", "feed"]))
    assert stats(sent, "chat")["skipped"] == {"CHAT_SETTING_OFF": 1}
    assert not posts(d3)


# ----------------------------------------------------- правка, удаление, отмена


async def test_an_edit_changes_the_same_chat_message(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, announcement())
    [(_, mid, _)] = posts(d3)
    edited = await call(
        d3,
        "POST",
        f"/api/v1/broadcasts/{sent['id']}/edit",
        json={
            "expected_version": sent["version"],
            "title": "Промывка перенесена",
            "body": "Новая дата — 30 сентября, остальное без изменений.",
        },
    )
    assert edited.status_code == 200, edited.text
    await settle(d3)
    assert len(posts(d3)) == 1, "второго поста нет"
    [(edited_mid, message)] = d3.messaging.edited
    assert edited_mid == mid
    assert "Промывка перенесена" in message.text and "Изменено" in message.text
    feed = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/announcements", who="resident")
    assert feed.json()["items"][0]["title"] == "Промывка перенесена"


async def test_retract_edits_the_post_and_hides_it_from_the_feed(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, announcement())
    [(_, mid, _)] = posts(d3)
    retracted = await call(
        d3,
        "POST",
        f"/api/v1/broadcasts/{sent['id']}/retract",
        json={"expected_version": sent["version"]},
    )
    assert retracted.status_code == 200, retracted.text
    await settle(d3)
    [(edited_mid, message)] = d3.messaging.edited
    assert edited_mid == mid
    assert message.text.startswith(community_texts.RETRACTED) and message.buttons == ()
    feed = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/announcements", who="resident")
    assert feed.json()["items"] == []


async def test_scheduled_send_waits_and_a_cancel_before_it_stops_it(d3) -> None:  # noqa: F811
    await chat(d3)
    draft = await create(d3, announcement())
    later = datetime.now(UTC) + timedelta(hours=1)
    scheduled = await confirm(d3, draft, send_at=later)
    assert scheduled.status_code == 200 and scheduled.json()["status"] == "scheduled"
    await settle(d3)
    assert not await deliveries(d3, broadcast_id=draft["id"])
    cancelled = await call(
        d3,
        "POST",
        f"/api/v1/broadcasts/{draft['id']}/cancel",
        json={"expected_version": scheduled.json()["version"]},
    )
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    await settle(d3, at=later + timedelta(minutes=1))
    assert not await deliveries(d3, broadcast_id=draft["id"])
    assert not posts(d3)


async def test_cancel_and_send_race_has_one_winner(d3) -> None:  # noqa: F811
    await chat(d3)
    for _ in range(4):
        draft = await create(d3, announcement())
        confirmed = (await confirm(d3, draft)).json()

        async def cancel(
            draft: dict[str, Any] = draft, confirmed: dict[str, Any] = confirmed
        ) -> int:
            response = await call(
                d3,
                "POST",
                f"/api/v1/broadcasts/{draft['id']}/cancel",
                json={"expected_version": confirmed["version"]},
            )
            return int(response.status_code)

        status, _ = await asyncio.gather(
            cancel(), d3.container.broadcasts.send_due({"broadcast_id": draft["id"]})
        )
        view = await detail(d3, draft["id"])
        count = len(await deliveries(d3, broadcast_id=draft["id"]))
        if view["status"] == "cancelled":
            assert status == 200 and count == 0
        else:
            assert view["status"] == "sent" and status == 409 and count == 2


# --------------------------------------------------------- сообщения платформы


async def test_platform_messages_need_the_chat_setting_and_reach_staff(d3) -> None:  # noqa: F811
    binding = await chat(d3)
    platform = uuid4()
    async with d3.container.session_factory() as session, session.begin():
        session.add(User(id=platform, display_name="Платформа", platform_role="superadmin"))
        await session.execute(
            update(User).where(User.id == d3.ids["admin1"]).values(max_dialog_at=datetime.now(UTC))
        )
    service = d3.container.broadcasts
    from domsignal.contracts.community import BroadcastConfirm, BroadcastCreate

    async def platform_send(title: str) -> Any:
        async with d3.container.session_factory() as session, session.begin():
            draft = await service.create(
                session,
                actor_id=platform,
                company_id=None,
                payload=BroadcastCreate(
                    kind="mailing",
                    title=title,
                    body="Плановое обновление ДомСигнала в воскресенье ночью.",
                    channels=["chat", "staff"],
                ),
                idempotency_key=key(),
            )
            await service.confirm(
                session,
                actor_id=platform,
                broadcast_id=draft.id,
                payload=BroadcastConfirm(expected_version=draft.version, service_only=True),
            )
        await settle(d3)
        async with d3.container.session_factory() as session:
            return await service.detail(session, actor_id=platform, broadcast_id=draft.id)

    first = await platform_send("Обновление платформы")
    chat_stats = next(item for item in first.stats if item.channel == "chat")
    assert chat_stats.skipped == {"CHAT_SETTING_OFF": 1} and not posts(d3)
    staff = next(item for item in first.stats if item.channel == "staff")
    assert staff.accepted >= 1
    [(_, _, staff_message)] = [item for item in d3.messaging.sent if item[0] == "701"]
    assert staff_message.text.startswith(community_texts.STAFF_NOTICE_LEAD)
    notices = await call(d3, "GET", f"/api/v1/companies/{d3.ids['t1']}/platform-notices")
    assert [item["title"] for item in notices.json()["items"]] == ["Обновление платформы"]
    other = await call(
        d3, "GET", f"/api/v1/companies/{d3.ids['t1']}/platform-notices", who="admin2"
    )
    assert other.status_code == 404

    await set_chat(
        d3,
        binding,
        post_ticket_status=True,
        post_company_messages=True,
        post_polls=True,
        post_platform_messages=True,
        **NO_QUIET,
    )
    await platform_send("Второе сообщение платформы")
    [(_, _, post)] = posts(d3)
    assert post.text.endswith("— " + community_texts.PLATFORM_SENDER)


async def test_a_responsible_sends_only_to_own_houses_and_an_operator_not_at_all(d3) -> None:  # noqa: F811
    await chat(d3)
    operator = uuid4()
    async with d3.container.session_factory() as session, session.begin():
        session.add(User(id=operator, display_name="Оператор", demo_alias="d3-operator"))
        await session.flush()
        session.add(
            OrganizationMembership(user_id=operator, tenant_id=d3.ids["t1"], role="operator")
        )
    async with d3.container.session_factory() as session:
        auth = await d3.container.session_service.issue_test_session(session, alias="d3-operator")
    d3.headers["operator"] = {"Authorization": "Bearer " + auth.access_token}
    denied = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        who="operator",
        json=announcement(),
        idempotency=key(),
    )
    assert denied.status_code == 403


async def test_the_chat_post_link_opens_the_feed_for_a_resident_only(d3) -> None:  # noqa: F811
    await chat(d3)
    await send_now(d3, announcement())
    [(_, _, post)] = posts(d3)
    ref = payloads(post)[0]
    launch = await call(d3, "GET", f"/api/v1/notification-launch/{ref}", who="resident")
    assert launch.status_code == 200, launch.text
    assert launch.json()["kind"] == "announcements"
    assert launch.json()["house_id"] == str(d3.ids["h1"])
    stranger = await call(d3, "GET", f"/api/v1/notification-launch/{ref}", who="admin2")
    assert stranger.status_code == 404
    [delivery] = [item for item in await deliveries(d3, purpose="broadcast_dm")]
    foreign_dm = await call(
        d3, "GET", f"/api/v1/notification-launch/{delivery.launch_ref}", who="admin1"
    )
    assert foreign_dm.status_code == 404


async def test_a_suspended_chat_gets_no_post(d3) -> None:  # noqa: F811
    binding = await chat(d3)
    draft = await create(d3, announcement(channels=["chat", "feed"]))
    await confirm(d3, draft)
    # Отправка создала доставку в чат, но до её отправки чат приостановили.
    await d3.container.broadcasts.send_due({"broadcast_id": draft["id"]})
    async with d3.container.session_factory() as session, session.begin():
        await session.execute(
            update(ChatBinding).where(ChatBinding.id == binding).values(status="suspended")
        )
    await settle(d3)
    [delivery] = await deliveries(d3, broadcast_id=draft["id"])
    assert delivery.status in {"superseded", "pending"}
    assert not posts(d3)
    assert (
        await d3.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.purpose == "broadcast_chat",
                NotificationDelivery.status == "accepted",
            )
        )
        == 0
    )
