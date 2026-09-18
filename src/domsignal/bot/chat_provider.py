"""Typed, read-only MAX boundary. No subscription/polling or group creation."""

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, ValidationError

from domsignal.bot.http_client import MaxHttpClient


@dataclass(frozen=True)
class ChatInfo:
    chat_id: str
    type: str
    title: str | None
    bot_present: bool
    owner_id: str | None = None


@dataclass(frozen=True)
class ChatMember:
    user_id: str
    is_admin: bool
    is_owner: bool = False
    permissions: frozenset[str] = frozenset()
    is_bot: bool = False


class MaxProviderError(Exception):
    def __init__(self, code: str, *, temporary: bool = False) -> None:
        # Never include response bodies, credentials or request headers.
        super().__init__(code)
        self.code = code
        self.temporary = temporary


class MaxChatProvider(Protocol):
    async def get_chat_info(self, chat_id: str) -> ChatInfo: ...
    async def get_bot_membership(self, chat_id: str) -> ChatMember: ...
    async def get_chat_admins(self, chat_id: str) -> tuple[ChatMember, ...]: ...


class _ChatResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chat_id: StrictInt
    type: Literal["chat", "channel", "dialog"]
    status: Literal["active", "removed", "left", "closed"]
    title: str | None
    owner_id: StrictInt | None = None


class _MemberResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: StrictInt
    is_admin: StrictBool
    is_owner: StrictBool
    is_bot: StrictBool
    permissions: list[str] | None = None

    def internal(self) -> ChatMember:
        return ChatMember(
            str(self.user_id),
            self.is_admin,
            self.is_owner,
            frozenset(self.permissions or []),
            self.is_bot,
        )


class _AdminsResponse(BaseModel):
    members: list[_MemberResponse]
    marker: StrictInt | None = None


class HttpMaxChatProvider:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client = MaxHttpClient(
            base_url=base_url, token=token, timeout=timeout, transport=transport,
        )

    async def _get(self, chat_id: str, suffix: str = "") -> Any:
        # External IDs cannot inject URL paths or query strings.
        if not re.fullmatch(r"-?\d{1,20}", chat_id) or str(int(chat_id)) != chat_id:
            raise MaxProviderError("max_invalid_chat_id")
        if not self.client.configured:
            raise MaxProviderError("max_not_configured", temporary=True)
        try:
            response = await self.client.request("GET", f"/chats/{chat_id}{suffix}")
        except (httpx.RequestError, TimeoutError):
            raise MaxProviderError("max_temporarily_unavailable", temporary=True) from None
        if response.status_code == 429 or response.status_code >= 500:
            raise MaxProviderError("max_temporarily_unavailable", temporary=True)
        errors = {401: "max_unauthorized", 403: "max_chat_inaccessible", 404: "max_chat_not_found"}
        if response.status_code != 200:
            raise MaxProviderError(errors.get(response.status_code, "max_invalid_response"))
        try:
            return response.json()
        except ValueError:
            raise MaxProviderError("max_invalid_response") from None

    async def get_chat_info(self, chat_id: str) -> ChatInfo:
        try:
            value = _ChatResponse.model_validate(await self._get(chat_id))
        except ValidationError:
            raise MaxProviderError("max_invalid_response") from None
        if str(value.chat_id) != chat_id:
            raise MaxProviderError("max_invalid_response")
        return ChatInfo(
            chat_id,
            value.type,
            value.title,
            value.status == "active",
            str(value.owner_id) if value.owner_id is not None else None,
        )

    async def get_bot_membership(self, chat_id: str) -> ChatMember:
        try:
            member = _MemberResponse.model_validate(await self._get(chat_id, "/members/me"))
        except ValidationError:
            raise MaxProviderError("max_invalid_response") from None
        if not member.is_bot:
            raise MaxProviderError("max_invalid_response")
        return member.internal()

    async def get_chat_admins(self, chat_id: str) -> tuple[ChatMember, ...]:
        try:
            value = _AdminsResponse.model_validate(await self._get(chat_id, "/members/admins"))
        except ValidationError:
            raise MaxProviderError("max_invalid_response") from None
        # Documented admins method returns all admins. Do not invent pagination.
        if value.marker is not None:
            raise MaxProviderError("max_admin_pagination_unsupported")
        return tuple(member.internal() for member in value.members)
