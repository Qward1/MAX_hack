"""Общий стенд явного пути: подключённый чат, дом с профилем и приёмом заявок.

Стенд намеренно не использует демо-дома из `seed_demo`: явный путь проверяется
на собственных синтетических данных, чтобы проверки не зависели от решения о
демонстрации.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from domsignal.db.models import (
    House,
    HouseManagement,
    HouseRoutingProfile,
    ManagementCompany,
    OrganizationMembership,
    ResidentMembership,
    User,
)
from domsignal.main import create_app
from domsignal.worker.pools import WorkerPool
from domsignal.worker.runner import WorkerRunner
from tests.fakes.max_chat import FakeMaxChatProvider
from tests.fakes.max_messaging import RecordingMaxMessagingProvider

WEBHOOK_SECRET = "synthetic-webhook-secret"


@dataclass
class ExplicitHarness:
    client: AsyncClient
    container: Any
    fake: FakeMaxChatProvider
    messaging: RecordingMaxMessagingProvider
    ids: dict[str, Any]
    headers: dict[str, dict[str, str]]

    async def webhook(self, kind: str, chat: str = "-501", actor: int = 501, **extra: Any) -> Any:
        payload = {
            "update_type": kind,
            "timestamp": int(datetime.now(UTC).timestamp() * 1000) + 1,
            "chat_id": int(chat),
            "user": {"user_id": actor},
            **extra,
        }
        response = await self.client.post(
            "/max/webhook", json=payload, headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}
        )
        assert response.status_code == 200, response.text
        return response

    async def bind(
        self, *, chat: str = "-501", house: str = "h1", actor: str = "admin", connector: int = 501
    ) -> Any:
        self.fake.configure(chat, connector=str(connector))
        initiated = await self.client.post(
            f"/api/v1/houses/{self.ids[house]}/chat-connections",
            json={},
            headers=self.headers[actor],
        )
        assert initiated.status_code == 201, initiated.text
        request = initiated.json()
        await self.webhook(
            "bot_started", chat="501", actor=connector, payload=request["correlation_token"]
        )
        await self.webhook("bot_added", chat=chat, actor=connector, is_channel=False)
        approved = await self.client.post(
            f"/api/v1/chat-connections/{request['id']}/approve",
            json={"confirm": True},
            headers=self.headers[actor],
        )
        assert approved.status_code == 200, approved.text
        # Подключение оставляет задачу проверки; явный путь начинается с чистой очереди.
        await self.drain()
        return approved.json()

    #: MAX-идентификаторы стенда: admin 501, resident 502, neighbour 503,
    #: outsider 504 (житель другого дома). По умолчанию пишет `resident`.
    async def report(
        self, text: str, *, chat: str = "-501", actor: int = 502, mid: str = "m1"
    ) -> Any:
        return await self.webhook(
            "message_created",
            chat,
            actor,
            message={
                "sender": {"user_id": actor, "is_bot": False},
                "recipient": {"chat_id": int(chat), "chat_type": "chat"},
                "body": {"mid": mid, "text": text},
            },
        )

    def runner(self, pool: WorkerPool = "operational", **kwargs: Any) -> WorkerRunner:
        return WorkerRunner(
            session_factory=self.container.session_factory,
            handlers=self.container.worker_handlers.mapping,
            notifications=self.container.notifications,
            pool=pool,
            **kwargs,
        )

    async def drain(
        self,
        pool: WorkerPool = "operational",
        *,
        rounds: int = 25,
        now: datetime | None = None,
    ) -> None:
        runner = self.runner(pool)
        for _ in range(rounds):
            if not await runner.run_once(now=now):
                break

    async def drain_all(self, *, rounds: int = 25, now: datetime | None = None) -> None:
        """Оба пула по очереди, как в рабочей установке с двумя процессами."""
        for _ in range(rounds):
            worked = await self.runner("ai").run_once(now=now)
            worked = await self.runner("operational").run_once(now=now) or worked
            if not worked:
                break

    async def scalar(self, statement: Any) -> Any:
        async with self.container.session_factory() as session:
            return await session.scalar(statement)

    async def all(self, statement: Any) -> list[Any]:
        async with self.container.session_factory() as session:
            return list(await session.scalars(statement))


@pytest_asyncio.fixture
async def ex(integration_settings: Any) -> Any:
    settings = integration_settings.model_copy(
        update={
            "max_transport": "webhook",
            "max_bot_token": "synthetic-initdata-token",
            "max_webhook_secret": WEBHOOK_SECRET,
            "max_bot_username": "synthetic_bot",
        }
    )
    app = create_app(settings)
    container = app.state.container
    fake = FakeMaxChatProvider()
    container.chat_connections.provider = fake  # explicit test-only injection
    messaging = RecordingMaxMessagingProvider()
    container.notifications.provider = messaging  # explicit test-only injection
    names = ["tenant", "h1", "mh1", "admin", "resident", "neighbour", "outsider"]
    ids: dict[str, Any] = {name: uuid4() for name in names}
    async with container.session_factory() as session, session.begin():
        session.add(ManagementCompany(id=ids["tenant"], name="Явный путь УК"))
        session.add(House(id=ids["h1"], name="h1", address="Казань, Синтетическая улица, 1"))
        for index, name in enumerate(["admin", "resident", "neighbour", "outsider"], 501):
            session.add(
                User(
                    id=ids[name],
                    display_name=name,
                    demo_alias=f"ex-{name}",
                    max_user_id=str(index),
                    max_identity_verified_at=datetime.now(UTC),
                )
            )
        await session.flush()
        session.add(
            HouseManagement(
                id=ids["mh1"],
                house_id=ids["h1"],
                tenant_id=ids["tenant"],
                valid_from=datetime.now(UTC) - timedelta(days=1),
                ticket_intake_enabled=True,
            )
        )
        session.add(
            HouseRoutingProfile(
                house_id=ids["h1"],
                region_code="RU-TA",
                municipality_code="kazan",
                territory_policy="uk",
            )
        )
        for name in ("resident", "neighbour"):
            session.add(ResidentMembership(user_id=ids[name], house_id=ids["h1"]))
        session.add(
            OrganizationMembership(
                user_id=ids["admin"], tenant_id=ids["tenant"], role="company_admin"
            )
        )
    headers: dict[str, dict[str, str]] = {}
    for name in ["admin", "resident", "neighbour", "outsider"]:
        async with container.session_factory() as session:
            auth = await container.session_service.issue_test_session(session, alias=f"ex-{name}")
        headers[name] = {"Authorization": "Bearer " + auth.access_token}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield ExplicitHarness(client, container, fake, messaging, ids, headers)
    await container.aclose()


async def disable_ticket_intake(harness: ExplicitHarness) -> None:
    """Дом без приёма заявок: карточка обязана показать причину, а не молчать."""
    async with harness.container.session_factory() as session, session.begin():
        await session.execute(
            update(HouseManagement)
            .where(HouseManagement.id == harness.ids["mh1"])
            .values(ticket_intake_enabled=False)
        )
