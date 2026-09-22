"""Explicit local browser fixture for the P5 signal inbox; never an application endpoint.

Requires APP_ENV=test and B14_BROWSER_FIXTURES=1 with a dedicated DATABASE_URL.
Signals are seeded through the real P4 path: MAX webhook events go through
`parse_update` + `MaxWebhookService.accept` (capture → window → danger rules),
then the operational pool closes the window by silence and the rules analyzer
writes signals. No direct INSERT into `signals`. Synthetic chat and texts only;
no real MAX calls, no truncation, no shared demo reset.

Commands: `prepare` (idempotent house, operator and connected chat; closes the
fixture house's leftover open signals so each run starts clean), `thread`,
`gas`, `light`, `playground` — each prints the created signal id.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from domsignal.bootstrap import build_container
from domsignal.bot.max_updates import parse_update
from domsignal.contracts.chat_connections import ConnectionCreate
from domsignal.core.chat_connections import TERMINAL
from domsignal.db.models import (
    ChatBinding,
    ConnectionRequest,
    House,
    HouseAssignment,
    HouseManagement,
    HouseRoutingProfile,
    ManagementCompany,
    OrganizationMembership,
    Signal,
    User,
)
from domsignal.settings import AppEnvironment, LlmProvider, get_settings
from domsignal.tools.seed_tickets import seed_id
from domsignal.worker.runner import WorkerRunner

# CLI запускается файлом, а не модулем: корень репозитория нужен для test doubles.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.fakes.max_chat import FakeMaxChatProvider  # noqa: E402

CHAT = "-5505"
CONNECTOR = 5505
#: Участники синтетического чата — не пользователи ДомСигнала.
NEIGHBOURS = (5511, 5512, 5513, 5514, 5515, 5516, 5517)
THREAD = (
    "Лифт во втором подъезде опять не работает",
    "Да, лифт стоит с утра",
    "Подтверждаю, лифт во 2 подъезде не едет",
    "С коляской невозможно подняться, лифт стоит",
    "Тоже пешком шла, лифт не работает",
    "Лифт до сих пор не работает, поднимаюсь пешком",
    "Лифт во втором подъезде так и не работает",
)


def ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


class Stand:
    def __init__(self) -> None:
        settings = get_settings()
        if settings.app_env != AppEnvironment.TEST or os.getenv("B14_BROWSER_FIXTURES") != "1":
            raise RuntimeError("Explicit isolated browser fixture opt-in is required")
        # Приём и разбор — правилами: сторож и AI-пул стенда здесь не нужны.
        self.settings = settings.model_copy(
            update={
                "passive_capture_enabled": True,
                "llm_provider": LlmProvider.RULES,
                "passive_window_silence_seconds": 20,
                # Повторные прогоны за сутки не должны упираться в лимит слабых
                # сигналов дома: иначе новые уходят в Audit Pool (так и задумано).
                "passive_weak_daily_limit": 1000,
            }
        )
        self.container = build_container(self.settings)
        provider = FakeMaxChatProvider()
        provider.configure(CHAT, connector=str(CONNECTOR))
        self.container.chat_connections.provider = provider  # explicit test-only injection
        self.run = str(int(time.time() * 1000))
        self.counter = 0

    async def close(self) -> None:
        await self.container.aclose()

    # ------------------------------------------------------------------ дом

    async def prepare(self) -> dict[str, str]:
        house, management = seed_id("p5-house"), seed_id("p5-management")
        async with self.container.session_factory() as db, db.begin():
            await db.execute(
                insert(ManagementCompany)
                .values(id=seed_id("p5-company"), name="P5 synthetic УК", is_demo=True)
                .on_conflict_do_nothing(index_elements=[ManagementCompany.id])
            )
            for name, alias in (("p5-admin", "p5-admin"), ("p5-operator", "p5-operator")):
                await db.execute(
                    insert(User)
                    .values(
                        id=seed_id(name),
                        display_name="Оператор П5" if name == "p5-operator" else "Админ П5",
                        demo_alias=alias,
                        max_user_id=f"p5-synthetic-{name}",
                    )
                    .on_conflict_do_nothing(index_elements=[User.id])
                )
            await db.execute(
                insert(House)
                .values(
                    id=house,
                    name="P5 house",
                    address="P5 синтетический дом, Казань, 1",
                    is_demo=True,
                )
                .on_conflict_do_nothing(index_elements=[House.id])
            )
            await db.execute(
                insert(HouseManagement)
                .values(
                    id=management,
                    house_id=house,
                    tenant_id=seed_id("p5-company"),
                    valid_from=datetime(2026, 1, 1, tzinfo=UTC),
                    basis_type="synthetic_demo",
                    is_demo=True,
                    ticket_intake_enabled=True,
                )
                .on_conflict_do_nothing(index_elements=[HouseManagement.id])
            )
            await db.execute(
                insert(HouseRoutingProfile)
                .values(
                    house_id=house,
                    region_code="RU-TA",
                    municipality_code="kazan",
                    territory_policy="unknown",
                )
                .on_conflict_do_nothing(index_elements=[HouseRoutingProfile.house_id])
            )
            for name, role in (("p5-admin", "company_admin"), ("p5-operator", "operator")):
                await db.execute(
                    insert(OrganizationMembership)
                    .values(
                        id=seed_id(f"org-{name}"),
                        user_id=seed_id(name),
                        tenant_id=seed_id("p5-company"),
                        role=role,
                        status="active",
                    )
                    .on_conflict_do_nothing(index_elements=[OrganizationMembership.id])
                )
            await db.execute(
                insert(HouseAssignment)
                .values(
                    id=seed_id("p5-operator-assignment"),
                    user_id=seed_id("p5-operator"),
                    management_id=management,
                    role="operator",
                )
                .on_conflict_do_nothing(index_elements=[HouseAssignment.id])
            )
        binding = await self.binding(house)
        # Каждый прогон начинается с пустой очереди дома стенда: незакрытые
        # сигналы прошлых прогонов закрываются как «не относится к дому».
        async with self.container.session_factory() as db, db.begin():
            await db.execute(
                update(Signal)
                .where(Signal.house_id == house, Signal.status.in_(("new", "in_review")))
                .values(
                    status="dismissed",
                    decided_at=datetime.now(UTC),
                    decision_reason="out_of_scope",
                    decision_note="P5 browser fixture cleanup",
                    version=Signal.version + 1,
                )
            )
        return {"house_id": str(house), "binding_id": str(binding)}

    async def binding(self, house: UUID) -> UUID:
        connections = self.container.chat_connections
        async with self.container.session_factory() as db:
            existing = await db.scalar(
                select(ChatBinding).where(
                    ChatBinding.house_id == house, ChatBinding.status == "active"
                )
            )
        if existing is None:
            # Незавершённое подключение прошлого прогона отменяется: новый
            # ключ подключения выдаётся только при создании запроса.
            async with self.container.session_factory() as db:
                stale = list(
                    await db.scalars(
                        select(ConnectionRequest.id).where(
                            ConnectionRequest.house_id == house,
                            ConnectionRequest.status.not_in(TERMINAL),
                        )
                    )
                )
            for request_id in stale:
                async with self.container.session_factory() as db, db.begin():
                    await connections.finish(
                        db, request_id=request_id, actor_id=seed_id("p5-admin"), target="cancelled"
                    )
            async with self.container.session_factory() as db, db.begin():
                request, token = await connections.initiate(
                    db, actor_id=seed_id("p5-admin"), house_id=house, scope=ConnectionCreate()
                )
                assert token is not None
                request_id = request.id
            async with self.container.session_factory() as db, db.begin():
                await connections.claim(
                    db, token=token, connector=str(CONNECTOR), occurred_at=datetime.now(UTC)
                )
            async with self.container.session_factory() as db, db.begin():
                await connections.bot_added(
                    db,
                    chat_id=CHAT,
                    actor=str(CONNECTOR),
                    occurred_at=datetime.now(UTC),
                    is_channel=False,
                )
            async with self.container.session_factory() as db, db.begin():
                existing = await connections.approve(
                    db, request_id=request_id, actor_id=seed_id("p5-admin")
                )
        binding_id = existing.id
        async with self.container.session_factory() as db, db.begin():
            # Реплики стенда датированы прошлым: привязка «активна» с запасом.
            await db.execute(
                update(ChatBinding)
                .where(ChatBinding.id == binding_id)
                .values(activated_at=datetime.now(UTC) - timedelta(days=2))
            )
        async with self.container.session_factory() as db, db.begin():
            await self.container.passive.set_capture(
                db, binding_id=binding_id, actor_id=seed_id("p5-admin"), enabled=True
            )
        return binding_id

    # --------------------------------------------------------------- чат

    async def say(self, text: str, *, actor: int, at: datetime) -> None:
        self.counter += 1
        event = parse_update(
            {
                "update_type": "message_created",
                "timestamp": ms(at),
                "message": {
                    "sender": {"user_id": actor, "is_bot": False},
                    "recipient": {"chat_id": int(CHAT), "chat_type": "chat"},
                    "body": {"mid": f"mid.p5-{self.run}-{self.counter:03d}", "text": text},
                },
            }
        )
        async with self.container.session_factory() as db:
            await self.container.max_webhook.accept(db, event)

    async def settle(self) -> None:
        """Тишина закрывает окно, правила разбирают его — как два пула стенда."""
        for pool in ("operational", "ai", "operational", "ai"):
            runner = WorkerRunner(
                session_factory=self.container.session_factory,
                handlers=self.container.worker_handlers.mapping,
                notifications=self.container.notifications,
                pool=pool,  # type: ignore[arg-type]
            )
            for _ in range(40):
                if not await runner.run_once():
                    break

    async def latest(self, **where: Any) -> str:
        async with self.container.session_factory() as db:
            statement = select(Signal.id).where(Signal.house_id == seed_id("p5-house"))
            for key, value in where.items():
                statement = statement.where(getattr(Signal, key) == value)
            found = await db.scalar(
                statement.where(Signal.status == "new").order_by(Signal.created_at.desc()).limit(1)
            )
        if found is None:
            raise RuntimeError("Signal was not created")
        return str(found)

    async def thread(self) -> str:
        start = datetime.now(UTC) - timedelta(minutes=10)
        for index, text in enumerate(THREAD):
            await self.say(
                text,
                actor=NEIGHBOURS[index % len(NEIGHBOURS)],
                at=start + timedelta(seconds=5 * index),
            )
        await self.settle()
        return await self.latest(subtype="elevator.stopped")

    async def gas(self) -> str:
        # AI-пул стенда остановлен: сигнал предварительный, окно не разбирается.
        await self.say(
            "Пахнет газом в третьем подъезде",
            actor=NEIGHBOURS[0],
            at=datetime.now(UTC) - timedelta(seconds=20),
        )
        return await self.latest(strength="critical")

    async def light(self) -> str:
        await self.say(
            "Не горит свет на лестнице в первом подъезде",
            actor=NEIGHBOURS[1],
            at=datetime.now(UTC) - timedelta(minutes=5),
        )
        await self.settle()
        return await self.latest(subtype="lighting.stairwell")

    async def playground(self) -> str:
        await self.say(
            "Во дворе сломаны качели на детской площадке",
            actor=NEIGHBOURS[2],
            at=datetime.now(UTC) - timedelta(minutes=4),
        )
        await self.settle()
        return await self.latest(subtype="playground.damaged")


async def main() -> None:
    stand = Stand()
    try:
        command = sys.argv[1]
        if command == "prepare":
            result: dict[str, str] = await stand.prepare()
        elif command in {"thread", "gas", "light", "playground"}:
            result = {"signal_id": await getattr(stand, command)()}
        else:
            raise ValueError("Unknown fixture command")
        print(json.dumps(result))
    finally:
        await stand.close()


if __name__ == "__main__":
    asyncio.run(main())
