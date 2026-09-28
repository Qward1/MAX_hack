"""F1 §5.5: витрина жюри защищена от случайной поломки проверочными аккаунтами.

Проверочный аккаунт (`users.reviewer`) получает 403 `showcase_protected` на
разрушающих действиях над витриной (УК `showcase`, её дома, другие проверочные
аккаунты). Над чужой не-витриной он работает как обычно; обычный сотрудник и
суперадмин ограничений не получают. Настоящая PostgreSQL и HTTP.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select, update

from domsignal.db.models import HouseManagement, ManagementCompany, User
from domsignal.tools.seed_tickets import seed_id
from tests.integration.test_administration import REGION, env  # noqa: F401

pytestmark = pytest.mark.integration

ALPHA = seed_id("alpha")
A1 = seed_id("a1")


async def _mark(env, *, reviewers=(), showcase=()) -> None:  # noqa: F811
    async with env["container"].session_factory() as db, db.begin():
        if reviewers:
            await db.execute(update(User).where(User.id.in_(reviewers)).values(reviewer=True))
        if showcase:
            await db.execute(
                update(ManagementCompany)
                .where(ManagementCompany.id.in_(showcase))
                .values(showcase=True)
            )


async def _call(client, path, payload):
    return await client.post(path, json=payload, headers={"Idempotency-Key": str(uuid4())})


def _protected(response) -> bool:
    return response.status_code == 403 and response.json().get("code") == "showcase_protected"


async def test_reviewer_platform_cannot_break_the_showcase(env) -> None:  # noqa: F811
    await _mark(env, reviewers=[env["platform_id"]], showcase=[ALPHA])
    platform = env["platform"]
    assert _protected(
        await _call(platform, f"/api/v1/platform/companies/{ALPHA}/suspend", {"reason": "проверка"})
    )
    assert _protected(
        await _call(
            platform,
            f"/api/v1/platform/companies/{ALPHA}/chat-quota",
            {"limit": 0, "reason": "проверка"},
        )
    )
    assert _protected(
        await _call(platform, f"/api/v1/platform/houses/{A1}/open-access/close", {"reason": "тест"})
    )
    assert _protected(
        await _call(
            platform, f"/api/v1/platform/houses/{A1}/region", {**REGION, "reason": "проверка"}
        )
    )
    # Расширить квоту витрине можно — это не поломка.
    raised = await _call(
        platform,
        f"/api/v1/platform/companies/{ALPHA}/chat-quota",
        {"limit": None, "reason": "расширить квоту"},
    )
    assert raised.status_code == 200, raised.text
    # Не-витрину тот же проверочный суперадмин приостанавливает как обычно.
    beta = seed_id("beta")
    suspended = await _call(
        platform, f"/api/v1/platform/companies/{beta}/suspend", {"reason": "своя проверка"}
    )
    assert suspended.status_code == 200, suspended.text
    back = await _call(
        platform, f"/api/v1/platform/companies/{beta}/reactivate", {"reason": "вернуть"}
    )
    assert back.status_code == 200, back.text


async def test_reviewer_admin_cannot_touch_other_reviewers_or_close_access(env) -> None:  # noqa: F811
    admin, operator = seed_id("admin"), seed_id("operator")
    await _mark(env, reviewers=[admin, operator], showcase=[ALPHA])
    client = env["admin"]
    base = f"/api/v1/companies/{ALPHA}"
    async with env["container"].session_factory() as db:
        management = await db.scalar(
            select(HouseManagement.id).where(
                HouseManagement.house_id == A1, HouseManagement.tenant_id == ALPHA
            )
        )
    assert _protected(await _call(client, f"{base}/staff/{operator}/revoke", {}))
    assert _protected(
        await _call(
            client,
            f"{base}/staff/{operator}/assignments",
            {"management_id": str(management), "role": None},
        )
    )
    assert _protected(
        await _call(client, f"{base}/staff/{operator}/credential-reset", {"kind": "password"})
    )
    assert _protected(await _call(client, f"{base}/houses/{A1}/open-access", {"enabled": False}))
    # Включить открытый доступ витрине можно — это не поломка.
    opened = await _call(
        client, f"{base}/houses/{A1}/open-access", {"enabled": True, "confirm": True}
    )
    assert opened.status_code == 200, opened.text


async def test_ordinary_staff_and_platform_keep_full_rights(env) -> None:  # noqa: F811
    await _mark(env, showcase=[ALPHA])
    operator = seed_id("operator")
    revoked = await _call(env["admin"], f"/api/v1/companies/{ALPHA}/staff/{operator}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    suspended = await _call(
        env["platform"], f"/api/v1/platform/companies/{ALPHA}/suspend", {"reason": "штатно"}
    )
    assert suspended.status_code == 200, suspended.text


async def test_showcase_health_needs_its_token_and_returns_only_booleans(env) -> None:  # noqa: F811
    from httpx import ASGITransport, AsyncClient

    from domsignal.main import create_app

    settings = env["settings"].model_copy(update={"showcase_check_token": "check-token-123"})
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver") as c:
        assert (await c.get("/api/v1/showcase/health")).status_code == 404
        wrong = await c.get("/api/v1/showcase/health", headers={"X-Showcase-Check-Token": "x"})
        assert wrong.status_code == 404
        unmarked = await c.get(
            "/api/v1/showcase/health", headers={"X-Showcase-Check-Token": "check-token-123"}
        )
        assert unmarked.json() == {"ok": False, "checks": {"showcase_marked": False}}
        await _mark(env, showcase=[ALPHA])
        marked = (
            await c.get(
                "/api/v1/showcase/health", headers={"X-Showcase-Check-Token": "check-token-123"}
            )
        ).json()
    assert marked["checks"]["company_active"] and marked["checks"]["house_managed"]
    # Чата у синтетической УК нет — проверка честно это говорит.
    assert marked["checks"]["chat_active"] is False and marked["ok"] is False
    assert all(isinstance(value, bool) for value in marked["checks"].values())
    await app.state.container.engine.dispose()
