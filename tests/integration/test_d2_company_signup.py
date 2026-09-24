"""D2: заявка УК со страницей статуса, квота при одобрении и расширение,
сброс пароля/MFA сотрудника, открытая регистрация, единый вход.

Настоящие HTTP и PostgreSQL; стенд и помощники — из A-10/B-09.
"""

import json
from uuid import UUID, uuid4

import pyotp
from sqlalchemy import func, select

from domsignal.db.models import (
    AppSession,
    ChatQuotaGrant,
    ChatQuotaRequest,
    CompanyApplicationMessage,
    EmployeeCredential,
    EmployeeCredentialReset,
    EmployeeInvitation,
    HouseAssignment,
    InboxReceipt,
    ManagementCompany,
    OrganizationMembership,
)
from domsignal.tools.seed_tickets import seed_id
from tests.integration.test_administration import (  # noqa: F401 - фикстура стенда
    APP,
    AUTH,
    PASSWORD,
    STATUS,
    admin_link,
    application,
    auth_post,
    env,
    post,
    register,
)

PLATFORM = "/api/v1/platform"
NEW_PASSWORD = "Fresh employee password after reset 71!"


async def status(env, obj, expected=200):  # noqa: F811
    return await post(env["public"], STATUS, {"token": env["tokens"][obj]}, expected)


async def decide(env, obj, action, body=None, expected=200):  # noqa: F811
    return await post(
        env["platform"],
        f"{PLATFORM}/company-applications/{obj}/{action}",
        {"reason": "Проверено платформой", **(body or {})},
        expected,
    )


async def test_status_page_questions_answer_and_privacy(env):  # noqa: F811
    obj = await application(
        env, {**APP, "house_addresses": ["Казань, ул. Баумана, 1", "Казань, ул. Пушкина, 5"]}
    )
    view = await status(env, obj)
    assert view["status"] == "submitted" and view["requested_chat_count"] == 2
    assert view["house_addresses"] == ["Казань, ул. Баумана, 1", "Казань, ул. Пушкина, 5"]
    assert view["admin_account"] == "unavailable" and not view["can_reply"]
    # Чужой или выдуманный токен ничего не раскрывает.
    await post(env["public"], STATUS, {"token": "x" * 43}, 404)
    await post(env["public"], STATUS, {"token": "short"}, 422)
    await post(
        env["public"], STATUS + "/reply", {"token": env["tokens"][obj], "text": "Ответ"}, 409
    )
    await decide(env, obj, "request-info", {"reason": "Пришлите номер договора управления"})
    view = await status(env, obj)
    assert view["status"] == "needs_info" and view["can_reply"]
    assert [m["author"] for m in view["messages"]] == ["platform"]
    assert view["messages"][0]["text"] == "Пришлите номер договора управления"
    answered = await post(
        env["public"],
        STATUS + "/reply",
        {"token": env["tokens"][obj], "text": "Договор № 12 от 01.02.2026"},
    )
    assert answered["status"] == "under_review" and not answered["can_reply"]
    assert [m["author"] for m in answered["messages"]] == ["platform", "applicant"]
    await post(
        env["public"], STATUS + "/reply", {"token": env["tokens"][obj], "text": "<b>x</b>"}, 422
    )
    detail = (await env["platform"].get(f"{PLATFORM}/company-applications/{obj}")).json()
    assert [m["text"] for m in detail["messages"]][-1] == "Договор № 12 от 01.02.2026"
    assert any(
        h["event"] == "administration.company_application.answered" for h in detail["history"]
    )
    # Ссылка статуса не выдаёт кабинет, а платформа не видит секрет.
    assert (await env["public"].get("/api/v1/admin/bootstrap")).status_code == 401
    async with env["container"].session_factory() as db:
        dump = json.dumps((await db.scalars(select(InboxReceipt.payload))).all())
        assert env["tokens"][obj] not in dump


