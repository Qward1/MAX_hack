"""Documented responses mapped over MockTransport, never live HTTP/token tests."""

import httpx
import pytest

from domsignal.bot.chat_provider import HttpMaxChatProvider, MaxProviderError
from domsignal.bot.max_updates import InvalidMaxUpdate, parse_update

MEMBER = {
    "user_id": 42,
    "first_name": "Synthetic",
    "is_bot": True,
    "is_admin": True,
    "is_owner": False,
    "permissions": ["read_all_messages"],
}


async def test_documented_chat_membership_admin_mapping() -> None:
    paths = []

    def response(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.url.host == "platform-api2.max.ru"
        assert request.headers["Authorization"] == "synthetic-contract-token"
        assert not request.url.query
        assert request.extensions["timeout"]["read"] == 3.0
        if request.url.path.endswith("/me"):
            value = MEMBER
        elif request.url.path.endswith("/admins"):
            value = {"members": [{**MEMBER, "user_id": 101, "is_bot": False}], "marker": None}
        else:
            value = {
                "chat_id": -101,
                "type": "chat",
                "status": "active",
                "title": "Test",
                "owner_id": 101,
                "participants": {"12": 0},
            }
        return httpx.Response(200, json=value)

    provider = HttpMaxChatProvider(
        base_url="https://platform-api2.max.ru",
        token="synthetic-contract-token",
        timeout=3,
        transport=httpx.MockTransport(response),
    )
    assert (await provider.get_chat_info("-101")).owner_id == "101"
    assert (await provider.get_bot_membership("-101")).permissions == {"read_all_messages"}
    assert (await provider.get_chat_admins("-101"))[0].user_id == "101"
    assert paths == ["/chats/-101", "/chats/-101/members/me", "/chats/-101/members/admins"]


@pytest.mark.parametrize(
    "status,code,temporary",
    [
        (401, "max_unauthorized", False),
        (403, "max_chat_inaccessible", False),
        (404, "max_chat_not_found", False),
        (429, "max_temporarily_unavailable", True),
        (500, "max_temporarily_unavailable", True),
        (503, "max_temporarily_unavailable", True),
        (302, "max_invalid_response", False),
    ],
)
async def test_http_errors_are_sanitized(status: int, code: str, temporary: bool) -> None:
    provider = HttpMaxChatProvider(
        base_url="https://platform-api2.max.ru",
        token="secret",
        timeout=1,
        transport=httpx.MockTransport(lambda _: httpx.Response(status, text="secret")),
    )
    with pytest.raises(MaxProviderError) as error:
        await provider.get_chat_info("-1")
    assert error.value.code == code and error.value.temporary == temporary
    assert "secret" not in str(error.value)


async def test_timeout_and_malformed_response_fail_closed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive upstream message", request=request)

    provider = HttpMaxChatProvider(
        base_url="https://platform-api2.max.ru",
        token="secret",
        timeout=1,
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(MaxProviderError, match="max_temporarily_unavailable"):
        await provider.get_chat_info("-1")
    for value in [{}, {**MEMBER, "is_admin": "true"}]:
        provider = HttpMaxChatProvider(
            base_url="https://platform-api2.max.ru",
            token="secret",
            timeout=1,
            transport=httpx.MockTransport(lambda _, v=value: httpx.Response(200, json=v)),
        )
        with pytest.raises(MaxProviderError, match="max_invalid_response"):
            await provider.get_bot_membership("-1")


def test_webhook_mapping_and_bad_identity() -> None:
    from datetime import UTC, datetime

    at = int(datetime.now(UTC).timestamp() * 1000)
    value = {
        "update_type": "bot_started",
        "timestamp": at,
        "chat_id": 1,
        "user": {"user_id": 2},
        "payload": "connect_synthetic",
    }
    event = parse_update(value)
    assert event.actor == "2" and event.chat_id == "1" and event.token == "connect_synthetic"
    assert event.event_id == parse_update(value).event_id
    with pytest.raises(InvalidMaxUpdate):
        parse_update({**value, "chat_id": True})


async def test_bad_chat_ids_never_reach_http() -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid chat ID reached HTTP")

    provider = HttpMaxChatProvider(
        base_url="https://platform-api2.max.ru",
        token="synthetic",
        timeout=1,
        transport=httpx.MockTransport(unexpected),
    )
    for chat_id in ["--1", "01", "../me", "1?token=x", "1" * 50]:
        with pytest.raises(MaxProviderError, match="max_invalid_chat_id"):
            await provider.get_chat_info(chat_id)


def test_channel_without_sender_and_forward_only_message_are_ignored() -> None:
    from datetime import UTC, datetime

    for message in [
        {
            "recipient": {"chat_id": -1, "chat_type": "channel"},
            "body": {"mid": "m1", "text": "channel post"},
        },
        {"recipient": {"chat_id": -1, "chat_type": "chat"}, "sender": {"user_id": 1}, "body": None},
    ]:
        event = parse_update(
            {
                "update_type": "message_created",
                "message": message,
                "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            }
        )
        assert event.text is None
