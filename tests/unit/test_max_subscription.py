import json

import httpx
import pytest

from domsignal.tools.max_subscription import (
    EXPECTED_UPDATE_TYPES,
    SubscriptionConfig,
    SubscriptionError,
    SubscriptionManager,
)


def config() -> SubscriptionConfig:
    return SubscriptionConfig(
        api_base_url="https://platform-api2.max.ru",
        public_base_url="https://bot.example",
        bot_username="t480_hakaton_max_bot",
        token="synthetic-token",
        webhook_secret="synthetic_webhook_secret",
    )


def public_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/ready":
        return httpx.Response(200, json={"status": "ready"})
    assert request.url.path == "/max/webhook"
    return httpx.Response(422 if "X-Max-Bot-Api-Secret" in request.headers else 401)


def test_register_preflights_posts_and_verifies_exact_subscription() -> None:
    requests: list[httpx.Request] = []
    registered = False

    def max_transport(request: httpx.Request) -> httpx.Response:
        nonlocal registered
        requests.append(request)
        if request.url.path == "/me":
            return httpx.Response(200, json={"username": "t480_hakaton_max_bot", "is_bot": True})
        if request.method == "GET":
            items = (
                [
                    {
                        "url": config().webhook_url,
                        "update_types": list(EXPECTED_UPDATE_TYPES),
                    }
                ]
                if registered
                else []
            )
            return httpx.Response(200, json={"subscriptions": items})
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body == {
            "url": config().webhook_url,
            "update_types": list(EXPECTED_UPDATE_TYPES),
            "secret": "synthetic_webhook_secret",
        }
        assert request.headers["Authorization"] == "synthetic-token"
        registered = True
        return httpx.Response(200, json={"success": True})

    manager = SubscriptionManager(
        config(),
        max_transport=httpx.MockTransport(max_transport),
        public_transport=httpx.MockTransport(public_transport),
    )
    assert manager.register() == "registered"
    assert [request.url.path for request in requests] == [
        "/me",
        "/subscriptions",
        "/subscriptions",
        "/subscriptions",
    ]
    assert [request.method for request in requests] == ["GET", "GET", "POST", "GET"]


def test_foreign_subscription_stops_before_any_mutation() -> None:
    requests: list[httpx.Request] = []

    def max_transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/me":
            return httpx.Response(200, json={"username": "t480_hakaton_max_bot", "is_bot": True})
        return httpx.Response(
            200,
            json={
                "subscriptions": [
                    {
                        "url": "https://other.example/webhook",
                        "update_types": ["message_created"],
                    }
                ]
            },
        )

    manager = SubscriptionManager(config(), max_transport=httpx.MockTransport(max_transport))
    with pytest.raises(SubscriptionError, match="conflict"):
        manager.replace()
    assert [request.url.path for request in requests] == ["/me", "/subscriptions"]


def test_token_for_another_bot_stops_before_subscription_read() -> None:
    requests: list[httpx.Request] = []

    def max_transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"username": "another_bot", "is_bot": True})

    manager = SubscriptionManager(config(), max_transport=httpx.MockTransport(max_transport))
    with pytest.raises(SubscriptionError, match="unexpected bot"):
        manager.list()
    assert [request.url.path for request in requests] == ["/me"]


def test_delete_only_expected_url_and_verify_empty() -> None:
    requests: list[httpx.Request] = []
    exists = True

    def max_transport(request: httpx.Request) -> httpx.Response:
        nonlocal exists
        requests.append(request)
        if request.url.path == "/me":
            return httpx.Response(200, json={"username": "t480_hakaton_max_bot", "is_bot": True})
        if request.method == "GET":
            subscriptions = (
                [
                    {
                        "url": config().webhook_url,
                        "update_types": list(EXPECTED_UPDATE_TYPES),
                    }
                ]
                if exists
                else []
            )
            return httpx.Response(200, json={"subscriptions": subscriptions})
        assert request.method == "DELETE"
        assert request.url.params["url"] == config().webhook_url
        exists = False
        return httpx.Response(200, json={"success": True})

    manager = SubscriptionManager(config(), max_transport=httpx.MockTransport(max_transport))
    assert manager.delete() == "deleted"
    assert [request.method for request in requests] == ["GET", "GET", "DELETE", "GET"]
