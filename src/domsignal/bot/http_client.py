"""Shared MAX HTTP configuration/credentials boundary. Never follows redirects."""

import asyncio
from typing import Any

import httpx


class MaxHttpClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._token)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        async with (
            asyncio.timeout(self.timeout),
            httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client,
        ):
            return await client.request(
                method,
                path,
                params=params,
                json=body,
                headers={"Authorization": self._token or ""},
            )
