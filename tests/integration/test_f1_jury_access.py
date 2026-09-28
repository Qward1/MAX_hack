"""F1 §5.5.3: один проверочный аккаунт на нескольких людях.

Второй вход тем же аккаунтом с другого устройства не выбивает первый; один и
тот же код TOTP второй раз не принимается (защита от повтора) — второму
проверяющему достаточно кода следующего 30-секундного окна.
"""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.test_employee_auth import (  # noqa: F401
    BASE,
    PASSWORD,
    auth,
    finish,
    post,
    state,
)

pytestmark = pytest.mark.integration


async def _second_device(auth) -> dict:  # noqa: F811
    client = AsyncClient(transport=ASGITransport(app=auth["app"]), base_url="https://testserver")
    return {**auth, "client": client}


async def test_parallel_sessions_of_one_account_do_not_evict_each_other(auth) -> None:  # noqa: F811
    await finish(auth)
    assert (await state(auth))["stage"] == "authenticated"
    totp = pyotp.TOTP(auth["secret"])
    other = await _second_device(auth)
    try:
        await state(other)
        login = await post(other, "/login", {"login_name": "employee.one", "password": PASSWORD})
        assert login.json()["stage"] == "mfa_challenge"
        # Тот же код, что уже принят первым устройством, — отказ (повтор).
        replay = await post(other, "/mfa/challenge", {"code": totp.now()})
        assert replay.status_code != 200
        # Тот же вход продолжается кодом следующего окна.
        later = totp.at(datetime.now(UTC) + timedelta(seconds=30))
        accepted = await post(other, "/mfa/challenge", {"code": later})
        assert accepted.status_code == 200, accepted.text
        assert (await state(other))["stage"] == "authenticated"
        # Первое устройство по-прежнему вошло.
        assert (await state(auth))["stage"] == "authenticated"
    finally:
        await other["client"].aclose()


async def test_session_endpoint_is_under_the_auth_prefix() -> None:
    assert BASE == "/api/v1/auth/employee"