async def test_approval_with_smaller_quota_and_self_service_admin(env):  # noqa: F811
    obj = await application(env)
    approved = await decide(
        env, obj, "approve", {"chat_quota": 1, "reason": "Пилот на один чат, расширим по запросу"}
    )
    assert approved["invitation"] is None
    assert approved["application"]["granted_chat_quota"] == 1
    company = approved["application"]["company_id"]
    view = await status(env, obj)
    assert view["status"] == "approved" and view["granted_chat_quota"] == 1
    assert not view["quota_unlimited"] and view["admin_account"] == "create"
    assert view["decision_reason"] == "Пилот на один чат, расширим по запросу"
    link = await admin_link(env, obj)
    admin, _ = await register(env, link, login="d2.first.admin")
    boot = (await admin.get("/api/v1/admin/bootstrap")).json()
    assert [c["company_id"] for c in boot["companies"]] == [company]
    assert (await status(env, obj))["admin_account"] == "active"
    await admin_link(env, obj, 409)
    quota = (await admin.get(f"/api/v1/companies/{company}/chat-quota")).json()
    assert quota["quota"]["limit"] == 1 and quota["quota"]["remaining"] == 1
    assert quota["grants"][0]["kind"] == "initial"
    destinations = (await admin.get(AUTH + "/destinations")).json()
    assert destinations == {
        "platform": False,
        "companies": [{"company_id": company, "name": APP["short_name"], "role": "company_admin"}],
    }


async def test_unlimited_and_default_quota_on_approval(env):  # noqa: F811
    unlimited = await application(env)
    result = await decide(env, unlimited, "approve", {"unlimited": True})
    assert (await status(env, unlimited))["quota_unlimited"]
    assert result["application"]["granted_chat_quota"] is None
    default = await application(env, {**APP, "inn": "7700000011", "requested_chat_count": 3})
    await decide(env, default, "approve")
    assert (await status(env, default))["granted_chat_quota"] == 3


async def test_rejected_application_has_no_account_button(env):  # noqa: F811
    obj = await application(env)
    await decide(env, obj, "reject", {"reason": "Не удалось подтвердить управление домами"})
    view = await status(env, obj)
    assert view["status"] == "rejected" and view["admin_account"] == "unavailable"
    assert view["decision_reason"] == "Не удалось подтвердить управление домами"
    await admin_link(env, obj, 409)
    async with env["container"].session_factory() as db:
        assert not await db.scalar(select(EmployeeInvitation))


async def test_duplicate_inn_is_flagged_and_second_approval_is_refused(env):  # noqa: F811
    first = await application(env)
    second = await application(env)
    rows = (await env["platform"].get(f"{PLATFORM}/company-applications")).json()
    assert {r["inn_conflict"] for r in rows} == {"open_application"}
    await decide(env, first, "approve")
    await decide(env, second, "approve", expected=409)
    detail = (await env["platform"].get(f"{PLATFORM}/company-applications/{second}")).json()
    assert detail["inn_conflict"] == "company_exists"


async def test_expansion_request_partial_approval_and_permissions(env):  # noqa: F811
    company = str(seed_id("alpha"))
    base = f"/api/v1/companies/{company}/chat-quota"
    # Без ограничения расширять нечего.
    await post(
        env["admin"], base + "/requests", {"requested_delta": 2, "reason": "Новые дома"}, 409
    )
    await post(
        env["platform"],
        f"{PLATFORM}/companies/{company}/chat-quota",
        {"limit": 1, "reason": "Пилот"},
    )
    payload = {"requested_delta": 3, "reason": "Три подъезда дома на Баумана"}
    first = await post(env["admin"], base + "/requests", payload, 201, key="quota-request-key")
    again = await post(env["admin"], base + "/requests", payload, 201, key="quota-request-key")
    assert first["id"] == again["id"] and first["status"] == "pending"
    await post(env["admin"], base + "/requests", payload, 409)
    await post(env["operator"], base + "/requests", payload, 403)
    await post(env["foreign"], base + "/requests", payload, 404)
    assert (await env["operator"].get(base)).status_code == 200  # оператор — только просмотр
    assert (await env["foreign"].get(base)).status_code == 404
    assert (await env["admin"].get(f"{PLATFORM}/chat-quota-requests")).status_code == 403
    pending = (await env["platform"].get(f"{PLATFORM}/chat-quota-requests")).json()
    assert [r["id"] for r in pending] == [first["id"]]
    assert pending[0]["quota"]["limit"] == 1 and pending[0]["company_name"]
    path = f"{PLATFORM}/chat-quota-requests/{first['id']}/decide"
    await post(env["platform"], path, {"granted_delta": 4, "reason": "Больше запрошенного"}, 409)
    decided = await post(env["platform"], path, {"granted_delta": 2, "reason": "Пока два"})
    assert decided["status"] == "partially_approved" and decided["granted_delta"] == 2
    assert decided["quota"]["limit"] == 3
    await post(env["platform"], path, {"granted_delta": 1, "reason": "Повтор"}, 409)
    view = (await env["admin"].get(base)).json()
    assert view["quota"]["limit"] == 3
    assert [g["kind"] for g in view["grants"]] == ["expansion", "adjustment"]
    assert view["requests"][0]["decision_reason"] == "Пока два"
    rejected = await post(
        env["admin"], base + "/requests", {"requested_delta": 1, "reason": "Ещё"}, 201
    )
    result = await post(
        env["platform"],
        f"{PLATFORM}/chat-quota-requests/{rejected['id']}/decide",
        {"granted_delta": 0, "reason": "Сначала подключите выданные"},
    )
    assert result["status"] == "rejected" and result["quota"]["limit"] == 3
    cancelled = await post(
        env["admin"], base + "/requests", {"requested_delta": 1, "reason": "x" * 3}, 201
    )
    await post(env["admin"], base + f"/requests/{cancelled['id']}/cancel")
    async with env["container"].session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ChatQuotaGrant)
                .where(ChatQuotaGrant.company_id == UUID(company))
            )
            == 2
        )
        statuses = sorted((await db.scalars(select(ChatQuotaRequest.status))).all())
        assert statuses == ["cancelled", "partially_approved", "rejected"]


