import json

import httpx
import pytest

from domsignal.bootstrap import build_container
from domsignal.bot.http_client import MaxHttpClient
from domsignal.bot.messaging import (
    HttpMaxMessagingProvider,
    MessageButton,
    MessagingError,
    PersonalMessage,
)
from domsignal.settings import Settings

CARD = PersonalMessage(
    "Публичная работа",
    (
        (MessageButton("open_app", "Открыть", "w_" + "a" * 32),),
        (MessageButton("callback", "Исправлено", "w_" + "a" * 32 + ":resolved"),),
    ),
)


def provider(handler):
    return HttpMaxMessagingProvider(
        MaxHttpClient(
            base_url="https://max.invalid",
            token="test-secret",
            timeout=2,
            transport=httpx.MockTransport(handler),
        ),
        bot_username="test_bot",
    )


async def test_documented_send_edit_answer_shapes():
    seen = []

    def handler(request):
        assert request.headers["Authorization"] == "test-secret"
        assert "token" not in request.url.query.decode()
        body = json.loads(request.content)
        seen.append((request.method, request.url.path, dict(request.url.params), body))
        if request.method == "POST" and request.url.path == "/messages":
            return httpx.Response(
                200,
                json={
                    "message": {
                        "body": {"mid": "mid.provider-1"},
                        "recipient": {"user_id": 123, "chat_id": 456, "chat_type": "dialog"},
                    }
                },
            )
        return httpx.Response(200, json={"success": True})

    p = provider(handler)
    assert (await p.send_personal_message("123", CARD)).message_id == "mid.provider-1"
    await p.edit_message("mid.provider-1", CARD)
    await p.answer_callback("cb-1", CARD)
    assert [x[:3] for x in seen] == [
        ("POST", "/messages", {"user_id": "123"}),
        ("PUT", "/messages", {"message_id": "mid.provider-1"}),
        ("POST", "/answers", {"callback_id": "cb-1"}),
    ]
    keyboard = seen[0][3]["attachments"][0]
    assert keyboard["type"] == "inline_keyboard"
    assert keyboard["payload"]["buttons"][0][0] == {
        "type": "open_app",
        "text": "Открыть",
        "web_app": "test_bot",
        "payload": "w_" + "a" * 32,
    }
    assert seen[1][3]["notify"] is False
    assert seen[2][3] == {"message": seen[1][3]}


@pytest.mark.parametrize("operation", ["edit_message", "answer_callback"])
@pytest.mark.parametrize("body", [{"success": False}, {"success": "true"}, {}, {"success": 1}])
async def test_nd21_boolean_success_is_strict(operation, body):
    p = provider(lambda r: httpx.Response(200, json=body))
    with pytest.raises(MessagingError) as caught:
        await getattr(p, operation)("synthetic-id", CARD)
    assert caught.value.kind == "retry"


@pytest.mark.parametrize(
    "status,kind",
    [(429, "retry"), (401, "permanent"), (403, "permanent"), (400, "permanent"), (503, "unknown")],
)
async def test_send_http_errors_sanitized(status, kind):
    p = provider(
        lambda r: httpx.Response(
            status, headers={"Retry-After": "9"}, json={"message": "secret-private-upstream"}
        )
    )
    with pytest.raises(MessagingError) as caught:
        await p.send_personal_message("123", CARD)
    assert caught.value.kind == kind
    assert "secret" not in str(caught.value)
    if status == 429:
        assert caught.value.retry_after == 9


@pytest.mark.parametrize(
    "error,kind",
    [
        (httpx.ConnectError, "retry"),
        (httpx.ReadTimeout, "unknown"),
        (httpx.WriteTimeout, "unknown"),
    ],
)
async def test_nd25_network_outcome(error, kind):
    def handler(request):
        raise error("secret-private-error", request=request)

    with pytest.raises(MessagingError) as caught:
        await provider(handler).send_personal_message("123", CARD)
    assert caught.value.kind == kind
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        "bad json",
        "{}",
        '{"message":{"body":{"mid":""}}}',
        '{"message":{"body":{"mid":"mid.1"},"recipient":'
        '{"user_id":999,"chat_id":1,"chat_type":"dialog"}}}',
    ],
)
async def test_nd25_malformed_send_not_accepted(body):
    with pytest.raises(MessagingError) as caught:
        await provider(lambda r: httpx.Response(200, content=body)).send_personal_message(
            "123", CARD
        )
    assert caught.value.kind == "unknown"


async def test_nd24_composition_never_chooses_fake():
    for mode in ("off", "recording", "webhook"):
        c = build_container(Settings(max_transport=mode, _env_file=None))
        assert isinstance(c.notifications.provider, HttpMaxMessagingProvider)
        assert c.notifications.enabled == (mode == "webhook")
        await c.engine.dispose()
