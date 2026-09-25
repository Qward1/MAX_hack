"""D3 §5: статус заявки в домовом чате и «Меня тоже касается» (B-06).

Одно сообщение бота на заявку, возникшую по решению человека (`/report` в
группе или решение оператора по сигналу); смена статуса и новый участник
правят то же сообщение. Данные синтетические.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from domsignal.bot.messaging import MessagingError
from domsignal.db.models import NotificationDelivery, Report, Ticket
from domsignal.services import community_texts
from tests.integration.d3_harness import (  # noqa: F401 - фикстура стенда
    call,
    chat,
    d3,
    deliveries,
    key,
    labels,
    payloads,
    quiet_around_now,
    settle,
)
from tests.integration.passive_harness import CHAT_1, NEIGHBOURS, RESIDENT, ms
from tests.integration.test_signal_inbox import decide, detail, lift

REPORT = "/report elevator Не работает лифт во втором подъезде"


def ticket_posts(h: Any) -> list[Any]:
    return [item for item in h.messaging.chat_sent if item[2].text.startswith("Заявка T-")]


async def group_report(h: Any, text: str = REPORT, *, actor: int = RESIDENT) -> None:
    await h.say(text, actor=actor, at=datetime.now(UTC))
    await settle(h)


async def ticket(h: Any) -> Ticket:
    return await h.scalar(select(Ticket).order_by(Ticket.created_at.desc()).limit(1))  # type: ignore[no-any-return]


async def command(h: Any, action: str, body: dict[str, Any] | None = None) -> Any:
    current = await ticket(h)
    response = await call(
        h,
        "POST",
        f"/api/v1/tickets/{current.id}/{action}",
        json={"expected_version": current.version, **(body or {})},
        idempotency=key(),
    )
    assert response.status_code == 200, response.text
    await settle(h)
    return response


async def press(h: Any, payload: str, *, actor: int, mid: str) -> None:
    await h.webhook(
        {
            "update_type": "message_callback",
            "timestamp": ms(datetime.now(UTC)),
            "callback": {
                "timestamp": ms(datetime.now(UTC)),
                "callback_id": f"cb-{actor}-{h.counter}",
                "payload": payload,
                "user": {"user_id": actor},
            },
            "message": {
                "recipient": {"chat_id": int(CHAT_1), "chat_type": "chat"},
                "body": {"mid": mid},
            },
        }
    )
    h.counter += 1
    await settle(h)


async def test_a_group_report_posts_one_status_message(d3) -> None:  # noqa: F811
    await chat(d3)
    await group_report(d3)
    current = await ticket(d3)
    [(chat_id, _, post)] = ticket_posts(d3)
    assert chat_id == CHAT_1
    assert post.text.splitlines()[0] == f"Заявка T-{current.number} · Проблема с лифтом"
    assert "Статус: Заявка создана и ждёт принятия в работу" in post.text
    assert "Касается жителей: 1" in post.text
    assert community_texts.CHAT_DISCLAIMER in post.text
    assert "Не работает лифт" not in post.text, "слова жителя в чат не выводятся"
    assert labels(post) == ["Меня тоже касается", "Открыть"]
    ref = payloads(post)[1]
    assert payloads(post)[0] == f"g:me:{ref}" and ref.startswith("t_")
    launch = await call(d3, "GET", f"/api/v1/notification-launch/{ref}", who="resident")
    assert launch.json()["kind"] == "ticket"
    assert launch.json()["incident_id"] == str(current.incident_id)
    assert len(await deliveries(d3, purpose="chat_ticket_status")) == 1


async def test_status_changes_edit_the_same_message(d3) -> None:  # noqa: F811
    await chat(d3)
    await group_report(d3)
    [(_, mid, _)] = ticket_posts(d3)
    await command(d3, "accept")
    assert d3.messaging.edited[-1][0] == mid
    assert "Статус: УК приняла в работу" in d3.messaging.edited[-1][1].text
    await command(d3, "start")
    assert "Статус: В работе" in d3.messaging.edited[-1][1].text
    await command(d3, "work-attempts", {"public_description": "Заменён блок управления лифтом"})
    assert "Исполнитель сообщил о выполнении, жители проверяют" in d3.messaging.edited[-1][1].text
    assert len(ticket_posts(d3)) == 1, "статус правится, а не публикуется заново"


async def test_me_too_joins_counts_and_notifies_personally(d3) -> None:  # noqa: F811
    await chat(d3)
    await group_report(d3)
    [(_, mid, post)] = ticket_posts(d3)
    neighbour = NEIGHBOURS[0]
    d3.fake.members[CHAT_1] = {str(neighbour)}
    await press(d3, payloads(post)[0], actor=neighbour, mid=mid)
    assert d3.messaging.notified[-1][1] == community_texts.ME_TOO_JOINED_NO_DIALOG
    joined = await d3.scalar(select(Report).where(Report.joined.is_(True)))
    assert joined is not None
    assert "Касается жителей: 2" in d3.messaging.edited[-1][1].text
    assert d3.messaging.edited[-1][0] == mid

    await press(d3, payloads(post)[0], actor=neighbour, mid=mid)
    assert d3.messaging.notified[-1][1] == community_texts.ME_TOO_ALREADY
    assert await d3.scalar(select(func.count()).select_from(Report)) == 2

    stranger = NEIGHBOURS[1]
    await press(d3, payloads(post)[0], actor=stranger, mid=mid)
    assert d3.messaging.notified[-1][1] == community_texts.ME_TOO_NOT_RESIDENT
    await press(d3, payloads(post)[0], actor=neighbour, mid="mid.chat-999")
    assert d3.messaging.notified[-1][1] == community_texts.ME_TOO_STALE
    assert await d3.scalar(select(func.count()).select_from(Report)) == 2

    # Присоединившийся — участник: о принятии в работу ему пишут лично.
    async with d3.container.session_factory() as session, session.begin():
        from domsignal.db.models import User

        user = await session.scalar(select(User).where(User.max_user_id == str(neighbour)))
        user.max_dialog_at = datetime.now(UTC)
    await command(d3, "accept")
    personal = [item for item in d3.messaging.sent if item[0] == str(neighbour)]
    assert personal and "Проблема принята в работу" in personal[-1][2].text


async def test_a_closed_ticket_refuses_me_too_and_drops_the_button(d3) -> None:  # noqa: F811
    await chat(d3)
    await group_report(d3)
    [(_, mid, post)] = ticket_posts(d3)
    await command(d3, "cancel", {"reason": "Дубль другой заявки"})
    assert "Статус: Отменена" in d3.messaging.edited[-1][1].text
    assert labels(d3.messaging.edited[-1][1]) == ["Открыть"]
    d3.fake.members[CHAT_1] = {str(NEIGHBOURS[0])}
    await press(d3, payloads(post)[0], actor=NEIGHBOURS[0], mid=mid)
    assert d3.messaging.notified[-1][1] == community_texts.ME_TOO_CLOSED


async def test_the_setting_off_means_no_post(d3) -> None:  # noqa: F811
    await chat(d3, post_ticket_status=False)
    await group_report(d3)
    assert not ticket_posts(d3)
    [delivery] = await deliveries(d3, purpose="chat_ticket_status")
    assert delivery.status == "skipped" and delivery.last_error_code == "CHAT_SETTING_OFF"
    assert await d3.scalar(select(func.count()).select_from(Ticket)) == 1


async def test_quiet_hours_keep_the_fact_and_acceptance_and_move_other_edits(d3) -> None:  # noqa: F811
    await chat(d3, **quiet_around_now())
    await group_report(d3)
    assert len(ticket_posts(d3)) == 1, "сам факт заявки тихие часы не задерживают"
    await command(d3, "accept")
    assert "УК приняла в работу" in d3.messaging.edited[-1][1].text
    edits = len(d3.messaging.edited)
    await command(d3, "start")
    assert len(d3.messaging.edited) == edits, "необязательная правка ждёт утра"
    [delivery] = await deliveries(d3, purpose="chat_ticket_status")
    assert delivery.desired_version > delivery.applied_version
    assert delivery.next_attempt_at is not None and delivery.next_attempt_at > datetime.now(UTC)


async def test_a_max_failure_does_not_roll_back_the_ticket(d3) -> None:  # noqa: F811
    await chat(d3)
    d3.messaging.errors = [MessagingError("MAX_SERVER_ERROR", kind="unknown")]
    await d3.say(REPORT, actor=RESIDENT, at=datetime.now(UTC))
    await d3.drain()
    for step in range(4):
        await d3.drain(now=datetime.now(UTC) + timedelta(seconds=step))
    assert await d3.scalar(select(func.count()).select_from(Ticket)) == 1
    statuses = await d3.all(
        select(NotificationDelivery.status).where(
            NotificationDelivery.purpose == "chat_ticket_status"
        )
    )
    assert statuses in (["unknown"], ["accepted"])


async def test_an_operator_ticket_from_a_signal_posts_the_status(d3) -> None:  # noqa: F811
    await chat(d3)
    signal = await lift(d3)
    view = await detail(d3, signal.id)
    created = await decide(d3, signal.id, "create-ticket", {"expected_version": view["version"]})
    assert created.status_code == 200, created.text
    await settle(d3)
    [(_, _, post)] = ticket_posts(d3)
    assert "Проблема с лифтом" in post.text and "Подъезд 2" in post.text
    assert "Касается жителей" not in post.text, "решение оператора — не житель"