async def test_platform_sets_and_removes_limit_with_history(env):  # noqa: F811
    company = str(seed_id("alpha"))
    path = f"{PLATFORM}/companies/{company}/chat-quota"
    await post(env["admin"], path, {"limit": 5, "reason": "Не платформа"}, 403)
    await post(env["platform"], path, {"limit": -1, "reason": "Отрицательная"}, 422)
    await post(env["platform"], path, {"limit": 5, "reason": "Пять чатов"})
    view = await post(env["platform"], path, {"limit": None, "reason": "Снять ограничение"})
    assert view["quota"]["limit"] is None and view["quota"]["remaining"] is None
    assert [(g["limit_after"], g["delta"]) for g in view["grants"]] == [(None, None), (5, None)]
    listed = (await env["platform"].get(f"{PLATFORM}/companies/{company}")).json()
    assert listed["chat_quota"]["limit"] is None


async def cipher_totp(env, user_id) -> pyotp.TOTP:  # noqa: F811
    async with env["container"].session_factory() as db:
        credential = await db.scalar(
            select(EmployeeCredential).where(EmployeeCredential.user_id == user_id)
        )
    secret = env["auth"].cipher().decrypt(credential.encrypted_totp_secret.encode()).decode()
    return pyotp.TOTP(secret)


async def test_reset_password_and_mfa_by_one_time_link(env):  # noqa: F811
    company, operator = seed_id("alpha"), seed_id("operator")
    base = f"/api/v1/companies/{company}/staff/{operator}/credential-reset"
    await post(env["operator"], base, {"kind": "password"}, 403)
    await post(env["foreign"], base, {"kind": "password"}, 404)
    await post(
        env["admin"],
        f"/api/v1/companies/{company}/staff/{seed_id('admin')}/credential-reset",
        {"kind": "password"},
        409,
    )
    assert (await env["operator"].get("/api/v1/admin/bootstrap")).status_code == 200
    first = await post(env["admin"], base, {"kind": "password_mfa"}, 201)
    # Сессии сотрудника отозваны сразу, прежний вход закрыт.
    assert (await env["operator"].get("/api/v1/admin/bootstrap")).status_code == 401
    second = await post(env["admin"], base, {"kind": "password_mfa"}, 201)
    old_token = first["reset_url"].split("/")[-1]
    token = second["reset_url"].split("/")[-1]
    stranger = await env["client"]()
    await auth_post(stranger, "/credential-reset/preview", {"token": old_token}, 401)
    preview = await auth_post(stranger, "/credential-reset/preview", {"token": token})
    assert preview["kind"] == "password_mfa" and preview["login_name"].startswith("fixture.")
    await auth_post(
        stranger, "/credential-reset/complete", {"token": token, "password": "short"}, 422
    )
    step = await auth_post(
        stranger, "/credential-reset/complete", {"token": token, "password": NEW_PASSWORD}
    )
    assert step["stage"] == "mfa_enroll"
    setup = await auth_post(stranger, "/mfa/enroll")
    await auth_post(stranger, "/mfa/verify", {"code": pyotp.TOTP(setup["secret"]).now()})
    assert (await stranger.get("/api/v1/admin/bootstrap")).status_code == 200
    replay = await env["client"]()
    await auth_post(
        replay, "/credential-reset/complete", {"token": token, "password": NEW_PASSWORD}, 401
    )
    login = await env["client"]()
    step = await auth_post(
        login, "/login", {"login_name": preview["login_name"], "password": NEW_PASSWORD}
    )
    assert step["stage"] == "mfa_challenge"
    async with env["container"].session_factory() as db:
        rows = (await db.scalars(select(EmployeeCredentialReset))).all()
        assert sorted(r.status for r in rows) == ["revoked", "used"]
        assert all(len(r.token_hash) == 64 and r.token_hash not in (token, old_token) for r in rows)
        events = (await db.scalars(select(InboxReceipt.event_type))).all()
        assert "administration.credential_reset.password_mfa" in events
        assert "administration.credential_reset.used" in events
        assert token not in json.dumps((await db.scalars(select(InboxReceipt.payload))).all())


