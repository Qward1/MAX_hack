"""Живой D2: код подключения чата, набранный командой `/start connect_…` в личке.

Кабинет УК предлагает отправить боту команду; раньше бот принимал код только из
ссылки запуска (`bot_started`), а набранная команда давала приветствие, и
запрос оставался «Создано». Теперь оба пути одинаково закрепляют запрос за
администратором чата, бот отвечает, что делать дальше, а токен нигде не
сохраняется. Данные синтетические.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, select

from domsignal.db.models import ConnectionRequest, ExplicitIntake, InboxReceipt, OutboxMessage
from domsignal.services import bot_replies
from tests.integration.test_d1_personal_bot import GUEST, Dialog, bot  # noqa: F401 - фикстура


async def initiate(h: Any, house: str = "h1", admin: str = "admin1") -> str:
    """Новый запрос подключения дома; код показывается только при создании."""
    response = await h.client.post(
        f"/api/v1/houses/{h.ids[house]}/chat-connections",
        json={"scope_type": "house"},
        headers=h.headers[admin],
    )
    assert response.status_code == 201, response.text
    return str(response.json()["correlation_token"])


async def test_typed_start_command_claims_the_request_and_explains_next_step(
    bot: Any,  # noqa: F811
) -> None:
    token = await initiate(bot)
    dialog = Dialog(bot, GUEST)
    await dialog.say(f"/start {token}")
    await dialog.settle()
    [reply] = dialog.replies()
    assert reply.text == bot_replies.CONNECT_CLAIMED
    request = await bot.scalar(select(ConnectionRequest))
    assert (request.status, request.connector_max_user_id) == ("connector_claimed", str(GUEST))
    # Команда не стала сообщением о проблеме, токен не сохранён.
    assert await bot.scalar(select(func.count()).select_from(ExplicitIntake)) == 0
    async with bot.container.session_factory() as db:
        stored = json.dumps(
            [
                *(await db.scalars(select(InboxReceipt.payload))).all(),
                *(await db.scalars(select(OutboxMessage.payload))).all(),
            ],
            ensure_ascii=False,
        )
    assert token not in stored


async def test_second_code_while_connecting_and_broken_code_get_clear_answers(
    bot: Any,  # noqa: F811
) -> None:
    # Один администратор чата — два дома разных УК.
    first, second = await initiate(bot), await initiate(bot, "h2", "admin2")
    dialog = Dialog(bot, GUEST)
    await dialog.start(first)  # ссылка запуска бота — тот же путь
    await dialog.say(f"/start {second}")
    await dialog.say(f"/start {first[:20]}")  # скопирован не целиком
    await dialog.settle()
    assert [m.text for m in dialog.replies()] == [
        bot_replies.CONNECT_CLAIMED,
        bot_replies.CONNECT_BUSY,
        bot_replies.CONNECT_INVALID,
    ]
    async with bot.container.session_factory() as db:
        statuses = sorted((await db.scalars(select(ConnectionRequest.status))).all())
    assert statuses == ["connector_claimed", "created"]
