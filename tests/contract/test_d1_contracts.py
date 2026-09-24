"""D1: точечная проверка участника MAX, новые события и шаблоны личного бота.

Ответы MAX — документированная форма поверх MockTransport, не живой HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from domsignal.ai import WindowAnalyzer, WindowInput, WindowLine, decide_explicit_report
from domsignal.bot.chat_provider import HttpMaxChatProvider, MaxProviderError
from domsignal.bot.max_updates import parse_update
from domsignal.contracts.onboarding import OpenAccessChange
from domsignal.services import bot_replies
from domsignal.services.explicit_reports import looks_like_no_problem
from domsignal.services.personal_bot import split_command
from domsignal.tools.max_subscription import EXPECTED_UPDATE_TYPES


def provider(handler: Any) -> HttpMaxChatProvider:
    return HttpMaxChatProvider(
        base_url="https://platform-api2.max.ru",
        token="synthetic-contract-token",
        timeout=3,
        transport=httpx.MockTransport(handler),
    )


def now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


# ------------------------------------------------ GET /chats/{id}/members


async def test_member_check_asks_for_exactly_one_user() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "members": [
                    {
                        "user_id": 731,
                        "name": "Synthetic",
                        "is_admin": False,
                        "is_owner": False,
                        "is_bot": False,
                        "last_access_time": 1,
                        "join_time": 1,
                    }
                ],
                "marker": None,
            },
        )

    assert await provider(handler).is_chat_member("-101", "731") is True
    [request] = seen
    assert request.url.path == "/chats/-101/members"
    assert dict(request.url.params) == {"user_ids": "731"}  # без count/marker и списка
    assert request.headers["Authorization"] == "synthetic-contract-token"


async def test_an_empty_member_list_means_not_a_member() -> None:
    result = await provider(lambda _: httpx.Response(200, json={"members": []})).is_chat_member(
        "-101", "731"
    )
    assert result is False


async def test_a_member_list_about_someone_else_is_invalid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"members": [{"user_id": 999, "is_bot": False}]})

    with pytest.raises(MaxProviderError) as error:
        await provider(handler).is_chat_member("-101", "731")
    assert error.value.code == "max_invalid_response"


@pytest.mark.parametrize(
    "status,code,temporary",
    [
        (403, "max_chat_inaccessible", False),
        (404, "max_chat_not_found", False),
        (429, "max_temporarily_unavailable", True),
        (503, "max_temporarily_unavailable", True),
    ],
)
async def test_member_check_errors_are_sanitized(status: int, code: str, temporary: bool) -> None:
    with pytest.raises(MaxProviderError) as error:
        await provider(lambda _: httpx.Response(status, text="secret body")).is_chat_member(
            "-101", "731"
        )
    assert (error.value.code, error.value.temporary) == (code, temporary)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("user_id", ["", "0", "abc", "1;2", "-5", "9" * 25])
async def test_a_bad_user_id_never_reaches_http(user_id: str) -> None:
    def fail(_: httpx.Request) -> httpx.Response:  # pragma: no cover - не должен вызываться
        raise AssertionError("HTTP call with an invalid user id")

    with pytest.raises(MaxProviderError):
        await provider(fail).is_chat_member("-101", user_id)


# ---------------------------------------------------------------- события


def test_user_added_and_removed_map_the_member_not_the_inviter() -> None:
    for kind, extra in (("user_added", {"inviter_id": 701}), ("user_removed", {"admin_id": 701})):
        event = parse_update(
            {
                "update_type": kind,
                "timestamp": now_ms(),
                "chat_id": -101,
                "user": {"user_id": 731, "name": "Synthetic"},
                "is_channel": False,
                **extra,
            }
        )
        assert (event.kind, event.chat_id, event.actor) == (kind, "-101", "731")


def test_a_bot_added_as_a_member_is_not_a_resident() -> None:
    event = parse_update(
        {
            "update_type": "user_added",
            "timestamp": now_ms(),
            "chat_id": -101,
            "user": {"user_id": 799, "is_bot": True},
        }
    )
    assert event.actor is None


def test_dialog_text_and_bot_callbacks_are_parsed() -> None:
    message = parse_update(
        {
            "update_type": "message_created",
            "timestamp": now_ms(),
            "message": {
                "sender": {"user_id": 731},
                "recipient": {"chat_id": 9731, "chat_type": "dialog"},
                "body": {"mid": "mid.dm-1", "text": "В первом подъезде не работает лифт"},
            },
        }
    )
    assert message.in_dialog and message.text and message.actor == "731"
    callback = parse_update(
        {
            "update_type": "message_callback",
            "timestamp": now_ms(),
            "callback": {
                "timestamp": now_ms(),
                "callback_id": "cb-1",
                "payload": "b:pick:max:abc:3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "user": {"user_id": 731},
            },
            "message": {
                "recipient": {"chat_id": 9731, "chat_type": "dialog"},
                "body": {"mid": "mid.bot-1"},
            },
        }
    )
    assert callback.bot_callback is not None and callback.callback is None
    assert callback.bot_callback.action == "pick"
    assert callback.bot_callback.argument == "max:abc:3fa85f64-5717-4562-b3fc-2c963f66afa6"


def test_a_bot_button_pressed_in_a_group_is_ignored() -> None:
    event = parse_update(
        {
            "update_type": "message_callback",
            "timestamp": now_ms(),
            "callback": {
                "timestamp": now_ms(),
                "callback_id": "cb-2",
                "payload": "b:houses",
                "user": {"user_id": 731},
            },
            "message": {
                "recipient": {"chat_id": -101, "chat_type": "chat"},
                "body": {"mid": "mid.bot-2"},
            },
        }
    )
    assert event.bot_callback is None


def test_the_subscription_adds_exactly_the_member_events() -> None:
    assert EXPECTED_UPDATE_TYPES == (
        "bot_started",
        "bot_stopped",
        "bot_added",
        "bot_removed",
        "message_created",
        "message_callback",
        "user_added",
        "user_removed",
    )


# ------------------------------------------------------------ личный бот


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/help", ("/help", "")),
        ("/report лифт стоит", ("/report", "лифт стоит")),
        ("/start@synthetic_bot", ("/start", "")),
        ("лифт стоит", (None, "лифт стоит")),
        ("/ не команда", (None, "/ не команда")),
    ],
)
def test_commands_are_split(text: str, expected: tuple[str | None, str]) -> None:
    assert split_command(text) == expected


def test_the_greeting_explains_the_product_in_three_or_four_lines() -> None:
    lines = bot_replies.GREETING.splitlines()
    assert 3 <= len(lines) <= 4
    assert "управляющей компании" in bot_replies.GREETING
    assert "куда обратиться" in bot_replies.GREETING


def test_no_test_or_demo_wording_in_the_open_access_and_bot_texts() -> None:
    texts = [
        value
        for name, value in vars(bot_replies).items()
        if name.isupper() and isinstance(value, str)
    ]
    for text in texts:
        lowered = text.lower()
        assert "тест" not in lowered and "демо" not in lowered, text


async def _analysis(text: str) -> Any:
    analysis = await WindowAnalyzer().analyze(
        WindowInput(
            channel="dm_report",
            lines=(
                WindowLine(line_id="m1", author_ref="a1", text=text, sent_at=datetime.now(UTC)),
            ),
        )
    )
    return analysis, decide_explicit_report(analysis)


async def test_chatter_is_not_a_problem_but_a_problem_or_danger_is() -> None:
    assert looks_like_no_problem(*await _analysis("Всем доброе утро, хорошего дня"))
    assert not looks_like_no_problem(*await _analysis("В первом подъезде не работает лифт"))
    assert not looks_like_no_problem(*await _analysis("В подъезде сильно пахнет газом"))


def test_enabling_open_access_requires_confirmation() -> None:
    with pytest.raises(ValidationError):
        OpenAccessChange(enabled=True)
    assert OpenAccessChange(enabled=True, confirm=True).enabled
    assert OpenAccessChange(enabled=False).enabled is False