async def test_reset_password_only_keeps_authenticator(env):  # noqa: F811
    company, operator = seed_id("alpha"), seed_id("operator")
    issued = await post(
        env["admin"],
        f"/api/v1/companies/{company}/staff/{operator}/credential-reset",
        {"kind": "password"},
        201,
    )
    totp = await cipher_totp(env, operator)
    c = await env["client"]()
    step = await auth_post(
        c,
        "/credential-reset/complete",
        {"token": issued["reset_url"].split("/")[-1], "password": NEW_PASSWORD},
    )
    assert step["stage"] == "mfa_challenge"
    await auth_post(c, "/mfa/challenge", {"code": totp.now()})
    assert (await c.get("/api/v1/admin/bootstrap")).status_code == 200


async def test_reset_refused_for_employee_of_two_companies(env):  # noqa: F811
    async with env["container"].session_factory() as db, db.begin():
        db.add(
            OrganizationMembership(
                user_id=seed_id("operator"), tenant_id=seed_id("beta"), role="operator"
            )
        )
    await post(
        env["admin"],
        f"/api/v1/companies/{seed_id('alpha')}/staff/{seed_id('operator')}/credential-reset",
        {"kind": "password"},
        409,
    )


async def join(env, code, login, finish=True):  # noqa: F811
    c = await env["client"]()
    step = await auth_post(
        c,
        "/join/register",
        {
            "code": code,
            "display_name": "Оператор по ссылке",
            "login_name": login,
            "password": PASSWORD,
        },
    )
    assert step["stage"] == "mfa_enroll"
    setup = await auth_post(c, "/mfa/enroll")
    if finish:
        await auth_post(c, "/mfa/verify", {"code": pyotp.TOTP(setup["secret"]).now()})
    return c, setup["secret"]


