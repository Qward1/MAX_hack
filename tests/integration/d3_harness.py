"""Стенд D3 поверх стенда пассивного чтения: две УК, два дома, чат дома h1.

Тихие часы чатов и личных рассылок в стенде выключены, чтобы проверки не
зависели от времени суток; проверки тихих часов задают окно вокруг «сейчас».
Данные синтетические.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from sqlalchemy import select

from domsignal.core.quiet_hours import MSK
from domsignal.db.models import NotificationDelivery, User
from tests.integration.passive_harness import build_harness, passive_settings

NO_QUIET = {"quiet_start": "00:00", "quiet_end": "00:00"}
ALL_ON = {
    "post_ticket_status": True,
    "post_company_messages": True,
    "post_polls": True,
    "post_platform_messages": False,
}


@pytest_asyncio.fixture
async def d3(integration_settings: Any) -> Any:
    harness, _ = await build_harness(
        passive_settings(integration_settings, broadcast_dm_quiet_hours="")
    )
    try:
        yield harness
    finally:
        await harness.client.aclose()
        await harness.container.aclose()


def key() -> str:
    return f"d3-{uuid4().hex}"


async def call(
    h: Any,
    method: str,
    path: str,
    *,
    who: str = "admin1",
    json: dict[str, Any] | None = None,
    idempotency: str | None = None,
    params: Any = None,
) -> Any:
    headers = dict(h.headers[who])
    if idempotency is not None:
        headers["Idempotency-Key"] = idempotency
    return await h.client.request(method, path, json=json, headers=headers, params=params)


async def chat(h: Any, *, enable_reading: bool = True, **settings: Any) -> UUID:
    """Подключённый чат дома h1 без тихих часов (или с заданными настройками)."""
    binding = await h.bind(enable=enable_reading)
    await set_chat(h, binding, **{**ALL_ON, **NO_QUIET, **settings})
    h.messaging.chat_sent.clear()
    return binding


async def set_chat(h: Any, binding: UUID, *, who: str = "admin1", **settings: Any) -> Any:
    response = await call(
        h, "POST", f"/api/v1/chat-bindings/{binding}/settings", who=who, json=settings
    )
    return response


def quiet_around_now(minutes_before: int = 60, minutes_after: int = 60) -> dict[str, str]:
    now = datetime.now(UTC).astimezone(MSK)
    start = now - timedelta(minutes=minutes_before)
    end = now + timedelta(minutes=minutes_after)
    return {"quiet_start": start.strftime("%H:%M"), "quiet_end": end.strftime("%H:%M")}


def announcement(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "announcement",
        "topic": "works",
        "title": "Промывка системы отопления",
        "body": "28 сентября с 10:00 до 14:00 во втором подъезде возможен шум.",
        "channels": ["chat", "dm", "feed"],
        "audience": {"mode": "all"},
    }
    body.update(changes)
    return body


def poll_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "poll",
        "title": "Покраска подъезда",
        "body": "",
        "channels": ["chat", "feed"],
        "audience": {"mode": "all"},
        "poll": {
            "question": "Какой цвет стен выбрать?",
            "options": ["Бежевый", "Светло-серый"],
            "multiple": False,
            "closes_at": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
        },
    }
    body.update(changes)
    return body


async def create(
    h: Any, body: dict[str, Any], *, who: str = "admin1", company: str = "t1"
) -> dict[str, Any]:
    response = await call(
        h,
        "POST",
        f"/api/v1/companies/{h.ids[company]}/broadcasts",
        who=who,
        json=body,
        idempotency=key(),
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def confirm(
    h: Any, broadcast: dict[str, Any], *, who: str = "admin1", send_at: datetime | None = None
) -> Any:
    return await call(
        h,
        "POST",
        f"/api/v1/broadcasts/{broadcast['id']}/confirm",
        who=who,
        json={
            "expected_version": broadcast["version"],
            "service_only": True,
            **({"send_at": send_at.isoformat()} if send_at else {}),
        },
    )


async def detail(h: Any, broadcast_id: Any, *, who: str = "admin1") -> dict[str, Any]:
    response = await call(h, "GET", f"/api/v1/broadcasts/{broadcast_id}", who=who)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def send_now(h: Any, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Черновик → подтверждение → отправка → доставка."""
    draft = await create(h, body, **kwargs)
    confirmed = await confirm(h, draft)
    assert confirmed.status_code == 200, confirmed.text
    await settle(h)
    return await detail(h, draft["id"])


async def settle(h: Any, *, at: datetime | None = None) -> None:
    await h.drain(now=at)
    for step in range(6):
        await h.drain(now=(at or datetime.now(UTC)) + timedelta(seconds=step))


async def deliveries(h: Any, **where: Any) -> list[NotificationDelivery]:
    statement = select(NotificationDelivery).order_by(NotificationDelivery.created_at)
    for field, value in where.items():
        statement = statement.where(getattr(NotificationDelivery, field) == value)
    return await h.all(statement)


def stats(view: dict[str, Any], channel: str) -> dict[str, Any]:
    return next(item for item in view["stats"] if item["channel"] == channel)


def labels(message: Any) -> list[str]:
    return [button.text for row in message.buttons for button in row]


def payloads(message: Any) -> list[str]:
    return [button.payload for row in message.buttons for button in row]


async def user_by_max(h: Any, max_id: int) -> User:
    return await h.scalar(select(User).where(User.max_user_id == str(max_id)))  # type: ignore[no-any-return]
