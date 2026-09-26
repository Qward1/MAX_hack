"""D5 §7: проверка доставки от имени бота — транспорт и отрисовка продукта."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, update

from domsignal.db.models import InboxReceipt, User
from domsignal.services.community_texts import VOTE_LABEL
from domsignal.tools import transport_check
from tests.integration.d3_harness import chat, d3

pytestmark = pytest.mark.integration

__all__ = ["d3"]


def labels(message: Any) -> list[str]:
    return [button.text for row in message.buttons for button in row]


async def test_posts_edits_dms_skip_the_unsubscribed_and_clean_up(
    d3: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = await chat(d3)
    async with d3.container.session_factory() as session, session.begin():
        await session.execute(
            update(User)
            .where(User.id.in_([d3.ids["admin1"], d3.ids["resident"]]))
            .values(max_dialog_at=datetime.now(UTC))
        )
    monkeypatch.setattr(transport_check, "dm_allowed", lambda now: True)
    args = argparse.Namespace(
        binding=binding,
        dm_user=[d3.ids["admin1"], d3.ids["resident"]],
        unsubscribed_user=d3.ids["resident"],
        operator="dev-agent (тест)",
        reason="проверка инструмента",
    )
    assert await transport_check.check(d3.container, args) == 0

    posts = d3.messaging.chat_sent
    assert len(posts) == 2
    assert posts[0][2].text.startswith("Объявление\nСлужебная проверка доставки")
    assert labels(posts[1][2]) == [VOTE_LABEL]
    edits = [message for _, message in d3.messaging.edited]
    assert any("Изменено" in message.text for message in edits), "правка того же объявления"
    assert any("Опрос закрыт" in message.text for message in edits), "итоги опроса правкой"
    dms = [item for item in d3.messaging.sent]
    assert [item[0] for item in dms] == ["701"], "отписавшийся житель пропущен"
    # Уборка: двойник не удаляет — посты правятся в служебную строку.
    assert sum(transport_check.CLEANED == m.text for m in edits) == 3

    async with d3.container.session_factory() as session:
        resident = await session.get(User, d3.ids["resident"])
        receipt = await session.scalar(
            select(InboxReceipt).where(InboxReceipt.event_type == "operator.transport_check")
        )
    assert resident is not None and resident.broadcast_opt_out_at is None, "прежнее состояние"
    assert receipt is not None
    kinds = [row["kind"] for row in receipt.payload["results"]]
    assert kinds == ["announcement", "poll", "dm", "dm"]
    assert {row.get("skipped") for row in receipt.payload["results"]} >= {"UNSUBSCRIBED"}
    assert "text" not in str(receipt.payload), "в квитанции нет текстов"


async def test_an_inactive_binding_is_refused(d3: Any) -> None:  # noqa: F811
    from uuid import uuid4

    args = argparse.Namespace(
        binding=uuid4(), dm_user=[], unsubscribed_user=None, operator="x", reason="y"
    )
    assert await transport_check.check(d3.container, args) == 2
    assert not d3.messaging.chat_sent