async def test_open_registration_lifecycle(env):  # noqa: F811
    company = seed_id("alpha")
    path = f"{PLATFORM}/companies/{company}/open-registration"
    await post(env["admin"], path, {"enabled": True, "reason": "Не платформа"}, 403)
    assert (await env["platform"].get(path)).json()["enabled"] is False
    enabled = await post(env["platform"], path, {"enabled": True, "reason": "Проверка кабинета"})
    code = enabled["join_url"].split("/")[-1]
    assert enabled["enabled"] and "/join/" in enabled["join_url"]
    c = await env["client"]()
    assert (await auth_post(c, "/join/preview", {"code": code}))[
        "company_name"
    ] == "A16 synthetic alpha"
    member, _ = await join(env, code, "d2.joined.operator")
    boot = (await member.get("/api/v1/admin/bootstrap")).json()
    assert boot["companies"][0]["company_id"] == str(company)
    assert boot["companies"][0]["surfaces"] == ["tickets", "signals", "assigned_houses", "overview"]
    async with env["container"].session_factory() as db:
        user = await db.scalar(
            select(EmployeeCredential.user_id).where(
                EmployeeCredential.login_name == "d2.joined.operator"
            )
        )
        roles = (
            await db.execute(
                select(HouseAssignment.management_id, HouseAssignment.role).where(
                    HouseAssignment.user_id == user, HouseAssignment.status == "active"
                )
            )
        ).all()
        assert sorted(str(m) for m, _ in roles) == sorted(
            str(seed_id(f"management-{h}")) for h in ("a1", "a2")
        )
        assert {r for _, r in roles} == {"operator"}
    staff = (await env["admin"].get(f"/api/v1/companies/{company}/staff")).json()
    assert [p["open_registration"] for p in staff if p["user_id"] == str(user)] == [True]
    listed = (await env["platform"].get(path)).json()
    assert [e["login_name"] for e in listed["employees"]] == ["d2.joined.operator"]
    # Незавершённая регистрация закрывается вместе с ссылкой.
    pending, secret = await join(env, code, "d2.unfinished", finish=False)
    closed = await post(env["platform"], path, {"enabled": False, "reason": "Проверка закончена"})
    assert closed["enabled"] is False and closed["join_url"] is None
    response = await pending.post(AUTH + "/mfa/verify", json={"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 401
    await auth_post(await env["client"](), "/join/preview", {"code": code}, 401)
    # Зарегистрированный по ссылке сотрудник остаётся, пока его не отзовут.
    assert (await member.get("/api/v1/admin/bootstrap")).status_code == 200
    reopened = await post(env["platform"], path, {"enabled": True, "reason": "Новая ссылка"})
    assert reopened["join_url"] != enabled["join_url"]
    await auth_post(await env["client"](), "/join/preview", {"code": code}, 401)


async def test_open_registration_refuses_suspended_company_and_taken_login(env):  # noqa: F811
    company = seed_id("alpha")
    enabled = await post(
        env["platform"],
        f"{PLATFORM}/companies/{company}/open-registration",
        {"enabled": True, "reason": "Проверка"},
    )
    code = enabled["join_url"].split("/")[-1]
    await join(env, code, "d2.first.join")
    c = await env["client"]()
    await auth_post(
        c,
        "/join/register",
        {
            "code": code,
            "display_name": "Повтор",
            "login_name": "d2.first.join",
            "password": PASSWORD,
        },
        409,
    )
    async with env["container"].session_factory() as db, db.begin():
        (await db.get(ManagementCompany, company)).status = "suspended"
    await auth_post(await env["client"](), "/join/preview", {"code": code}, 401)


async def test_join_attempts_are_rate_limited(env):  # noqa: F811
    c = await env["client"]()
    state = (await c.get(AUTH + "/session")).json()
    c.headers.update({"Origin": "https://testserver", "X-CSRF-Token": state["csrf_token"]})
    code = "unknown-join-code-" + uuid4().hex
    statuses = [
        (await c.post(AUTH + "/join/preview", json={"code": code})).status_code for _ in range(101)
    ]
    assert statuses[0] == 401 and statuses[-1] == 429


async def test_destinations_for_platform_and_public(env):  # noqa: F811
    platform = (await env["platform"].get(AUTH + "/destinations")).json()
    assert platform == {"platform": True, "companies": []}
    assert (await env["public"].get(AUTH + "/destinations")).status_code == 401


async def test_messages_are_stored_without_markup(env):  # noqa: F811
    obj = await application(env)
    await decide(env, obj, "request-info", {"reason": "Уточните адреса"})
    async with env["container"].session_factory() as db:
        rows = (await db.scalars(select(CompanyApplicationMessage))).all()
        assert [(r.author, r.text) for r in rows] == [("platform", "Уточните адреса")]
        assert not await db.scalar(select(AppSession).where(AppSession.user_id.is_(None)))


async def test_responsible_sees_chat_connections_only_for_own_houses(env):  # noqa: F811
    company = seed_id("alpha")
    responsible = await env["client"](seed_id("responsible"))
    boot = (await responsible.get("/api/v1/admin/bootstrap")).json()["companies"][0]
    assert boot["role"] == "operator"
    assert boot["surfaces"] == [
        "tickets",
        "signals",
        "assigned_houses",
        "overview",
        "chat_connections",
    ]
    houses = (await responsible.get(f"/api/v1/companies/{company}/houses")).json()
    assert [(h["house_id"], h["can_connect_chats"]) for h in houses] == [(str(seed_id("a1")), True)]
    operator = (await env["operator"].get("/api/v1/admin/bootstrap")).json()["companies"][0]
    assert "chat_connections" not in operator["surfaces"]
    admin = (await env["admin"].get(f"/api/v1/companies/{company}/houses")).json()
    assert {h["can_connect_chats"] for h in admin} == {True} and len(admin) == 2
    # Ответственный подключает чат своего дома (право chat.connect действующей политики).
    response = await responsible.post(f"/api/v1/houses/{seed_id('a1')}/chat-connections", json={})
    assert response.status_code == 201, response.text
    assert response.json()["quota"]["limit"] is None
    denied = await env["operator"].post(f"/api/v1/houses/{seed_id('a1')}/chat-connections", json={})
    assert denied.status_code in {403, 404}
