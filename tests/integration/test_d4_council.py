"""D4: совет дома и «Предложить вопрос» — PostgreSQL и HTTP для жителя."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from domsignal.contracts.community import CouncilMemberChange, CouncilMemberRevoke
from domsignal.db.models import Broadcast, BroadcastHouse, HouseProposal, InboxReceipt
from domsignal.services.errors import AccessDenied, FieldValidationError, ResourceNotFound
from tests.integration.explicit_harness import ex  # noqa: F401

REASON = "решение собрания жителей"


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"key-{uuid4().hex}"}


async def call(harness: Any, method: str, path: str, who: str, body: Any = None) -> Any:
    headers = {**harness.headers[who], **(key() if method == "POST" else {})}
    return await harness.client.request(method, path, json=body, headers=headers)


async def grant(harness: Any, who: str) -> None:
    async with harness.container.session_factory() as session, session.begin():
        await harness.container.council.grant(
            session,
            actor_id=harness.ids["admin"],
            company_id=harness.ids["tenant"],
            house_id=harness.ids["h1"],
            payload=CouncilMemberChange(user_id=harness.ids[who], reason=REASON),
        )


def poll_body(**extra: Any) -> dict[str, Any]:
    return {
        "poll": {
            "question": "Ставим шлагбаум во дворе?",
            "options": ["За", "Против"],
            "multiple": False,
            "closes_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
        "service_only": True,
        **extra,
    }


@pytest.mark.integration
async def test_the_uk_admin_marks_and_revokes_a_resident_with_audit(ex) -> None:  # noqa: F811
    council = ex.container.council
    await grant(ex, "resident")
    await grant(ex, "resident")  # повтор — одна запись
    async with ex.container.session_factory() as session:
        view = await council.admin_view(
            session, actor_id=ex.ids["admin"], company_id=ex.ids["tenant"], house_id=ex.ids["h1"]
        )
    assert view.can_manage and [m.user_id for m in view.members] == [ex.ids["resident"]]
    assert {r.user_id: r.is_member for r in view.residents}[ex.ids["resident"]] is True
    # Не житель дома в совет не попадает.
    with pytest.raises(FieldValidationError, match="только жителя этого дома"):
        await grant(ex, "outsider")
    # Житель, не сотрудник УК, совет не отмечает (маскированный 404).
    with pytest.raises((AccessDenied, ResourceNotFound)):
        async with ex.container.session_factory() as session, session.begin():
            await council.grant(
                session,
                actor_id=ex.ids["resident"],
                company_id=ex.ids["tenant"],
                house_id=ex.ids["h1"],
                payload=CouncilMemberChange(user_id=ex.ids["neighbour"], reason=REASON),
            )
    async with ex.container.session_factory() as session, session.begin():
        view = await council.revoke(
            session,
            actor_id=ex.ids["admin"],
            company_id=ex.ids["tenant"],
            house_id=ex.ids["h1"],
            user_id=ex.ids["resident"],
            payload=CouncilMemberRevoke(reason="переизбрание"),
        )
    assert view.members == []
    events = [
        row.event_type
        for row in await ex.all(
            select(InboxReceipt).where(InboxReceipt.event_type.like("administration.council.%"))
        )
    ]
    assert sorted(events) == [
        "administration.council.member_granted",
        "administration.council.member_revoked",
    ]


@pytest.mark.integration
async def test_proposals_are_limited_and_visible_to_the_author_and_the_council(ex) -> None:  # noqa: F811
    path = f"/api/v1/houses/{ex.ids['h1']}/proposals"
    for number in range(3):
        created = await call(ex, "POST", path, "neighbour", {"text": f"Тема номер {number}"})
        assert created.status_code == 201, created.text
        assert created.json()["status"] == "new" and created.json()["mine"] is True
    refused = await call(ex, "POST", path, "neighbour", {"text": "Четвёртая тема"})
    assert refused.status_code == 422
    assert "не больше 3" in refused.json()["field_errors"][0]["message"]
    mine = (await call(ex, "GET", f"/api/v1/houses/{ex.ids['h1']}/council", "resident")).json()
    assert mine["is_member"] is False and mine["proposals"] == []  # чужие не видны
    await grant(ex, "resident")
    council = (await call(ex, "GET", f"/api/v1/houses/{ex.ids['h1']}/council", "resident")).json()
    assert council["is_member"] is True and len(council["proposals"]) == 3
    # Посторонний не видит совет чужого дома.
    foreign = await call(ex, "GET", f"/api/v1/houses/{ex.ids['h1']}/council", "outsider")
    assert foreign.status_code in {403, 404}


@pytest.mark.integration
async def test_the_council_publishes_through_the_d3_mechanism(ex) -> None:  # noqa: F811
    await ex.bind()
    base = f"/api/v1/houses/{ex.ids['h1']}/council"
    body = {
        "title": "Субботник в субботу",
        "body": "Собираемся в 10:00 у подъезда",
        "service_only": True,
    }
    denied = await call(ex, "POST", f"{base}/announcements", "neighbour", body)
    assert denied.status_code in {403, 404}
    await grant(ex, "resident")
    published = await call(ex, "POST", f"{base}/announcements", "resident", body)
    assert published.status_code == 201, published.text
    assert published.json()["status"] == "scheduled"
    broadcast = await ex.scalar(select(Broadcast).where(Broadcast.origin == "council"))
    assert broadcast.tenant_id == ex.ids["tenant"] and broadcast.channels == ["chat", "feed"]
    await ex.drain_all()
    assert await ex.scalar(
        select(BroadcastHouse).where(BroadcastHouse.broadcast_id == broadcast.id)
    )
    feed = (
        await call(ex, "GET", f"/api/v1/houses/{ex.ids['h1']}/announcements", "neighbour")
    ).json()
    item = next(i for i in feed["items"] if i["title"] == "Субботник в субботу")
    assert item["sender"] == "Сообщение от совета дома"
    posted = [message.text for _, _, message in ex.messaging.chat_sent]
    assert any("Сообщение от совета дома" in text for text in posted)


@pytest.mark.integration
async def test_a_proposal_becomes_a_council_poll_or_a_uk_draft(ex) -> None:  # noqa: F811
    await ex.bind()
    proposals = f"/api/v1/houses/{ex.ids['h1']}/proposals"
    first = (await call(ex, "POST", proposals, "neighbour", {"text": "Шлагбаум во дворе"})).json()
    second = (await call(ex, "POST", proposals, "neighbour", {"text": "Покраска подъезда"})).json()
    await grant(ex, "resident")
    poll = await call(
        ex,
        "POST",
        f"/api/v1/houses/{ex.ids['h1']}/council/polls",
        "resident",
        poll_body(proposal_id=first["id"]),
    )
    assert poll.status_code == 201, poll.text
    assert poll.json()["poll_id"]
    view = (await call(ex, "GET", f"/api/v1/houses/{ex.ids['h1']}/council", "neighbour")).json()
    converted = next(p for p in view["proposals"] if p["id"] == first["id"])
    assert converted["status"] == "converted" and converted["poll_id"] == poll.json()["poll_id"]
    # УК: одним действием — черновик опроса в кабинете, отправка обычным подтверждением.
    async with ex.container.session_factory() as session, session.begin():
        draft = await ex.container.council.proposal_to_poll(
            session,
            actor_id=ex.ids["admin"],
            company_id=ex.ids["tenant"],
            proposal_id=second["id"],
            idempotency_key=f"key-{uuid4().hex}",
        )
    assert draft.origin == "company" and draft.status == "draft" and draft.poll is not None
    stored = await ex.scalar(select(HouseProposal).where(HouseProposal.id == second["id"]))
    assert stored.status == "converted" and stored.broadcast_id == draft.id


@pytest.mark.integration
async def test_a_revoked_member_cannot_publish_and_a_queued_post_is_cancelled(ex) -> None:  # noqa: F811
    await ex.bind()
    await grant(ex, "resident")
    base = f"/api/v1/houses/{ex.ids['h1']}/council"
    body = {"title": "Отключение воды", "body": "Во вторник с 10 до 12", "service_only": True}
    assert (await call(ex, "POST", f"{base}/announcements", "resident", body)).status_code == 201
    # Отметку сняли до отправки: полномочия перепроверяются, пост не уходит.
    async with ex.container.session_factory() as session, session.begin():
        await ex.container.council.revoke(
            session,
            actor_id=ex.ids["admin"],
            company_id=ex.ids["tenant"],
            house_id=ex.ids["h1"],
            user_id=ex.ids["resident"],
            payload=CouncilMemberRevoke(reason="переизбрание"),
        )
    await ex.drain_all()
    broadcast = await ex.scalar(select(Broadcast).where(Broadcast.origin == "council"))
    assert broadcast.status == "cancelled"
    again = await call(ex, "POST", f"{base}/announcements", "resident", body)
    assert again.status_code in {403, 404}
