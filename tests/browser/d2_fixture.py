"""Local D2 browser fixture. Never run or imported in production.

Команды (нужны APP_ENV=test и D2_BROWSER_FIXTURES=1):

* `platform` — суперадмин `d2.platform` с новым временным паролем;
* `totp <login>` — действующий код TOTP сотрудника (для входа второй раз);
* `house <inn> <address>` — дом под управлением УК с этим ИНН (минуя ручную
  проверку платформой, которую уже проверяет B09);
* `reset-rate` — очистить ограничитель попыток входа стенда: все входы идут
  с 127.0.0.1, и длинный сценарий D2 иначе исчерпывает лимит соседних спеков;
* `connect <token> <chat_id> <login>` — шаги MAX и подтверждение подключения
  от имени сотрудника с двойником провайдера MAX: на стенде без MAX настоящий
  провайдер недоступен, а сама проверка квоты — та же, что в API.
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta

import pyotp
from sqlalchemy import delete, select

from domsignal.bootstrap import build_container
from domsignal.db.models import (
    AuthRateLimit,
    EmployeeCredential,
    House,
    HouseManagement,
    ManagementCompany,
    User,
)
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.settings import AppEnvironment, get_settings
from domsignal.tools.seed_tickets import seed_id
from tests.fakes.max_chat import FakeMaxChatProvider


async def main() -> None:
    settings = get_settings()
    if settings.app_env != AppEnvironment.TEST or os.getenv("D2_BROWSER_FIXTURES") != "1":
        raise RuntimeError("Isolated D2 browser fixture opt-in required")
    container = build_container(settings)
    service = EmployeeAuthService(settings)
    try:
        command = sys.argv[1]
        async with container.session_factory() as db, db.begin():
            if command == "platform":
                user = await db.get(User, seed_id("d2-platform"))
                if user is None:
                    user = User(
                        id=seed_id("d2-platform"),
                        display_name="Платформа ДомСигнала",
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
                    db, user.id, "reset-password" if credential else "create", "d2.platform"
                )
                print(json.dumps({"password": password}))
            elif command == "totp":
                credential = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.login_name == sys.argv[2])
                )
                assert credential and credential.encrypted_totp_secret
                secret = service.cipher().decrypt(credential.encrypted_totp_secret.encode())
                step = int(time.time()) // 30
                # Код уже использованного шага второй раз не принимается: берём следующий.
                if credential.last_totp_step is not None and credential.last_totp_step >= step:
                    step = credential.last_totp_step + 1
                code = pyotp.TOTP(secret.decode()).at(datetime.fromtimestamp(step * 30, UTC))
                print(json.dumps({"code": code}))
            elif command == "reset-rate":
                await db.execute(delete(AuthRateLimit))
                print(json.dumps({"reset": True}))
            elif command == "house":
                company = await db.scalar(
                    select(ManagementCompany).where(ManagementCompany.inn == sys.argv[2])
                )
                assert company is not None
                house = House(name=sys.argv[3][:200], address=sys.argv[3])
                db.add(house)
                await db.flush()
                db.add(
                    HouseManagement(
                        house_id=house.id,
                        tenant_id=company.id,
                        valid_from=datetime.now(UTC) - timedelta(days=1),
                        basis_type="d2_browser_fixture",
                        ticket_intake_enabled=True,
                    )
                )
                print(json.dumps({"house_id": str(house.id)}))
            elif command == "connect":
                token, chat_id, login = sys.argv[2], sys.argv[3], sys.argv[4]
                actor = await db.scalar(
                    select(EmployeeCredential.user_id).where(EmployeeCredential.login_name == login)
                )
                assert actor is not None
                provider = FakeMaxChatProvider()
                provider.configure(chat_id, connector=chat_id)
                container.chat_connections.provider = provider
                request = await container.chat_connections.claim(
                    db, token=token, connector=chat_id, occurred_at=datetime.now(UTC)
                )
                # Только свежий запрос: повтор старой команды не должен «подключать» снова.
                assert request is not None and request.status == "connector_claimed", request
                await container.chat_connections.bot_added(
                    db,
                    chat_id=chat_id,
                    actor=chat_id,
                    occurred_at=datetime.now(UTC),
                    is_channel=False,
                )
                await db.flush()
                binding = await container.chat_connections.approve(
                    db, request_id=request.id, actor_id=actor
                )
                print(json.dumps({"status": binding.status}))
            else:
                raise RuntimeError(f"Unknown command {command}")
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
