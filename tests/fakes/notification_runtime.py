"""Loopback-only test processes. No fixture routes or fake selection in production."""

import asyncio
import os
import sys

from fastapi import FastAPI, Request

from domsignal.bootstrap import build_container
from domsignal.bot.http_client import MaxHttpClient
from domsignal.bot.messaging import HttpMaxMessagingProvider
from domsignal.main import create_app
from domsignal.settings import Settings
from domsignal.worker.runner import WorkerRunner


def settings() -> Settings:
    if os.getenv("APP_ENV") != "test" or os.getenv("ND_FIXTURES") != "1":
        raise RuntimeError("Explicit isolated ND fixture opt-in is required")
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=os.environ["DATABASE_URL"],
        session_secret="nd-synthetic-session-secret",
        max_transport="webhook",
        max_webhook_secret="nd-synthetic-webhook-secret",
        max_bot_username="fixture_bot",
    )


def inject(container):
    # Only a supplied local port is accepted; this adapter cannot select a real upstream.
    port = int(os.environ["ND_PROVIDER_PORT"])
    container.notifications.provider = HttpMaxMessagingProvider(
        MaxHttpClient(
            base_url=f"http://127.0.0.1:{port}",
            token="synthetic-fixture-token",
            timeout=3,
        ),
        bot_username="fixture_bot",
    )
    if os.getenv("B09_BROWSER_FIXTURES") == "1":
        from tests.fakes.max_chat import FakeMaxChatProvider

        provider = FakeMaxChatProvider()
        chat_id = f"b09-{os.environ['ND_RUN_ID']}"
        provider.configure(chat_id, connector=chat_id)
        container.chat_connections.provider = provider
    return container


def app():
    application = create_app(settings())
    inject(application.state.container)
    return application


def provider_app():
    settings()  # same explicit opt-in
    application = FastAPI()
    events: list[dict] = []
    messages: dict[str, dict] = {}

    @application.post("/messages")
    async def send(request: Request, user_id: int):
        body = await request.json()
        mid = f"mid.fixture-{os.environ['ND_RUN_ID']}-{len(messages) + 1}"
        messages[mid] = body
        events.append({"operation": "send", "destination": str(user_id), "mid": mid, "body": body})
        return {
            "message": {
                "body": {"mid": mid},
                "recipient": {
                    "user_id": user_id,
                    "chat_id": user_id + 10000,
                    "chat_type": "dialog",
                },
            }
        }

    @application.put("/messages")
    async def edit(request: Request, message_id: str):
        if message_id not in messages:
            return {"success": False}
        body = await request.json()
        messages[message_id] = body
        events.append({"operation": "edit", "mid": message_id, "body": body})
        return {"success": True}

    @application.post("/answers")
    async def answer(request: Request, callback_id: str):
        events.append(
            {"operation": "answer", "callback_id": callback_id, "body": await request.json()}
        )
        return {"success": True}

    @application.get("/fixture-events")
    async def recording():
        return {"events": events, "messages": messages}

    return application


async def worker():
    container = inject(build_container(settings()))
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        notifications=container.notifications,
    )
    try:
        while True:
            if not await runner.run_once():
                await asyncio.sleep(0.1)
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    if sys.argv[1:] != ["worker"]:
        raise ValueError("Expected worker")
    asyncio.run(worker())
