"""Стенд пассивного чтения: два дома двух УК, у каждого свой подключённый чат.

Данные синтетические. Время реплик задаётся явно (метка обновления MAX в
миллисекундах), поэтому окна закрываются детерминированно: привязка после
подключения «активирована» заранее, чтобы реплики из прошлого её не опережали.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from domsignal.db.models import (
    ChatBinding,
    House,
    HouseManagement,
    HouseRoutingProfile,
    Job,
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

MEMO_LEAD = "ДомСигнал: в чате написали о признаках опасности."
NOTICE_LEAD = "ДомСигнал подключён к этому чату"

#: Чаты стенда и MAX-идентификаторы подключающих администраторов.
CHAT_1, CHAT_2 = "-701", "-702"
ADMIN_1, ADMIN_2 = 701, 702
#: Участники чата — не пользователи ДомСигнала: им это и не нужно.
NEIGHBOURS = (711, 712, 713, 714, 715, 716, 717)
#: Житель дома h1, у которого есть учётная запись: для явного `/report`.
RESIDENT = 721


def ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


@dataclass
class PassiveHarness:
    client: AsyncClient
    container: Any
    fake: FakeMaxChatProvider
    messaging: RecordingMaxMessagingProvider
    ids: dict[str, Any]
    headers: dict[str, dict[str, str]]
    counter: int = 0

    async def webhook(self, payload: dict[str, Any]) -> Any:
        response = await self.client.post(
            "/max/webhook", json=payload, headers={"X-Max-Bot-Api-Secret": WEBHOOK_SECRET}
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def lifecycle(self, kind: str, *, chat: str, actor: int, **extra: Any) -> Any:
        return await self.webhook(
            {
                "update_type": kind,
                "timestamp": ms(datetime.now(UTC)) + 1,
                "chat_id": int(chat),
                "user": {"user_id": actor},
                **extra,
            }
        )

    async def bind(
        self, *, chat: str = CHAT_1, house: str = "h1", admin: str = "admin1", enable: bool = True
    ) -> UUID:
        connector = ADMIN_1 if admin == "admin1" else ADMIN_2
        self.fake.configure(chat, connector=str(connector))
        initiated = await self.client.post(
            f"/api/v1/houses/{self.ids[house]}/chat-connections",
            json={},
            headers=self.headers[admin],
        )
        assert initiated.status_code == 201, initiated.text
        request = initiated.json()
        await self.lifecycle(
            "bot_started", chat=str(connector), actor=connector,
            payload=request["correlation_token"],
        )
        await self.lifecycle("bot_added", chat=chat, actor=connector, is_channel=False)
        approved = await self.client.post(
            f"/api/v1/chat-connections/{request['id']}/approve",
            json={"confirm": True},
            headers=self.headers[admin],
        )
        assert approved.status_code == 200, approved.text
        binding_id = UUID(approved.json()["id"])
        # Реплики стенда датированы прошлым: привязка «активна» с запасом.
        async with self.container.session_factory() as session, session.begin():
            await session.execute(
                update(ChatBinding)
                .where(ChatBinding.id == binding_id)
                .values(activated_at=datetime.now(UTC) - timedelta(hours=3))
            )
        await self.drain()
        if enable:
            await self.set_capture(binding_id, admin=admin, enabled=True)
        return binding_id

    async def set_capture(self, binding_id: UUID, *, admin: str = "admin1", enabled: bool) -> Any:
        async with self.container.session_factory() as session, session.begin():
            return await self.container.passive.set_capture(
                session, binding_id=binding_id, actor_id=self.ids[admin], enabled=enabled
            )

    async def say(
        self,
        text: str | None,
        *,
        chat: str = CHAT_1,
        actor: int = NEIGHBOURS[0],
        at: datetime | None = None,
        mid: str | None = None,
        reply_to: str | None = None,
        is_bot: bool = False,
        chat_type: str = "chat",
    ) -> str:
        """Реплика в чат от имени участника. Возвращает её `mid`."""
        self.counter += 1
        mid = mid or f"mid.p4-{self.counter:04d}"
        body: dict[str, Any] = {"mid": mid}
        if text is not None:
            body["text"] = text
        message: dict[str, Any] = {
            "sender": {"user_id": actor, "is_bot": is_bot},
            "recipient": {"chat_id": int(chat), "chat_type": chat_type},
            "body": body,
        }
        if reply_to:
            message["link"] = {"type": "reply", "message": {"mid": reply_to}}
        await self.webhook(
            {
                "update_type": "message_created",
                "timestamp": ms(at or datetime.now(UTC)),
                "message": message,
            }
        )
        return mid

    def runner(self, pool: WorkerPool = "operational", **kwargs: Any) -> WorkerRunner:
        return WorkerRunner(
            session_factory=self.container.session_factory,
            handlers=self.container.worker_handlers.mapping,
            notifications=self.container.notifications,
            pool=pool,
            **kwargs,
        )

    async def drain(
        self, pool: WorkerPool = "operational", *, rounds: int = 40, now: datetime | None = None
    ) -> None:
        runner = self.runner(pool)
        for _ in range(rounds):
            if not await runner.run_once(now=now):
                break

    async def drain_all(self, *, rounds: int = 40, now: datetime | None = None) -> None:
        """Оба пула по очереди, как в рабочей установке с двумя процессами."""
        for _ in range(rounds):
            worked = await self.runner("ai").run_once(now=now)
            worked = await self.runner("operational").run_once(now=now) or worked
            if not worked:
                break

    async def deliver(self, *, rounds: int = 6) -> None:
        """Операционный пул с продвижением часов: MAX допускает не больше
        двух сообщений в секунду в один чат, и шлюз адресата честно ждёт."""
        for step in range(rounds):
            await self.drain("operational", now=datetime.now(UTC) + timedelta(seconds=step))

    def configure(self, **changes: Any) -> None:
        """Поменять параметры пассивного чтения на лету (политика окна — ядра)."""
        config = self.container.signals.config
        policy = changes.pop("policy", {})
        self.container.signals.config = replace(
            config, policy=replace(config.policy, **policy), **changes
        )

    def memos(self) -> list[tuple[str, str, Any]]:
        return [item for item in self.messaging.chat_sent if item[2].text.startswith(MEMO_LEAD)]

    def notices(self) -> list[tuple[str, str, Any]]:
        return [item for item in self.messaging.chat_sent if item[2].text.startswith(NOTICE_LEAD)]

    async def scalar(self, statement: Any) -> Any:
        async with self.container.session_factory() as session:
            return await session.scalar(statement)

    async def all(self, statement: Any) -> list[Any]:
        async with self.container.session_factory() as session:
            return list(await session.scalars(statement))

    async def jobs(self, kind: str) -> list[Job]:
        return await self.all(select(Job).where(Job.kind == kind).order_by(Job.created_at))


def passive_settings(integration_settings: Any, **overrides: Any) -> Any:
    return integration_settings.model_copy(
        update={
            "max_transport": "webhook",
            "max_bot_token": "synthetic-initdata-token",
            "max_webhook_secret": WEBHOOK_SECRET,
            "max_bot_username": "synthetic_bot",
            "passive_capture_enabled": True,
            "passive_window_silence_seconds": 20,
            **overrides,
        }
    )


async def build_harness(settings: Any) -> tuple[PassiveHarness, Any]:
    app = create_app(settings)
    container = app.state.container
    fake = FakeMaxChatProvider()
    container.chat_connections.provider = fake  # explicit test-only injection
    messaging = RecordingMaxMessagingProvider()
    container.notifications.provider = messaging  # explicit test-only injection
    names = ["t1", "t2", "h1", "h2", "mh1", "mh2", "admin1", "admin2", "resident"]
    ids: dict[str, Any] = {name: uuid4() for name in names}
    async with container.session_factory() as session, session.begin():
        session.add(ManagementCompany(id=ids["t1"], name="УК Первая (тест)"))
        session.add(ManagementCompany(id=ids["t2"], name="УК Вторая (тест)"))
        session.add(House(id=ids["h1"], name="h1", address="Казань, Синтетическая улица, 1"))
        session.add(House(id=ids["h2"], name="h2", address="Казань, Синтетическая улица, 2"))
        for name, max_id in (("admin1", ADMIN_1), ("admin2", ADMIN_2), ("resident", RESIDENT)):
            session.add(
                User(
                    id=ids[name],
                    display_name=name,
                    demo_alias=f"p4-{name}",
                    max_user_id=str(max_id),
                    max_identity_verified_at=datetime.now(UTC),
                )
            )
        await session.flush()
        for house, management, tenant in (("h1", "mh1", "t1"), ("h2", "mh2", "t2")):
            session.add(
                HouseManagement(
                    id=ids[management],
                    house_id=ids[house],
                    tenant_id=ids[tenant],
                    valid_from=datetime.now(UTC) - timedelta(days=1),
                    ticket_intake_enabled=True,
                )
            )
            session.add(
                HouseRoutingProfile(
                    house_id=ids[house],
                    region_code="RU-TA",
                    municipality_code="kazan",
                    territory_policy="uk",
                )
            )
        session.add(ResidentMembership(user_id=ids["resident"], house_id=ids["h1"]))
        session.add(
            OrganizationMembership(user_id=ids["admin1"], tenant_id=ids["t1"], role="company_admin")
        )
        session.add(
            OrganizationMembership(user_id=ids["admin2"], tenant_id=ids["t2"], role="company_admin")
        )
    headers: dict[str, dict[str, str]] = {}
    for name in ("admin1", "admin2", "resident"):
        async with container.session_factory() as session:
            auth = await container.session_service.issue_test_session(session, alias=f"p4-{name}")
        headers[name] = {"Authorization": "Bearer " + auth.access_token}
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return PassiveHarness(client, container, fake, messaging, ids, headers), app


@pytest_asyncio.fixture
async def pv(integration_settings: Any) -> Any:
    harness, _ = await build_harness(passive_settings(integration_settings))
    try:
        yield harness
    finally:
        await harness.client.aclose()
        await harness.container.aclose()
