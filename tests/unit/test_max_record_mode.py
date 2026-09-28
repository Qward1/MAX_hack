"""F1 §3.2: эмулятор MAX — режим `record` только для локального стенда.

Двойник MAX API отвечает в тех же формах, что настоящий MAX, поэтому
провайдеры бота работают с ним без изменений; production режим отвергает.
"""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from domsignal.api.init_data import validate_init_data
from domsignal.bot.chat_provider import HttpMaxChatProvider
from domsignal.bot.messaging import HttpMaxMessagingProvider, MessageButton, PersonalMessage
from domsignal.bot.recording_api import RecordingMaxApi
from domsignal.settings import PRODUCTION_MAX_BOT_USERNAME, Settings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import max_emulator  # noqa: E402


def test_production_refuses_record_mode() -> None:
    with pytest.raises(ValidationError, match="MAX_TRANSPORT must be webhook in production"):
        Settings(
            app_env="production",
            auth_mfa_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            database_url="postgresql+asyncpg://app:strong-password-123@db/domsignal",
            session_secret="a-production-secret-with-sufficient-entropy",
            allow_test_session=False,
            demo_seed=False,
            max_transport="record",
            max_bot_token="synthetic-token",
            max_webhook_secret="synthetic_webhook_secret_1234567890",
            max_bot_username=PRODUCTION_MAX_BOT_USERNAME,
            public_base_url="https://domsignal.example.ru",
            cors_origins=["https://domsignal.example.ru"],
            _env_file=None,
        )


def test_record_mode_needs_local_secret_token_and_bot_name() -> None:
    with pytest.raises(ValidationError, match="MAX_TRANSPORT=record requires MAX_WEBHOOK_SECRET"):
        Settings(max_transport="record", _env_file=None)
    settings = Settings(
        max_transport="record",
        max_webhook_secret="local-emulator-secret",
        max_bot_token="local-emulator-token",
        max_bot_username="domsignal_local_bot",
        _env_file=None,
    )
    assert settings.max_record_dir == "output/max-record"


def _state(directory: Path) -> None:
    emulator = max_emulator.Emulator("http://127.0.0.1:1", "s", directory, "t")
    emulator.chat(-1001, "Дом · Проверочная, 1", admin=1001, members=[1002], bot_admin=True)
    emulator.set_bot(-1001, True)


async def test_bot_providers_work_against_the_recording_api(tmp_path: Path) -> None:
    _state(tmp_path)
    transport = RecordingMaxApi(tmp_path)
    chats = HttpMaxChatProvider(
        base_url="https://max.invalid", token="local", timeout=5, transport=transport
    )
    info = await chats.get_chat_info("-1001")
    assert info.title == "Дом · Проверочная, 1" and info.bot_present
    bot = await chats.get_bot_membership("-1001")
    assert bot.is_bot and bot.is_admin and "read_all_messages" in bot.permissions
    admins = await chats.get_chat_admins("-1001")
    assert [a.user_id for a in admins] == ["1001"]
    assert await chats.is_chat_member("-1001", "1002")
    assert not await chats.is_chat_member("-1001", "4242")

    messaging = HttpMaxMessagingProvider(chats.client, bot_username="domsignal_local_bot")
    message = PersonalMessage(
        text="Код подключения принят", buttons=((MessageButton("callback", "Готово", "b:done"),),)
    )
    sent = await messaging.send_personal_message("1002", message)
    await messaging.send_chat_message("-1001", PersonalMessage(text="Бот подключён", buttons=()))
    await messaging.edit_message(sent.message_id, PersonalMessage(text="Изменено", buttons=()))
    await messaging.notify_callback("cb.1", "Принято")
    rows = [
        json.loads(line)
        for line in (tmp_path / "outbox.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [row["kind"] for row in rows] == ["send", "send", "edit", "answer"]
    assert rows[0]["params"] == {"user_id": "1002"} and rows[1]["params"] == {"chat_id": "-1001"}
    described = max_emulator.describe(rows[0])
    assert "личка 1002" in described and "Код подключения принят" in described
    assert "[Готово]" in described


async def test_unknown_chat_is_not_found(tmp_path: Path) -> None:
    chats = HttpMaxChatProvider(
        base_url="https://max.invalid",
        token="local",
        timeout=5,
        transport=RecordingMaxApi(tmp_path),
    )
    with pytest.raises(Exception, match="max_chat_not_found"):
        await chats.get_chat_info("-9999")


def test_emulator_init_data_passes_the_real_validation(tmp_path: Path) -> None:
    emulator = max_emulator.Emulator("http://127.0.0.1:1", "s", tmp_path, "local-emulator-token")
    raw = emulator.init_data(1002, "Житель", "h_demo")
    user = validate_init_data(raw, bot_token="local-emulator-token", max_age_seconds=300)
    assert str(user.id) == "1002"
    assert "start_param=h_demo" in raw
