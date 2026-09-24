"""Documented MAX Update -> internal event; no raw MAX JSON beyond this module."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationError

from domsignal.contracts.notifications import TicketCallback
from domsignal.services.errors import ServiceError


class InvalidMaxUpdate(ServiceError):
    status = 422
    code = "invalid_max_update"


class _User(BaseModel):
    user_id: StrictInt
    is_bot: StrictBool = False


class _Recipient(BaseModel):
    chat_id: StrictInt
    chat_type: str


class _Body(BaseModel):
    mid: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, max_length=10000)


class _Message(BaseModel):
    sender: _User | None = None
    recipient: _Recipient
    body: _Body | None = None
    # `LinkedMessage` («пересланное или ответное сообщение»): форма ссылки
    # разбирается отдельно и мягко, поэтому здесь остаётся сырой объект:
    # неожиданная форма ссылки не должна отвергать всё обновление.
    link: Any = None


#: Ссылка на исходное сообщение ответа: `link.type = reply`, `link.message.mid`.
_MID = re.compile(r"[A-Za-z0-9._-]{1,200}")


def _reply_to_mid(link: Any) -> str | None:
    """Идентификатор сообщения, на которое ответили, или `None`.

    Документированная форма MAX: `Message.link` — `LinkedMessage` с полями
    `type` (`forward` | `reply`), `sender`, `chat_id` и `message` (`MessageBody`
    с `mid`). Пересылка ответом не считается. Любая другая форма даёт `None`:
    ссылку продукт не угадывает, а реплика от этого не теряется.
    """
    if not isinstance(link, dict) or link.get("type") != "reply":
        return None
    message = link.get("message")
    mid = message.get("mid") if isinstance(message, dict) else None
    return mid if isinstance(mid, str) and _MID.fullmatch(mid) else None


class _Update(BaseModel):
    update_type: str
    timestamp: StrictInt


class _Lifecycle(_Update):
    chat_id: StrictInt
    user: _User
    is_channel: StrictBool = False
    payload: str | None = Field(default=None, max_length=512)


#: События жизненного цикла: бот в чате/диалоге и участники чата (D1).
LIFECYCLE_KINDS = frozenset(
    {"bot_started", "bot_stopped", "bot_added", "bot_removed", "user_added", "user_removed"}
)

#: Нажатие кнопки личного бота: `b:<действие>[:<аргумент>[:<аргумент>]]`.
BOT_CALLBACK = re.compile(r"b:([a-z_]{1,20})(?::([A-Za-z0-9_.:-]{1,300}))?")


class _Created(_Update):
    message: _Message


class _Callback(BaseModel):
    timestamp: StrictInt
    callback_id: str = Field(min_length=1, max_length=200)
    payload: str | None = Field(default=None, max_length=1024)
    user: _User


class _CallbackUpdate(_Update):
    callback: _Callback
    message: _Message | None


@dataclass(frozen=True)
class BotCallback:
    """Нажатие кнопки личного бота в диалоге. Права проверяет обработчик."""

    callback_id: str
    actor: str
    message_id: str
    action: str
    argument: str | None


@dataclass(frozen=True)
class MaxEvent:
    event_id: str
    kind: str
    occurred_at: datetime
    chat_id: str | None = None
    actor: str | None = None
    is_channel: bool = False
    token: str | None = None
    text: str | None = None
    callback: TicketCallback | None = None
    # Идентификатор сообщения MAX и ссылка на исходное сообщение ответа.
    # Идентичность события по-прежнему считается от `mid` выше.
    mid: str | None = None
    reply_to_mid: str | None = None
    #: `chat` — групповой чат, `dialog` — личка бота (D1).
    chat_type: str | None = None
    bot_callback: BotCallback | None = None

    @property
    def in_dialog(self) -> bool:
        return self.chat_type == "dialog"


def parse_update(payload: dict[str, Any]) -> MaxEvent:
    try:
        header = _Update.model_validate(payload)
        at = datetime.fromtimestamp(header.timestamp / 1000, UTC)
        if header.timestamp <= 0 or at > datetime.now(UTC) + timedelta(seconds=30):
            raise ValueError("Invalid timestamp")
        identity: list[str | int | bool] = [header.update_type, header.timestamp]
        if header.update_type in LIFECYCLE_KINDS:
            event = _Lifecycle.model_validate(payload)
            identity.extend([event.chat_id, event.user.user_id, event.is_channel])
            if event.payload:
                identity.append(hashlib.sha256(event.payload.encode()).hexdigest())
            fields: dict[str, Any] = dict(
                chat_id=str(event.chat_id),
                # У `user_added`/`user_removed` это участник, которого
                # добавили или который вышел; бот сам себя здесь не видит.
                actor=None
                if header.update_type in {"user_added", "user_removed"} and event.user.is_bot
                else str(event.user.user_id),
                is_channel=event.is_channel,
                token=event.payload if event.update_type == "bot_started" else None,
            )
        elif header.update_type == "message_created":
            created = _Created.model_validate(payload)
            message = created.message
            # A MAX message ID is unique within its chat; delivery timestamp isn't identity.
            identity = [
                header.update_type,
                message.recipient.chat_id,
                message.body.mid if message.body else header.timestamp,
            ]
            fields = dict(
                chat_id=str(message.recipient.chat_id),
                actor=str(message.sender.user_id) if message.sender else None,
                # Текст — только у человека в группе или в личке бота.
                text=message.body.text
                if message.body
                and message.sender
                and message.recipient.chat_type in {"chat", "dialog"}
                and not message.sender.is_bot
                else None,
                mid=message.body.mid if message.body else None,
                reply_to_mid=_reply_to_mid(message.link),
                chat_type=message.recipient.chat_type,
            )
        elif header.update_type == "message_callback":
            value = _CallbackUpdate.model_validate(payload)
            callback = value.callback
            identity = [header.update_type, callback.callback_id]
            fields = {}
            match = re.fullmatch(
                r"(w_[A-Za-z0-9_-]{32}):(resolved|unresolved)", callback.payload or ""
            )
            callback_message = value.message
            bot = BOT_CALLBACK.fullmatch(callback.payload or "")
            if (
                bot
                and not callback.user.is_bot
                and callback_message
                and callback_message.body
                and callback_message.recipient.chat_type == "dialog"
            ):
                fields = dict(
                    actor=str(callback.user.user_id),
                    chat_type="dialog",
                    bot_callback=BotCallback(
                        callback_id=callback.callback_id,
                        actor=str(callback.user.user_id),
                        message_id=callback_message.body.mid,
                        action=bot[1],
                        argument=bot[2],
                    ),
                )
            if (
                match
                and not callback.user.is_bot
                and callback_message
                and callback_message.body
                and callback_message.recipient.chat_type == "dialog"
            ):
                callback_event_id = (
                    "max:"
                    + hashlib.sha256(
                        json.dumps(identity, separators=(",", ":")).encode()
                    ).hexdigest()
                )
                fields = dict(
                    callback=TicketCallback(
                        event_id=callback_event_id,
                        callback_id=callback.callback_id,
                        actor=str(callback.user.user_id),
                        message_id=callback_message.body.mid,
                        launch_ref=match[1],
                        outcome=match[2],
                    )
                )
        else:
            fields = {}
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return MaxEvent("max:" + digest, header.update_type, at, **fields)
    except (ValueError, OverflowError, OSError, ValidationError):
        raise InvalidMaxUpdate("Invalid MAX update") from None
