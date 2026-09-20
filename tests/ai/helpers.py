"""Общие помощники тестов AI-ядра: окна, реплики и ответы модели."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from domsignal.ai import WindowInput, WindowLine
from domsignal.ai.contracts import Channel, OpenItem

BASE_TIME = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


def line(
    index: int,
    text: str,
    *,
    author: str = "resident-1",
    seconds: int = 0,
    reply_to: str | None = None,
    is_context: bool = False,
) -> WindowLine:
    return WindowLine(
        line_id=f"line-{index}",
        author_ref=author,
        text=text,
        sent_at=BASE_TIME + timedelta(seconds=seconds),
        reply_to=reply_to,
        is_context=is_context,
    )


def window(
    *texts: str,
    channel: Channel = "group_passive",
    open_items: tuple[OpenItem, ...] = (),
) -> WindowInput:
    lines = tuple(
        line(index, text, author=f"resident-{index}", seconds=index * 30)
        for index, text in enumerate(texts, start=1)
    )
    return WindowInput(channel=channel, lines=lines, open_items=open_items)


def single(text: str, channel: Channel = "group_report") -> WindowInput:
    return WindowInput(channel=channel, lines=(line(1, text),))


def facets(
    current: str = "unclear",
    local: str = "unclear",
    observed: str = "unclear",
    quote: str | None = None,
    msg: str | None = None,
) -> dict[str, Any]:
    def facet(value: str) -> dict[str, Any]:
        return {"v": value, "quote": quote, "msg": msg}

    return {"current": facet(current), "local": facet(local), "observed": facet(observed)}


def model_signal(
    ref: str = "new:1",
    subtype: str = "elevator.stopped",
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ref": ref,
        "subtype": subtype,
        "object": "лифт",
        "location_scope": {"value": "unknown", "quote": None, "msg": None},
        "facets": facets(),
    }
    payload.update(overrides)
    return payload


def model_response(
    signals: list[dict[str, Any]],
    roles: dict[str, str] | None = None,
    refs: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    roles = roles or {}
    refs = refs or {}
    messages = [
        {"id": msg, "role": role, "signals": refs.get(msg, [])} for msg, role in roles.items()
    ]
    return {"messages": messages, "signals": signals}
