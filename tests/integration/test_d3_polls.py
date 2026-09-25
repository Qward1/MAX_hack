"""D3 §4: опросы — голос жителя, итоги числами, правка того же поста.

Итоги в чате правятся не чаще раза в 5 минут и сразу при закрытии. Голосует
житель домов аудитории, один голос на человека, до закрытия его можно
изменить. Данные синтетические.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from domsignal.db.models import Job, NotificationDelivery, Poll
from domsignal.services import community_texts
from domsignal.services.broadcasts import POLL_CLOSE_JOB
from tests.integration.d3_harness import (  # noqa: F401 - фикстура стенда
    call,
    chat,
    d3,
    deliveries,
    labels,
    payloads,
    poll_body,
    send_now,
    settle,
)


def poll_posts(h: Any) -> list[Any]:
    return [item for item in h.messaging.chat_sent if item[2].text.startswith("Опрос")]


async def vote(h: Any, poll_id: str, options: list[str], *, who: str = "resident") -> Any:
    return await call(
        h, "POST", f"/api/v1/polls/{poll_id}/vote", who=who, json={"option_ids": options}
    )


async def test_a_poll_goes_to_the_chat_with_a_vote_button_and_a_disclaimer(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, poll_body())
    assert sent["poll"]["voters"] == 0 and len(sent["poll"]["options"]) == 2
    [(_, _, post)] = poll_posts(d3)
    assert "Какой цвет стен выбрать?" in post.text
    assert "1. Бежевый — 0 (0%)" in post.text and "Проголосовали: 0" in post.text
    assert community_texts.POLL_DISCLAIMER in post.text
    assert labels(post) == ["Голосовать"] and payloads(post)[0].startswith("p_")

    launch = await call(
        d3, "GET", f"/api/v1/notification-launch/{payloads(post)[0]}", who="resident"
    )
    assert launch.json()["kind"] == "poll"
    assert launch.json()["poll_id"] == sent["poll"]["poll_id"]

    view = await call(d3, "GET", f"/api/v1/polls/{sent['poll']['poll_id']}", who="resident")
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["can_vote"] is True and body["disclaimer"] == community_texts.POLL_DISCLAIMER
    assert body["sender"] == "Сообщение от УК «УК Первая (тест)»"


async def test_one_vote_per_person_can_change_until_closed(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, poll_body())
    poll_id = sent["poll"]["poll_id"]
    first, second = (item["id"] for item in sent["poll"]["options"])
    voted = await vote(d3, poll_id, [first])
    assert voted.status_code == 200, voted.text
    assert voted.json()["voters"] == 1 and voted.json()["my_choice"] == [first]
    assert voted.json()["options"][0]["votes"] == 1 and voted.json()["options"][0]["share"] == 1
    again = await vote(d3, poll_id, [first])
    assert again.json()["voters"] == 1
    changed = await vote(d3, poll_id, [second])
    assert changed.json()["voters"] == 1
    assert [item["votes"] for item in changed.json()["options"]] == [0, 1]
    two = await vote(d3, poll_id, [first, second])
    assert two.status_code == 422, "один вариант в опросе без множественного выбора"
    unknown = await vote(d3, poll_id, [str(sent["id"])])
    assert unknown.status_code == 422
    staff = await vote(d3, poll_id, [first], who="admin1")
    assert staff.status_code == 403, "сотрудник видит итоги, но не голосует"
    stranger = await call(d3, "GET", f"/api/v1/polls/{poll_id}", who="admin2")
    assert stranger.status_code == 404
    serialized = changed.text
    assert "resident" not in serialized and str(d3.ids["resident"]) not in serialized


async def test_results_edit_the_same_post_at_most_every_five_minutes(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, poll_body())
    [(_, mid, _)] = poll_posts(d3)
    first = sent["poll"]["options"][0]["id"]
    now = datetime.now(UTC)
    await vote(d3, sent["poll"]["poll_id"], [first])
    [delivery] = await deliveries(d3, purpose="broadcast_chat")
    assert delivery.desired_version > delivery.applied_version
    assert delivery.next_attempt_at is not None
    assert delivery.next_attempt_at >= now + timedelta(minutes=4, seconds=50)
    await settle(d3)
    assert not d3.messaging.edited, "итоги не правятся чаще раза в 5 минут"
    await settle(d3, at=delivery.next_attempt_at + timedelta(seconds=1))
    [(edited_mid, message)] = d3.messaging.edited
    assert edited_mid == mid and "1. Бежевый — 1 (100%)" in message.text
    assert len(poll_posts(d3)) == 1, "итоги — правка, а не новый пост"


async def test_closing_edits_immediately_and_refuses_new_votes(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, poll_body())
    first = sent["poll"]["options"][0]["id"]
    await vote(d3, sent["poll"]["poll_id"], [first])
    closed = await call(
        d3,
        "POST",
        f"/api/v1/broadcasts/{sent['id']}/close-poll",
        json={"expected_version": sent["version"]},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["poll"]["closed"] is True
    await settle(d3)
    message = d3.messaging.edited[-1][1]
    assert "Опрос закрыт" in message.text and labels(message) == ["Открыть ДомСигнал"]
    refused = await vote(d3, sent["poll"]["poll_id"], [first])
    assert refused.status_code == 409 and refused.json()["code"] == "poll_closed"


async def test_the_poll_closes_itself_on_time(d3) -> None:  # noqa: F811
    await chat(d3)
    closes = datetime.now(UTC) + timedelta(minutes=15)
    body = poll_body()
    body["poll"]["closes_at"] = closes.isoformat()
    sent = await send_now(d3, body)
    jobs = await d3.jobs(POLL_CLOSE_JOB)
    assert len(jobs) == 1 and jobs[0].next_attempt_at >= closes - timedelta(seconds=2)
    # Срок наступил: опрос и его задача сдвигаются в прошлое вместо ожидания.
    async with d3.container.session_factory() as session, session.begin():
        await session.execute(
            update(Poll)
            .where(Poll.id == sent["poll"]["poll_id"])
            .values(closes_at=datetime.now(UTC) - timedelta(seconds=5))
        )
        await session.execute(
            update(Job).where(Job.id == jobs[0].id).values(next_attempt_at=datetime.now(UTC))
        )
    await settle(d3)
    poll = await d3.scalar(select(Poll).where(Poll.id == sent["poll"]["poll_id"]))
    assert poll.closed_at is not None
    assert "Опрос закрыт" in d3.messaging.edited[-1][1].text


async def test_a_poll_needs_ten_minutes_and_two_options(d3) -> None:  # noqa: F811
    await chat(d3)
    body = poll_body()
    body["poll"]["closes_at"] = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    short = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        json=body,
        idempotency="d3-short-poll",
    )
    assert short.status_code == 422
    body = poll_body()
    body["poll"]["options"] = ["Один"]
    single = await call(
        d3,
        "POST",
        f"/api/v1/companies/{d3.ids['t1']}/broadcasts",
        json=body,
        idempotency="d3-single-poll",
    )
    assert single.status_code == 422


async def test_polls_are_in_the_feed_and_in_the_cabinet_results(d3) -> None:  # noqa: F811
    await chat(d3)
    sent = await send_now(d3, poll_body(channels=["chat"]))
    await vote(d3, sent["poll"]["poll_id"], [sent["poll"]["options"][1]["id"]])
    feed = await call(d3, "GET", f"/api/v1/houses/{d3.ids['h1']}/announcements", who="resident")
    [item] = feed.json()["items"]
    assert item["kind"] == "poll" and item["poll"]["voted"] is True and item["poll"]["voters"] == 1
    cabinet = await call(d3, "GET", f"/api/v1/broadcasts/{sent['id']}")
    assert [option["votes"] for option in cabinet.json()["poll"]["options"]] == [0, 1]
    assert (
        await d3.scalar(
            select(NotificationDelivery.status).where(
                NotificationDelivery.purpose == "broadcast_chat"
            )
        )
        == "accepted"
    )
