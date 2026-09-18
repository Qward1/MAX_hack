"""Fail-closed operator CLI for the single approved MAX webhook subscription."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from domsignal.settings import AppEnvironment, MaxTransportMode, Settings, get_settings

EXPECTED_UPDATE_TYPES = (
    "bot_started",
    "bot_stopped",
    "bot_added",
    "bot_removed",
    "message_created",
    "message_callback",
)


class SubscriptionError(RuntimeError):
    """Safe operator-facing failure with no credential or response-body details."""


class _Subscription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    update_types: list[str]


class _Subscriptions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subscriptions: list[_Subscription]


class _Success(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: StrictBool


class _Bot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    username: str
    is_bot: StrictBool


@dataclass(frozen=True, repr=False)
class SubscriptionConfig:
    api_base_url: str
    public_base_url: str
    bot_username: str
    token: str
    webhook_secret: str
    timeout: float = 15.0

    @classmethod
    def from_settings(cls, settings: Settings) -> SubscriptionConfig:
        if settings.app_env is not AppEnvironment.PRODUCTION:
            raise SubscriptionError("subscription commands require APP_ENV=production")
        if settings.max_transport is not MaxTransportMode.WEBHOOK:
            raise SubscriptionError("subscription commands require MAX_TRANSPORT=webhook")
        if not settings.max_bot_token or not settings.max_webhook_secret:
            raise SubscriptionError("MAX bot token and webhook secret are required")
        return cls(
            api_base_url=settings.max_api_base_url,
            public_base_url=settings.public_base_url.rstrip("/"),
            bot_username=settings.max_bot_username or "",
            token=settings.max_bot_token,
            webhook_secret=settings.max_webhook_secret,
            timeout=max(settings.max_api_timeout_seconds, 15.0),
        )

    @property
    def webhook_url(self) -> str:
        return f"{self.public_base_url}/max/webhook"


class SubscriptionManager:
    def __init__(
        self,
        config: SubscriptionConfig,
        *,
        max_transport: httpx.BaseTransport | None = None,
        public_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._max_transport = max_transport
        self._public_transport = public_transport

    def _max_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        with httpx.Client(
            base_url=self.config.api_base_url,
            headers={"Authorization": self.config.token},
            timeout=self.config.timeout,
            follow_redirects=False,
            transport=self._max_transport,
        ) as client:
            response = client.request(method, path, params=params, json=body)
        if response.status_code != 200:
            raise SubscriptionError(f"MAX {method} {path} returned HTTP {response.status_code}")
        return response

    def verify_bot_identity(self) -> None:
        response = self._max_request("GET", "/me")
        try:
            bot = _Bot.model_validate(response.json())
        except (ValueError, ValidationError):
            raise SubscriptionError("MAX returned an invalid bot identity") from None
        if not bot.is_bot or bot.username != self.config.bot_username:
            raise SubscriptionError("MAX token belongs to an unexpected bot; no mutation was made")

    def _list(self) -> tuple[_Subscription, ...]:
        response = self._max_request("GET", "/subscriptions")
        try:
            value = _Subscriptions.model_validate(response.json())
        except (ValueError, ValidationError):
            raise SubscriptionError("MAX returned an invalid subscriptions response") from None
        return tuple(value.subscriptions)

    def list(self) -> tuple[_Subscription, ...]:
        self.verify_bot_identity()
        return self._list()

    def _single_expected(self, subscriptions: tuple[_Subscription, ...]) -> _Subscription | None:
        if not subscriptions:
            return None
        if len(subscriptions) != 1 or subscriptions[0].url != self.config.webhook_url:
            raise SubscriptionError(
                "subscription conflict: existing subscriptions were not changed; inspect `list`"
            )
        return subscriptions[0]

    @staticmethod
    def _has_expected_types(subscription: _Subscription) -> bool:
        return len(subscription.update_types) == len(EXPECTED_UPDATE_TYPES) and set(
            subscription.update_types
        ) == set(EXPECTED_UPDATE_TYPES)

    def preflight_public_endpoint(self) -> None:
        with httpx.Client(
            base_url=self.config.public_base_url,
            timeout=self.config.timeout,
            follow_redirects=False,
            transport=self._public_transport,
        ) as client:
            ready = client.get("/ready")
            denied = client.post("/max/webhook", json={})
            authenticated = client.post(
                "/max/webhook",
                json={},
                headers={"X-Max-Bot-Api-Secret": self.config.webhook_secret},
            )
        if ready.status_code != 200:
            raise SubscriptionError(f"public /ready returned HTTP {ready.status_code}")
        try:
            if ready.json().get("status") != "ready":
                raise ValueError
        except (AttributeError, ValueError):
            raise SubscriptionError("public /ready returned an invalid body") from None
        if denied.status_code != 401:
            raise SubscriptionError(
                f"webhook without secret returned HTTP {denied.status_code}, expected 401"
            )
        if authenticated.status_code != 422:
            raise SubscriptionError(
                "webhook authentication preflight did not reach payload validation "
                f"(HTTP {authenticated.status_code}, expected 422)"
            )

    def _post_expected(self) -> None:
        response = self._max_request(
            "POST",
            "/subscriptions",
            body={
                "url": self.config.webhook_url,
                "update_types": list(EXPECTED_UPDATE_TYPES),
                "secret": self.config.webhook_secret,
            },
        )
        try:
            success = _Success.model_validate(response.json())
        except (ValueError, ValidationError):
            raise SubscriptionError("MAX returned an invalid subscription result") from None
        if not success.success:
            raise SubscriptionError(
                "MAX returned success=false; subscription state was not trusted"
            )

    def _verify_expected(self) -> None:
        subscription = self._single_expected(self._list())
        if subscription is None or not self._has_expected_types(subscription):
            raise SubscriptionError("subscription verification failed after MAX mutation")

    def register(self) -> Literal["registered", "already_registered"]:
        self.verify_bot_identity()
        existing = self._single_expected(self._list())
        if existing is not None and not self._has_expected_types(existing):
            raise SubscriptionError(
                "the expected URL has different update types; use `replace` after review"
            )
        self.preflight_public_endpoint()
        if existing is not None:
            return "already_registered"
        self._post_expected()
        self._verify_expected()
        return "registered"

    def replace(self) -> Literal["replaced"]:
        self.verify_bot_identity()
        existing = self._single_expected(self._list())
        if existing is None:
            raise SubscriptionError("there is no expected subscription to replace; use `register`")
        self.preflight_public_endpoint()
        # MAX documents POST /subscriptions as the update operation for an existing URL.
        self._post_expected()
        self._verify_expected()
        return "replaced"

    def delete(self) -> Literal["deleted", "already_absent"]:
        self.verify_bot_identity()
        existing = self._single_expected(self._list())
        if existing is None:
            return "already_absent"
        response = self._max_request(
            "DELETE",
            "/subscriptions",
            params={"url": self.config.webhook_url},
        )
        try:
            success = _Success.model_validate(response.json())
        except (ValueError, ValidationError):
            raise SubscriptionError("MAX returned an invalid unsubscription result") from None
        if not success.success:
            raise SubscriptionError(
                "MAX returned success=false; subscription state was not trusted"
            )
        if self._list():
            raise SubscriptionError("subscription verification failed after DELETE")
        return "deleted"


def _print_subscriptions(
    config: SubscriptionConfig, subscriptions: tuple[_Subscription, ...]
) -> None:
    print(
        json.dumps(
            {
                "verified_bot_username": config.bot_username,
                "expected_url": config.webhook_url,
                "expected_update_types": list(EXPECTED_UPDATE_TYPES),
                "subscriptions": [item.model_dump() for item in subscriptions],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "preflight", "register", "replace", "delete"))
    args = parser.parse_args()
    try:
        config = SubscriptionConfig.from_settings(get_settings())
        manager = SubscriptionManager(config)
        if args.action == "list":
            _print_subscriptions(config, manager.list())
        elif args.action == "preflight":
            manager.preflight_public_endpoint()
            print(json.dumps({"status": "preflight_ok", "url": config.webhook_url}))
        else:
            result = getattr(manager, args.action)()
            print(json.dumps({"status": result, "url": config.webhook_url}))
        return 0
    except (SubscriptionError, httpx.HTTPError, TimeoutError) as exc:
        if isinstance(exc, SubscriptionError):
            message = str(exc)
        else:
            message = "network or TLS failure; no subscription mutation was trusted"
        print(f"ERROR: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
