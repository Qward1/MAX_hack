"""Explicit local browser fixture. Never run or imported in production."""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.db.models import (
    ConnectionRequest,
    EmployeeCredential,
    House,
    HouseManagement,
    ResidentMembership,
    User,
)
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools.seed_tickets import seed_id
from tests.fakes.max_chat import FakeMaxChatProvider


async def main():
    settings = get_settings()
    if settings.app_env != AppEnvironment.TEST or os.getenv("B09_BROWSER_FIXTURES") != "1":
        raise RuntimeError("Isolated B09 browser fixture opt-in required")
    container = build_container(settings)
    service = EmployeeAuthService(settings)
    try:
        async with container.session_factory() as db, db.begin():
            if sys.argv[1] == "platform":
                user = await db.get(User, seed_id("b09-platform"))
                if user is None:
                    user = User(
                        id=seed_id("b09-platform"),
                        display_name="B09 Platform",
                        platform_role="superadmin",
                    )
                    db.add(user)
                    await db.flush()
                credential = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.user_id == user.id)
                )
                if credential:
                    await service.provision(db, user.id, "reset-mfa")
                password = await service.provision(
                    db, user.id, "reset-password" if credential else "create", "b09.platform"
                )
                print(json.dumps({"password": password}))
            elif sys.argv[1] == "connect":
                provider = FakeMaxChatProvider()
                chat_id = f"b09-{os.environ['ND_RUN_ID']}"
                provider.configure(chat_id, connector=chat_id)
                container.chat_connections.provider = provider
                request = await container.chat_connections.claim(
                    db, token=sys.argv[2], connector=chat_id, occurred_at=datetime.now(UTC)
                )
                assert request is not None
                await container.chat_connections.bot_added(
                    db,
                    chat_id=chat_id,
                    actor=chat_id,
                    occurred_at=datetime.now(UTC),
                    is_channel=False,
                )
                await db.flush()
                await container.chat_connections.verify(db, request.id)
                print(json.dumps({"status": request.status}))
            elif sys.argv[1] == "approve":
                # Стенд браузера без MAX: подтверждение с тем же двойником MAX, что у "connect".
                chat_id = f"b09-{os.environ['ND_RUN_ID']}"
                provider = FakeMaxChatProvider()
                provider.configure(chat_id, connector=chat_id)
                container.chat_connections.provider = provider
                credential = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.login_name == sys.argv[2])
                )
                request = await db.scalar(
                    select(ConnectionRequest)
                    .where(ConnectionRequest.candidate_max_chat_id == chat_id)
                    .order_by(ConnectionRequest.created_at.desc())
                )
                assert credential is not None and request is not None
                binding = await container.chat_connections.approve(
                    db, request_id=request.id, actor_id=credential.user_id
                )
                print(json.dumps({"binding": str(binding.id), "status": binding.status}))
            elif sys.argv[1] == "resident":
                house = await db.scalar(select(House).where(House.address == sys.argv[2]))
                assert house is not None and house.address.startswith("B09 новый дом")
                db.add(
                    ResidentMembership(
                        user_id=seed_id("resident"), house_id=house.id, source="b09_browser_fixture"
                    )
                )
                print(json.dumps({"house_id": str(house.id)}))
            elif sys.argv[1] == "metadata":
                credential = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.login_name == sys.argv[2])
                )
                rows = await db.scalars(
                    select(HouseManagement).where(HouseManagement.basis_type == "approved_request")
                )
                print(
                    json.dumps(
                        {
                            "user_id": str(credential.user_id),
                            "managements": [str(m.id) for m in rows],
                        }
                    )
                )
            else:
                raise ValueError("Unknown fixture command")
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
