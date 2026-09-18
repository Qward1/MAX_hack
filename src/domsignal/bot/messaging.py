"""Typed personal messaging port; production wire shapes stay in this adapter."""

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationError

from domsignal.bot.http_client import MaxHttpClient


@dataclass(frozen=True)
class MessageButton:
    kind: Literal["open_app", "callback"]
    text: str
    payload: str


@dataclass(frozen=True)
class PersonalMessage:
    text: str
    buttons: tuple[tuple[MessageButton, ...], ...]


@dataclass(frozen=True)
class SentMessage:
    message_id: str


class MessagingError(Exception):
    def __init__(
        self,
        code: str,
        *,
        kind: Literal["retry", "permanent", "unknown"],
        retry_after: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.kind = kind
        self.retry_after = retry_after


class MaxMessagingProvider(Protocol):
    async def send_personal_message(
        self,
        destination: str,
        message: PersonalMessage,
    ) -> SentMessage: ...
    async def edit_message(self, message_id: str, message: PersonalMessage) -> None: ...
    async def answer_callback(self, callback_id: str, message: PersonalMessage) -> None: ...


class _Body(BaseModel):
    mid: str = Field(min_length=1, max_length=200, pattern=r"^(mid\.)?[a-zA-Z0-9_-]+$")


class _Recipient(BaseModel):
    user_id: StrictInt
    chat_id: StrictInt
    chat_type: Literal["dialog"]


class _Sent(BaseModel):
    body: _Body
    recipient: _Recipient


class _SendResponse(BaseModel):
    message: _Sent


class _Success(BaseModel):
    success: StrictBool


class HttpMaxMessagingProvider:
    def __init__(self, client: MaxHttpClient, *, bot_username: str | None) -> None:
        self.client = client
        self.bot_username = bot_username

    def _body(self, message: PersonalMessage, *, notify: bool) -> dict[str, Any]:
        if not self.bot_username:
            raise MessagingError("MAX_APP_NOT_CONFIGURED", kind="permanent")
        buttons: list[list[dict[str, str]]] = []
        for row in message.buttons:
            buttons.append(
                [
                    {
                        "type": b.kind,
                        "text": b.text,
                        "payload": b.payload,
                        **({"web_app": self.bot_username} if b.kind == "open_app" else {}),
                    }
                    for b in row
                ]
            )
        return {
            "text": message.text,
            "notify": notify,
            "attachments": [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
            if buttons
            else [],
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str],
        body: dict[str, Any],
        *,
        send: bool = False,
    ) -> Any:
        if not self.client.configured:
            raise MessagingError("MAX_NOT_CONFIGURED", kind="permanent")
        try:
            response = await self.client.request(method, path, params=params, body=body)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise MessagingError("MAX_CONNECT_FAILURE", kind="retry") from None
        except (httpx.RequestError, TimeoutError):
            raise MessagingError(
                "MAX_OUTCOME_UNKNOWN",
                kind="unknown" if send else "retry",
            ) from None
        if response.status_code == 429:
            guidance = response.headers.get("Retry-After", "")
            delay = min(float(guidance), 3600.0) if guidance.isdigit() else None
            raise MessagingError("MAX_RATE_LIMIT", kind="retry", retry_after=delay)
        if response.status_code >= 500:
            # No documented idempotency guarantee: a server error may follow a committed POST.
            raise MessagingError("MAX_SERVER_ERROR", kind="unknown" if send else "retry")
        if response.status_code != 200:
            codes = {401: "MAX_UNAUTHORIZED", 403: "MAX_FORBIDDEN", 404: "MAX_NOT_FOUND"}
            raise MessagingError(codes.get(response.status_code, "MAX_REJECTED"), kind="permanent")
        try:
            return response.json()
        except ValueError:
            raise MessagingError(
                "MAX_INVALID_RESPONSE",
                kind="unknown" if send else "retry",
            ) from None

    async def send_personal_message(
        self,
        destination: str,
        message: PersonalMessage,
    ) -> SentMessage:
        if not re.fullmatch(r"[1-9]\d{0,18}", destination) or int(destination) > 2**63 - 1:
            raise MessagingError("MAX_INVALID_DESTINATION", kind="permanent")
        data = await self._request(
            "POST",
            "/messages",
            {"user_id": destination},
            self._body(message, notify=True),
            send=True,
        )
        try:
            result = _SendResponse.model_validate(data)
            if str(result.message.recipient.user_id) != destination:
                raise ValueError("Wrong destination")
        except (ValidationError, ValueError):
            raise MessagingError("MAX_INVALID_RESPONSE", kind="unknown") from None
        return SentMessage(result.message.body.mid)

    async def _boolean(
        self,
        method: str,
        path: str,
        params: dict[str, str],
        body: dict[str, Any],
    ) -> None:
        data = await self._request(method, path, params, body)
        try:
            value = _Success.model_validate(data)
        except ValidationError:
            raise MessagingError("MAX_INVALID_RESPONSE", kind="retry") from None
        if not value.success:
            raise MessagingError("MAX_OPERATION_REJECTED", kind="retry")

    async def edit_message(self, message_id: str, message: PersonalMessage) -> None:
        await self._boolean(
            "PUT",
            "/messages",
            {"message_id": message_id},
            self._body(message, notify=False),
        )

    async def answer_callback(self, callback_id: str, message: PersonalMessage) -> None:
        await self._boolean(
            "POST",
            "/answers",
            {"callback_id": callback_id},
            {"message": self._body(message, notify=False)},
        )
