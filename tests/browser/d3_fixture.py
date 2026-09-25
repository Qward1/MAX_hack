"""Local D3 browser fixture. Never run or imported in production.

Команды (нужны APP_ENV=test и D3_BROWSER_FIXTURES=1):

* `ids` — идентификаторы синтетических УК и домов стенда A-16;
* `binding` — активная привязка домового чата к дому a1 (на стенде нет MAX:
  подключение по API уже проверяют тесты A-07; здесь нужен только чат для
  настроек бота и раздела «Мой дом»);
* `send` — то, что делает воркер: отправка подтверждённых сообщений
  (`broadcast.send`). MAX на стенде выключен, поэтому доставки остаются в
  очереди и статистика честно показывает «ожидает».
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import Broadcast, ChatBinding, ConnectionRequest, MAXChat
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools.seed_tickets import seed_id

CHAT_ID = "-9303"


async def main() -> None:
    settings = get_settings()
    if settings.app_env != AppEnvironment.TEST or os.getenv("D3_BROWSER_FIXTURES") != "1":
        raise RuntimeError("Isolated D3 browser fixture opt-in required")
    container = build_container(settings)
    try:
        command = sys.argv[1]
        if command == "ids":
            print(
                json.dumps(
                    {
                        "company": str(seed_id("alpha")),
                        "house": str(seed_id("a1")),
                        "other_house": str(seed_id("a2")),
                        "foreign_house": str(seed_id("b1")),
                    }
                )
            )
        elif command == "binding":
            async with container.session_factory() as db, db.begin():
                existing = await db.scalar(
                    select(ChatBinding).where(
                        ChatBinding.max_chat_id == CHAT_ID, ChatBinding.status == "active"
                    )
                )
                if existing is None:
                    now = datetime.now(UTC)
                    chat = await db.scalar(select(MAXChat).where(MAXChat.max_chat_id == CHAT_ID))
                    if chat is None:
                        db.add(
                            MAXChat(
                                max_chat_id=CHAT_ID,
                                type="chat",
                                title="Синтетический чат дома a1",
                                bot_present=True,
                                last_seen_at=now,
                                binding_version=1,
                            )
                        )
                        await db.flush()
                    request = ConnectionRequest(
                        id=uuid4(),
                        management_id=seed_id("management-a1"),
                        house_id=seed_id("a1"),
                        initiated_by_user_id=seed_id("admin"),
                        token_hash=uuid4().hex + uuid4().hex,
                        expires_at=now,
                        status="completed",
                        candidate_max_chat_id=CHAT_ID,
                        scope_type="house",
                        completed_at=now,
                    )
                    db.add(request)
                    await db.flush()
                    existing = ChatBinding(
                        id=uuid4(),
                        max_chat_id=CHAT_ID,
                        connection_request_id=request.id,
                        house_id=seed_id("a1"),
                        management_id=seed_id("management-a1"),
                        scope_type="house",
                        status="active",
                        binding_version=1,
                        verified_at=now,
                        activated_at=now,
                    )
                    db.add(existing)
                print(json.dumps({"binding": str(existing.id)}))
        elif command == "send":
            async with container.session_factory() as db:
                scheduled = list(
                    await db.scalars(
                        select(Broadcast.id).where(
                            Broadcast.status == "scheduled",
                            Broadcast.scheduled_at <= datetime.now(UTC),
                        )
                    )
                )
            for broadcast_id in scheduled:
                await container.broadcasts.send_due({"broadcast_id": str(broadcast_id)})
            print(json.dumps({"sent": len(scheduled)}))
        else:
            raise RuntimeError(f"Unknown command {command}")
    finally:
        await container.aclose()


asyncio.run(main())
