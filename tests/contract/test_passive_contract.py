"""Контракт пассивного чтения: MAX-формы, голос бота в чате, журналы без текста.

Проверки идут по самим шаблонам и формам запроса: так запрещённая формулировка
или недокументированное поле не проедут в новой константе мимо сценариев.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from domsignal.bot.http_client import MaxHttpClient
from domsignal.bot.max_updates import parse_update
from domsignal.bot.messaging import HttpMaxMessagingProvider, MessagingError, PersonalMessage
from domsignal.contracts.routing import SafetyBlock
from domsignal.services import chat_voice
from domsignal.services.action_cards import FORBIDDEN_PHRASES

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SAFETY = SafetyBlock(
    title="При угрозе жизни и здоровью звоните 112",
    lines=["ДомСигнал не заменяет экстренные службы."],
    phone="112",
    source_title="Федеральный закон от 30.12.2020 № 488-ФЗ",
)


def provider(handler):  # noqa: ANN001, ANN201
    return HttpMaxMessagingProvider(
        MaxHttpClient(
            base_url="https://max.invalid",
            token="test-secret",
            timeout=2,
            transport=httpx.MockTransport(handler),
        ),
        bot_username="test_bot",
    )


# ------------------------------------------------------------- MAX: отправка


async def test_chat_message_uses_the_documented_post_with_chat_id() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        body = json.loads(request.content)
        assert body["text"] == "Памятка" and body["attachments"] == []
        return httpx.Response(
            200,
            json={
                "message": {
                    "body": {"mid": "mid.chat-1"},
                    "recipient": {"chat_id": -701, "chat_type": "chat"},
                }
            },
        )

    sent = await provider(handler).send_chat_message("-701", PersonalMessage("Памятка", ()))
    assert sent.message_id == "mid.chat-1"
    assert seen == [("POST", "/messages", {"chat_id": "-701"})]


@pytest.mark.parametrize(
    "recipient",
    [
        {"chat_id": -702, "chat_type": "chat"},
        {"chat_id": -701, "chat_type": "dialog", "user_id": 5},
        {"chat_id": "-701", "chat_type": "chat"},
    ],
)
async def test_chat_send_to_the_wrong_place_is_not_accepted(recipient: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200, json={"message": {"body": {"mid": "mid.x"}, "recipient": recipient}}
        )

    with pytest.raises(MessagingError) as error:
        await provider(handler).send_chat_message("-701", PersonalMessage("Памятка", ()))
    assert error.value.kind == "unknown"


@pytest.mark.parametrize("chat_id", ["", "0", "abc", "-0", "1" * 20, "-701 ", "7e3"])
async def test_bad_chat_ids_never_reach_http(chat_id: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call expected")

    with pytest.raises(MessagingError) as error:
        await provider(handler).send_chat_message(chat_id, PersonalMessage("Памятка", ()))
    assert error.value.code == "MAX_INVALID_DESTINATION" and error.value.kind == "permanent"


# ------------------------------------------------------------ MAX: обновление


def _created(**message: object) -> dict[str, object]:
    return {
        "update_type": "message_created",
        "timestamp": int(datetime.now(UTC).timestamp() * 1000),
        "message": {
            "sender": {"user_id": 5, "is_bot": False},
            "recipient": {"chat_id": -701, "chat_type": "chat"},
            "body": {"mid": "mid.abc", "text": "Лифт стоит"},
            **message,
        },
    }


def test_message_id_and_reply_link_come_from_documented_fields() -> None:
    event = parse_update(_created(link={"type": "reply", "message": {"mid": "mid.orig"}}))
    assert event.mid == "mid.abc" and event.reply_to_mid == "mid.orig"
    # Идентичность события по-прежнему считается по `mid`, а не по ссылке.
    assert event.event_id == parse_update(_created()).event_id


@pytest.mark.parametrize(
    "link",
    [
        {"type": "forward", "message": {"mid": "mid.orig"}},
        {"type": "reply"},
        {"type": "reply", "message": {"mid": 42}},
        {"type": "reply", "message": {"mid": "bad mid with spaces"}},
        "reply",
        None,
    ],
)
def test_an_unexpected_link_shape_is_not_guessed(link: object) -> None:
    event = parse_update(_created(link=link))
    assert event.reply_to_mid is None and event.text == "Лифт стоит"


# -------------------------------------------------------------- голос бота


def test_chat_voice_templates_avoid_forbidden_phrases() -> None:
    texts = [
        chat_voice.reading_notice_text("УК «Тест»"),
        chat_voice.reading_notice_text(None),
        chat_voice.safety_memo_text(SAFETY),
        chat_voice.operator_alert_message(
            house_address="Казань, улица, 1",
            danger_kinds=["gas", "person_trapped"],
            from_rules=True,
            quote="Пахнет газом",
            quote_author="A",
            quote_sent_at=datetime.now(UTC),
        ).text,
    ]
    for text in texts:
        lowered = text.lower()
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in lowered, (phrase, text)


def test_the_reading_notice_says_who_what_how_rarely_and_who_turns_it_off() -> None:
    text = chat_voice.reading_notice_text("Первая")
    assert "управляющей компанией «Первая»" in text  # кто подключил
    assert "читает сообщения этого чата" in text  # что делает
    assert "замечать проблемы дома" in text  # зачем
    assert "пишет сюда редко" in text  # как редко
    assert "кнопка «Открыть ДомСигнал»" in text  # D1: вход из чата
    assert "не является официальным обращением" in text
    assert "Отключить чтение может управляющая компания «Первая»" in text
    # Никаких ссылок, телефонов и сроков.
    assert not re.search(r"https?://|www\.|\+7|\b8\d{3}|\d+\s*(час|дн|сут|минут)", text)


def test_the_memo_is_only_the_verified_safety_block() -> None:
    text = chat_voice.safety_memo_text(SAFETY)
    lines = text.split("\n")
    assert lines[0] == "ДомСигнал: в чате написали о признаках опасности."
    assert lines[1:] == [
        "При угрозе жизни и здоровью звоните 112",
        "ДомСигнал не заменяет экстренные службы.",
        "Единый номер экстренных служб: 112",
        "Источник: Федеральный закон от 30.12.2020 № 488-ФЗ",
    ]


def test_the_memo_repeats_the_federal_safety_file() -> None:
    import yaml  # type: ignore[import-untyped]

    document = yaml.safe_load(
        (REPOSITORY_ROOT / "regions/_federal/safety.yaml").read_text(encoding="utf-8")
    )
    block = document["blocks"][0]
    assert block["phone"] == "112" and block["verification"]["status"] == "verified"


def test_chat_intents_have_no_field_for_model_prose() -> None:
    fields = set(chat_voice.ChatMessageIntent.model_fields)
    assert not fields & {"clean_description", "description", "summary"}
    assert set(chat_voice.SignalAlertIntent.model_fields) == {
        "signal_id",
        "house_id",
        "new_kinds",
        "evidence_mid",
    }


def test_operator_alert_has_no_button_to_nowhere() -> None:
    message = chat_voice.operator_alert_message(
        house_address="Казань, улица, 1",
        danger_kinds=["electric"],
        from_rules=False,
        quote=None,
        quote_author=None,
        quote_sent_at=None,
    )
    assert message.buttons == ()
    assert "Признак найден при разборе переписки." in message.text


# ------------------------------------------------------------------ журналы

PASSIVE_MODULES = (
    "src/domsignal/services/passive_capture.py",
    "src/domsignal/services/passive_analysis.py",
    "src/domsignal/services/notifications.py",
)
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}
_FORBIDDEN_KEYS = {"text", "quote", "external_user_id", "actor", "author", "details"}


def _extra_keys(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        found.append((node.lineno, key.value))
    return found


@pytest.mark.parametrize("module", PASSIVE_MODULES)
def test_log_extras_never_clash_with_log_record_or_carry_text(module: str) -> None:
    keys = _extra_keys(REPOSITORY_ROOT / module)
    assert keys, module
    for line, key in keys:
        # Зарезервированный ключ роняет запись журнала, а с ней — транзакцию.
        assert key not in _RESERVED, (module, line, key)
        assert key not in _FORBIDDEN_KEYS, (module, line, key)
