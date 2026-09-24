"""D1 §3: личный бот (B-04) — приветствие, команды и проблема в личке.

Сообщение в личке идёт тем же путём, что `/report` в группе: окно из одной
реплики, разбор (здесь — правила), общий роутер и ActionCard. Ответы — через
outbox и доставку, повтор события не даёт второго ответа. Данные синтетические.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from domsignal.db.models import (
    ExplicitIntake,
    Incident,
    NotificationDelivery,
    Report,
    ResidentMembership,
    RouteOutcome,
    Ticket,
    User,
)
from domsignal.services import bot_replies
from tests.integration.passive_harness import (
    CHAT_1,
    RESIDENT,
    build_harness,
    ms,
    passive_settings,
)
from tests.integration.test_d1_chat_membership import houses, login

GUEST = 761
ELEVATOR = "В первом подъезде не работает лифт"
LIGHTS = "На улице у остановки не горят фонари"


@pytest_asyncio.fixture
async def bot(integration_settings: Any) -> Any:
    harness, _ = await build_harness(
        passive_settings(integration_settings, build_commit="abcdef1234567890")
    )
    try:
        yield harness
    finally:
        await harness.client.aclose()
        await harness.container.aclose()


class Dialog:
    """Личка одного человека с ботом: события MAX и ответы бота."""

    def __init__(self, h: Any, max_id: int) -> None:
        self.h = h
        self.max_id = max_id
        self.count = 0

    async def start(self, payload: str | None = None) -> Any:
        body: dict[str, Any] = {
            "update_type": "bot_started",
            "timestamp": ms(datetime.now(UTC)) + self.count,
            "chat_id": 9000 + self.max_id,
            "user": {"user_id": self.max_id},
        }
        if payload:
            body["payload"] = payload
        self.count += 1
        return await self.h.webhook(body)

    async def say(self, text: str, *, mid: str | None = None) -> Any:
        self.count += 1
        return await self.h.webhook(
            {
                "update_type": "message_created",
                "timestamp": ms(datetime.now(UTC)),
                "message": {
                    "sender": {"user_id": self.max_id},
                    "recipient": {"chat_id": 9000 + self.max_id, "chat_type": "dialog"},
                    "body": {"mid": mid or f"mid.dm-{self.max_id}-{self.count}", "text": text},
                },
            }
        )

    async def press(self, payload: str) -> Any:
        self.count += 1
        return await self.h.webhook(
            {
                "update_type": "message_callback",
                "timestamp": ms(datetime.now(UTC)),
                "callback": {
                    "timestamp": ms(datetime.now(UTC)),
                    "callback_id": f"cb-{self.max_id}-{self.count}",
                    "payload": payload,
                    "user": {"user_id": self.max_id},
                },
                "message": {
                    "recipient": {"chat_id": 9000 + self.max_id, "chat_type": "dialog"},
                    "body": {"mid": f"mid.bot-{self.count}"},
                },
            }
        )

    async def settle(self) -> None:
        await self.h.drain_all()
        await self.h.deliver()

    def replies(self) -> list[Any]:
        return [message for dest, _, message in self.h.messaging.sent if dest == str(self.max_id)]

    def answers(self) -> list[Any]:
        return [message for _, message in self.h.messaging.answered]


def labels(message: Any) -> list[str]:
    return [button.text for row in message.buttons for button in row]


def payloads(message: Any) -> list[str]:
    return [button.payload for row in message.buttons for button in row]


async def open_house(h: Any, house: str = "h1", company: str = "t1") -> None:
    response = await h.client.post(
        f"/api/v1/companies/{h.ids[company]}/houses/{h.ids[house]}/open-access",
        json={"enabled": True, "confirm": True},
        headers=h.headers["admin1" if company == "t1" else "admin2"],
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------------------ приветствие


async def test_bot_started_without_a_token_greets_with_the_app_button(bot: Any) -> None:
    dialog = Dialog(bot, GUEST)
    await dialog.start()
    await dialog.settle()
    [greeting] = dialog.replies()
    assert greeting.text == bot_replies.GREETING
    assert 3 <= len(greeting.text.splitlines()) <= 4
    assert labels(greeting) == ["Открыть ДомСигнал"]  # открытых домов нет
    assert greeting.buttons[0][0].kind == "open_app"
    user = await bot.scalar(select(User).where(User.max_user_id == str(GUEST)))
    assert user.dialog_open and user.max_identity_verified_at is None


async def test_a_user_without_houses_is_offered_the_open_ones(bot: Any) -> None:
    await open_house(bot)
    dialog = Dialog(bot, GUEST)
    await dialog.start("from_somewhere")  # чужой параметр — тоже приветствие
    await dialog.settle()
    [greeting] = dialog.replies()
    assert labels(greeting) == ["Открыть ДомСигнал", "Выбрать дом"]
    assert payloads(greeting)[1] == "b:houses"

    await dialog.press("b:houses")
    await dialog.settle()
    [listing] = dialog.answers()
    assert listing.text == bot_replies.OPEN_HOUSES_LEAD
    assert payloads(listing) == [f"b:join:{bot.ids['h1']}"]
    await dialog.press(f"b:join:{bot.ids['h1']}")
    await dialog.settle()
    assert dialog.answers()[-1].text.startswith("Дом выбран: Казань, Синтетическая улица, 1")

    # Теперь сообщение о проблеме — заявка УК и карточка в личку.
    await dialog.say(ELEVATOR)
    await dialog.settle()
    assert await bot.scalar(select(func.count()).select_from(Ticket)) == 1
    card = dialog.replies()[-1]
    assert "управляющей компании" in card.text
    assert "Заявка появилась в очереди вашей управляющей компании" in card.text
    assert labels(card) == ["Открыть карточку"]


async def test_the_connection_token_flow_is_unchanged(bot: Any) -> None:
    await bot.bind()  # подключение по токену `connect_…` проходит как раньше
    assert not [
        message for message in bot.messaging.sent if message[2].text == bot_replies.GREETING
    ]


async def test_help_and_version(bot: Any) -> None:
    dialog = Dialog(bot, GUEST)
    await dialog.say("/help")
    await dialog.say("/version")
    await dialog.say("/unknown")
    await dialog.settle()
    texts = [message.text for message in dialog.replies()]
    assert texts == [bot_replies.HELP, "ДомСигнал, версия abcdef1.", bot_replies.HELP]


# ------------------------------------------------------ проблема в личке


async def test_a_resident_with_one_house_gets_a_ticket_and_the_card(bot: Any) -> None:
    dialog = Dialog(bot, RESIDENT)
    await dialog.say(f"/report {ELEVATOR}")
    await dialog.settle()
    [ticket] = await bot.all(select(Ticket))
    assert ticket.house_id == bot.ids["h1"] and ticket.source == "max_dm"
    [outcome] = await bot.all(select(RouteOutcome))
    assert (outcome.source, outcome.decision) == ("dm_report", "ticket")
    [card] = dialog.replies()
    assert "Заявка появилась в очереди" in card.text
    intake = await bot.scalar(select(ExplicitIntake))
    assert (intake.channel, intake.state, intake.result_kind) == ("dm_report", "done", "ticket")


async def test_an_external_route_gives_the_route_card(bot: Any) -> None:
    dialog = Dialog(bot, RESIDENT)
    await dialog.say(LIGHTS)
    await dialog.settle()
    assert await bot.scalar(select(func.count()).select_from(Ticket)) == 0
    [outcome] = await bot.all(select(RouteOutcome))
    assert outcome.decision == "external" and outcome.source == "dm_report"
    [card] = dialog.replies()
    assert "не к вашей УК" in card.text and labels(card) == ["Открыть карточку"]


async def test_danger_puts_the_safety_block_first(bot: Any) -> None:
    dialog = Dialog(bot, RESIDENT)
    await dialog.say("В подъезде сильно пахнет газом")
    await dialog.settle()
    card = dialog.replies()[-1]
    first = card.text.split("\n\n")[0]
    assert "112" in first or "газ" in first.lower()
    assert card.text.index(first) == 0


async def test_chatter_is_not_a_problem_and_is_not_stored(bot: Any) -> None:
    dialog = Dialog(bot, RESIDENT)
    await dialog.say("Всем доброе утро, хорошего дня")
    await dialog.settle()
    [reply] = dialog.replies()
    assert reply.text.startswith(bot_replies.NOT_A_PROBLEM)
    assert bot_replies.HELP in reply.text
    intake = await bot.scalar(select(ExplicitIntake))
    assert intake.text == "" and intake.result_kind == "not_a_problem"
    assert await bot.scalar(select(func.count()).select_from(Report)) == 0


async def test_a_short_text_gets_the_hint_without_a_record(bot: Any) -> None:
    dialog = Dialog(bot, RESIDENT)
    await dialog.say("лифт")
    await dialog.settle()
    assert dialog.replies()[0].text.startswith(bot_replies.NOT_A_PROBLEM)
    assert await bot.scalar(select(func.count()).select_from(ExplicitIntake)) == 0


async def test_the_daily_limit(bot: Any) -> None:
    bot.container.personal_bot.daily_limit = 2
    dialog = Dialog(bot, RESIDENT)
    for index in range(3):
        await dialog.say(f"{ELEVATOR}, этаж {index + 2}")
    await dialog.settle()
    assert await bot.scalar(select(func.count()).select_from(ExplicitIntake)) == 2
    assert dialog.replies()[-1].text == bot_replies.LIMIT.format(limit=2) or any(
        message.text == bot_replies.LIMIT.format(limit=2) for message in dialog.replies()
    )


async def test_a_replayed_event_gives_one_reply(bot: Any) -> None:
    dialog = Dialog(bot, RESIDENT)
    await dialog.say(LIGHTS, mid="mid.dm-replay")
    again = await dialog.say(LIGHTS, mid="mid.dm-replay")
    assert again["duplicate"] is True
    await dialog.settle()
    assert len(dialog.replies()) == 1
    assert await bot.scalar(select(func.count()).select_from(RouteOutcome)) == 1


async def test_no_houses_explains_how_to_get_one(bot: Any) -> None:
    dialog = Dialog(bot, GUEST)
    await dialog.say(ELEVATOR)
    await dialog.settle()
    [reply] = dialog.replies()
    assert reply.text == bot_replies.NO_HOUSES
    intake = await bot.scalar(select(ExplicitIntake))
    assert intake.text == "" and intake.result_kind == "ignored"


async def test_several_houses_ask_which_one(bot: Any) -> None:
    async with bot.container.session_factory() as session, session.begin():
        session.add(ResidentMembership(user_id=bot.ids["resident"], house_id=bot.ids["h2"]))
    dialog = Dialog(bot, RESIDENT)
    await dialog.say(ELEVATOR)
    await dialog.settle()
    [question] = dialog.replies()
    assert question.text == bot_replies.CHOOSE_HOUSE
    assert labels(question) == ["Казань, Синтетическая улица, 1", "Казань, Синтетическая улица, 2"]
    pick = payloads(question)[1]
    assert pick.endswith(str(bot.ids["h2"]))
    await dialog.press(pick)
    await dialog.settle()
    assert dialog.answers()[0].text.startswith("Дом: Казань, Синтетическая улица, 2")
    [ticket] = await bot.all(select(Ticket))
    assert ticket.house_id == bot.ids["h2"]
    # Повторное нажатие — тот же дом, вторая заявка не создаётся.
    await dialog.press(pick)
    await dialog.settle()
    assert await bot.scalar(select(func.count()).select_from(Ticket)) == 1


async def test_an_unanswered_house_question_forgets_the_text(bot: Any) -> None:
    async with bot.container.session_factory() as session, session.begin():
        session.add(ResidentMembership(user_id=bot.ids["resident"], house_id=bot.ids["h2"]))
    dialog = Dialog(bot, RESIDENT)
    await dialog.say(ELEVATOR)
    await dialog.settle()
    pick = payloads(dialog.replies()[0])[0]
    # Прошло 30 минут: срок ожидания в прошлом, задача истечения наступила.
    async with bot.container.session_factory() as session, session.begin():
        await session.execute(
            update(ExplicitIntake).values(hold_until=datetime.now(UTC) - timedelta(seconds=1))
        )
    await bot.drain_all(now=datetime.now(UTC) + timedelta(minutes=31))
    intake = await bot.scalar(select(ExplicitIntake))
    assert (intake.text, intake.result_kind) == ("", "expired")
    await dialog.press(pick)
    await dialog.settle()
    assert dialog.answers()[-1].text == bot_replies.EXPIRED
    assert await bot.scalar(select(func.count()).select_from(Ticket)) == 0


async def test_a_duplicate_asks_same_or_other(bot: Any) -> None:
    first = Dialog(bot, RESIDENT)
    await first.say(ELEVATOR)
    await first.settle()
    [incident] = await bot.all(select(Incident))

    await first.say("Лифт в первом подъезде опять стоит")
    await first.settle()
    question = first.replies()[-1]
    assert question.text.startswith("Похоже, об этом уже сообщали")
    assert labels(question) == ["Это та же проблема", "Другое"]
    await first.press(payloads(question)[0])
    await first.settle()
    assert first.answers()[-1].text.startswith("Готово: вы присоединились")
    assert await bot.scalar(select(func.count()).select_from(Incident)) == 1
    reports = await bot.all(select(Report).where(Report.incident_id == incident.id))
    assert len(reports) == 2
    joined = await bot.scalar(select(ExplicitIntake).where(ExplicitIntake.result_kind == "joined"))
    assert joined.text == ""

    await first.say("Лифт в первом подъезде снова не работает")
    await first.settle()
    await first.press(payloads(first.replies()[-1])[1])  # «Другое»
    await first.settle()
    assert first.answers()[-1].text == bot_replies.OTHER_CHOSEN
    assert await bot.scalar(select(func.count()).select_from(Incident)) == 2


async def test_logs_carry_neither_text_nor_max_ids(
    bot: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="domsignal")
    dialog = Dialog(bot, RESIDENT)
    await dialog.say(ELEVATOR)
    await dialog.say("Всем доброе утро, хорошего дня")
    await dialog.settle()
    for record in caplog.records:
        if not record.name.startswith("domsignal.services"):
            continue
        rendered = (
            record.getMessage() + " " + " ".join(str(value) for value in record.__dict__.values())
        )
        assert "лифт" not in rendered.lower() and "доброе утро" not in rendered.lower()
        assert str(RESIDENT) not in rendered


# ------------------------------------------------------------ группа


async def test_a_group_report_without_a_dialog_is_answered_in_the_group_once(bot: Any) -> None:
    await bot.bind()
    bot.fake.members[CHAT_1] = {"771"}
    await bot.say(f"/report {LIGHTS}", actor=771)
    await bot.say(f"/report {ELEVATOR}", actor=771)
    await bot.drain_all()
    await bot.deliver()
    acks = [
        item for item in bot.messaging.chat_sent if item[2].text.startswith(bot_replies.GROUP_ACK)
    ]
    assert len(acks) == 1  # не чаще раза в 10 минут на автора
    assert "https://max.ru/synthetic_bot" in acks[0][2].text
    # Житель — участник чата: сообщения приняты, заявка и внешний маршрут есть.
    outcomes = await bot.all(select(RouteOutcome.decision).order_by(RouteOutcome.created_at))
    assert sorted(outcomes) == ["external", "ticket"]
    # Личная карточка не ушла: бот не пишет первым.
    skipped = await bot.all(
        select(NotificationDelivery).where(
            NotificationDelivery.purpose == "route_action_card",
            NotificationDelivery.last_error_code == "NO_MAX_IDENTITY",
        )
    )
    assert len(skipped) == 1
    assert not [dest for dest, _, _ in bot.messaging.sent if dest == "771"]

    # Житель открыл диалог: последняя недоставленная карточка досылается.
    dialog = Dialog(bot, 771)
    await dialog.start()
    await dialog.settle()
    texts = [message.text for message in dialog.replies()]
    assert texts[0] == bot_replies.GREETING
    assert any("не к вашей УК" in text for text in texts[1:])


async def test_a_group_report_from_a_non_member_is_not_accepted(bot: Any) -> None:
    await bot.bind()
    await bot.say(f"/report {ELEVATOR}", actor=772)  # MAX: не участник чата
    await bot.drain_all()
    assert await bot.scalar(select(func.count()).select_from(Report)) == 0
    intake = await bot.scalar(select(ExplicitIntake))
    assert intake.result_kind == "ignored"


async def test_the_reading_notice_carries_the_app_button_and_can_be_resent(bot: Any) -> None:
    binding = await bot.bind()
    await bot.deliver()
    [notice] = bot.notices()
    [[button]] = notice[2].buttons
    assert (button.kind, button.text) == ("open_app", "Открыть ДомСигнал")
    assert button.payload.startswith("c_")
    again = await bot.client.post(
        f"/api/v1/chat-bindings/{binding}/notice", headers=bot.headers["admin1"]
    )
    assert again.status_code == 200 and again.json()["queued"] is True
    twice = await bot.client.post(
        f"/api/v1/chat-bindings/{binding}/notice", headers=bot.headers["admin1"]
    )
    assert twice.json()["queued"] is False  # не чаще раза в 10 минут
    foreign = await bot.client.post(
        f"/api/v1/chat-bindings/{binding}/notice", headers=bot.headers["admin2"]
    )
    assert foreign.status_code == 404
    await bot.deliver()
    assert len(bot.notices()) == 2
    buttons = [item[2].buttons[0][0].payload for item in bot.notices()]
    assert buttons[0] != buttons[1]


async def test_mini_app_launch_from_the_chat_button_checks_that_chat(bot: Any) -> None:
    await bot.bind()
    await bot.deliver()
    ref = bot.notices()[0][2].buttons[0][0].payload
    bot.container.resident_access.check_all_max_chats = 0
    bot.fake.members[CHAT_1] = {"781"}
    headers = await login(bot, 781)
    assert await houses(bot, headers) == []  # без подсказки чат не угадывается
    user = await bot.scalar(select(User).where(User.max_user_id == "781"))
    await bot.container.resident_access.refresh(user.id, launch_ref=ref)
    assert await houses(bot, headers) == [str(bot.ids["h1"])]
    assert isinstance(user.id, UUID)


async def test_bot_stopped_closes_the_dialog(bot: Any) -> None:
    dialog = Dialog(bot, GUEST)
    await dialog.start()
    await bot.webhook(
        {
            "update_type": "bot_stopped",
            "timestamp": ms(datetime.now(UTC) + timedelta(seconds=1)),
            "chat_id": 9000 + GUEST,
            "user": {"user_id": GUEST},
        }
    )
    user = await bot.scalar(select(User).where(User.max_user_id == str(GUEST)))
    assert not user.dialog_open
    async with bot.container.session_factory() as session, session.begin():
        await session.execute(update(User).where(User.id == user.id).values(group_ack_at=None))


async def test_the_bot_never_answers_its_own_dialog_messages(bot: Any) -> None:
    await bot.webhook(
        {
            "update_type": "message_created",
            "timestamp": ms(datetime.now(UTC)),
            "message": {
                "sender": {"user_id": 999, "is_bot": True},
                "recipient": {"chat_id": 9000 + GUEST, "chat_type": "dialog"},
                "body": {"mid": "mid.bot-own-1", "text": bot_replies.HELP},
            },
        }
    )
    await bot.drain_all()
    await bot.deliver()
    assert bot.messaging.sent == []
    assert await bot.scalar(select(User).where(User.max_user_id == "999")) is None
