"""ORG/STAFF/HOUSE/UI-RBAC: real PostgreSQL and HTTP, no permission mocks."""

import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pyotp
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from domsignal.db.models import (
    AppSession,
    CompanyOnboardingRequest,
    EmployeeCredential,
    EmployeeInvitation,
    HouseManagement,
    InboxReceipt,
    ManagementCompany,
    OrganizationMembership,
    User,
)
from domsignal.main import create_app
from domsignal.services.employee_auth import COOKIE, HASHER, SOURCE, EmployeeAuthService
from domsignal.tools.seed_tickets import seed, seed_id

PASSWORD = "Isolated onboarding password 39!"
ENCODED = HASHER.hash(PASSWORD)
AUTH = "/api/v1/auth/employee"
APP = {
    "legal_name": "ООО Тестовая УК",
    "short_name": "Тестовая УК",
    "inn": "7701234567",
    "contact_name": "Администратор",
    "contact_email": "test@example.test",
    "requested_chat_count": 2,
}
STATUS = "/api/v1/onboarding/application-status"


@pytest_asyncio.fixture
async def env(integration_settings):
    settings = integration_settings.model_copy(
        update={
            "auth_mfa_encryption_key": Fernet.generate_key().decode(),
            "public_base_url": "https://testserver",
            "auth_rate_threshold": 100,
        }
    )
    await seed(settings)
    app = create_app(settings)
    container = app.state.container
    auth = EmployeeAuthService(settings)
    platform = uuid4()
    clients = []

    async def client(user_id=None):
        c = AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")
        clients.append(c)
        if user_id:
            token = secrets.token_urlsafe(32)
            now = datetime.now(UTC)
            async with container.session_factory() as db, db.begin():
                credential = await db.scalar(
                    select(EmployeeCredential).where(EmployeeCredential.user_id == user_id)
                )
                if credential is None:
                    db.add(
                        EmployeeCredential(
                            user_id=user_id,
                            login_name=f"fixture.{user_id.hex}",
                            password_hash=ENCODED,
                            password_changed_at=now,
                            password_change_required=False,
                            mfa_enabled=True,
                            encrypted_totp_secret=auth.cipher()
                            .encrypt(pyotp.random_base32().encode())
                            .decode(),
                        )
                    )
                db.add(
                    AppSession(
                        user_id=user_id,
                        token_hash=auth.digest(token),
                        source=SOURCE,
                        created_at=now,
                        last_seen_at=now,
                        idle_expires_at=now + timedelta(hours=1),
                        expires_at=now + timedelta(hours=8),
                    )
                )
            c.cookies.set(COOKIE, token)
            c.headers.update({"Origin": "https://testserver", "X-CSRF-Token": auth.csrf(token)})
        return c

    async with container.session_factory() as db, db.begin():
        db.add(User(id=platform, display_name="Platform fixture", platform_role="superadmin"))
    data = {
        "app": app,
        "container": container,
        "settings": settings,
        "auth": auth,
        "platform_id": platform,
        "client": client,
        "public": await client(),
        "platform": await client(platform),
        "admin": await client(seed_id("admin")),
        "operator": await client(seed_id("operator")),
        "foreign": await client(seed_id("beta-admin")),
        # Ссылки статуса заявок (D2): id заявки → секрет из ответа на подачу.
        "tokens": {},
    }
    yield data
    for c in clients:
        await c.aclose()
    await container.engine.dispose()


async def post(client, path, payload=None, expected=200, key=None):
    headers = {"Idempotency-Key": key or str(uuid4())}
    r = await client.post(path, json=payload or {}, headers=headers)
    assert r.status_code == expected, r.text
    return r.json()


async def application(env, payload=None):
    received = await post(
        env["public"], "/api/v1/onboarding/company-applications", payload or APP, 202
    )
    rows = (await env["platform"].get("/api/v1/platform/company-applications")).json()
    env["tokens"][rows[0]["id"]] = received["status_url"].split("/")[-1]
    return rows[0]["id"]


async def admin_link(env, obj, expected=200):
    """«Создать аккаунт администратора» со страницы статуса заявки (D2)."""
    return await post(
        env["public"], STATUS + "/admin-invitation", {"token": env["tokens"][obj]}, expected
    )


async def approve(env):
    obj = await application(env)
    approved = await post(
        env["platform"],
        f"/api/v1/platform/company-applications/{obj}/approve",
        {"reason": "Проверено вручную"},
    )
    assert approved["invitation"] is None  # ссылку больше не передают вручную
    approved["invitation"] = await admin_link(env, obj)
    return approved


async def invite(env, role="operator", company=None):
    company = company or seed_id("alpha")
    return await post(
        env["admin"],
        f"/api/v1/companies/{company}/employee-invitations",
        {"organization_role": role},
        201,
    )


async def auth_post(client, path, payload=None, expected=200):
    state = (await client.get(AUTH + "/session")).json()
    client.headers.update({"Origin": "https://testserver", "X-CSRF-Token": state["csrf_token"]})
    return await post(client, AUTH + path, payload, expected)


async def register(env, invitation, login=None, finish=True):
    c = await env["client"]()
    token = invitation["invitation_url"].split("/")[-1]
    await auth_post(
        c,
        "/invitations/register",
        {
            "token": token,
            "display_name": "Новый сотрудник",
            "login_name": login or f"new.{uuid4().hex}",
            "password": PASSWORD,
        },
    )
    setup = await auth_post(c, "/mfa/enroll")
    if finish:
        await auth_post(c, "/mfa/verify", {"code": pyotp.TOTP(setup["secret"]).now()})
        state = (await c.get(AUTH + "/session")).json()
        c.headers["X-CSRF-Token"] = state["csrf_token"]
    return c, setup["secret"]


async def test_public_application_no_access_duplicate_no_oracle_and_validation(env):
    c = env["public"]
    async with env["container"].session_factory() as db:
        before = {
            t.__tablename__: await db.scalar(select(func.count()).select_from(t))
            for t in (ManagementCompany, OrganizationMembership, EmployeeCredential, AppSession)
        }
    first = await post(c, "/api/v1/onboarding/company-applications", APP, 202)
    second = await post(c, "/api/v1/onboarding/company-applications", APP, 202)
    # Повтор ИНН: такой же публичный ответ со своей ссылкой статуса — нет оракула
    # «уже подано» и нет доступа к чужой заявке (D2).
    assert first.keys() == second.keys() and first["message"] == second["message"]
    assert first["status_url"] != second["status_url"]
    assert (await c.get("/api/v1/admin/bootstrap")).status_code == 401
    async with env["container"].session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(CompanyOnboardingRequest)) == 2
        for t in (ManagementCompany, OrganizationMembership, EmployeeCredential, AppSession):
            assert await db.scalar(select(func.count()).select_from(t)) == before[t.__tablename__]
        raw = [r["status_url"].split("/")[-1] for r in (first, second)]
        stored = json.dumps(
            (await db.scalars(select(CompanyOnboardingRequest.status_token_hash))).all()
        )
        assert not any(token in stored for token in raw)
    rows = (await env["platform"].get("/api/v1/platform/company-applications")).json()
    assert {r["inn_conflict"] for r in rows} == {"open_application"}
    assert all(r["status_link_issued"] and r["requested_chat_count"] == 2 for r in rows)
    for patch in (
        {"inn": "abc"},
        {"contact_email": None},
        {"contact_email": "test@mail"},
        {"house_addresses": ["д. 5"]},
        {"comment": "<script>"},
        {"comment": "a" * 2001},
        {"requested_chat_count": 0},
        {"requested_chat_count": None},
        {"house_addresses": ["<b>ул. Ленина, 1</b>"]},
        {"house_addresses": ["ул. Ленина, 1"] * 51},
    ):
        await post(c, "/api/v1/onboarding/company-applications", {**APP, **patch}, 422)


async def test_company_review_atomic_concurrent_and_private(env):
    obj = await application(env)
    assert (await env["admin"].get("/api/v1/platform/company-applications")).status_code == 403
    for action in ("start-review", "request-info"):
        await post(
            env["platform"],
            f"/api/v1/platform/company-applications/{obj}/{action}",
            {"reason": "Нужен контакт"},
        )
    path = f"/api/v1/platform/company-applications/{obj}/approve"
    results = await asyncio.gather(
        *[env["platform"].post(path, json={"reason": "Проверено"}) for _ in range(2)]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with env["container"].session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ManagementCompany)
                .where(ManagementCompany.inn == APP["inn"])
            )
            == 1
        )
        # Одобрение больше не выпускает ссылку для ручной передачи (D2).
        assert not await db.scalar(select(EmployeeInvitation))
    assert next(r.json() for r in results if r.status_code == 200)["invitation"] is None
    link = await admin_link(env, obj)
    # Та же ссылка статуса даёт то же приглашение, пока оно действует.
    assert (await admin_link(env, obj)) == link
    raw = link["invitation_url"].split("/")[-1]
    async with env["container"].session_factory() as db:
        invitation = await db.scalar(select(EmployeeInvitation))
        assert invitation.organization_role == "company_admin"
        assert invitation.source == "application_status"
        assert not await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.tenant_id == invitation.company_id
            )
        )
        assert invitation.token_hash == env["auth"].digest(raw, "invitation")
        assert raw not in json.dumps((await db.scalars(select(InboxReceipt.payload))).all())
    await post(env["platform"], path, {"reason": "Повтор"}, 409)


async def test_rejection_creates_no_company(env):
    obj = await application(env)
    await post(
        env["platform"],
        f"/api/v1/platform/company-applications/{obj}/reject",
        {"reason": "Не подтверждено"},
    )
    async with env["container"].session_factory() as db:
        assert not await db.scalar(
            select(ManagementCompany).where(ManagementCompany.inn == APP["inn"])
        )
        assert not await db.scalar(select(EmployeeInvitation))


async def test_new_employee_mfa_boundary_and_replay(env):
    approved = await approve(env)
    c, secret = await register(env, approved["invitation"], finish=False)
    async with env["container"].session_factory() as db:
        assert not await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.tenant_id == UUID(approved["application"]["company_id"])
            )
        )
    assert (await c.get("/api/v1/admin/bootstrap")).status_code == 401
    await auth_post(c, "/mfa/verify", {"code": pyotp.TOTP(secret).now()})
    boot = (await c.get("/api/v1/admin/bootstrap")).json()
    assert boot["companies"][0]["surfaces"] == [
        "overview",
        "tickets",
        "signals",
        "houses",
        "staff",
        "chat_connections",
        "organization",
    ]
    await auth_post(
        c,
        "/invitations/accept",
        {"token": approved["invitation"]["invitation_url"].split("/")[-1]},
        401,
    )
    again = await env["client"]()
    await auth_post(
        again,
        "/invitations/register",
        {
            "token": approved["invitation"]["invitation_url"].split("/")[-1],
            "display_name": "Replay",
            "login_name": "replay.user",
            "password": PASSWORD,
        },
        401,
    )


async def test_existing_employee_multi_company_and_claim_identity(env):
    approved = await approve(env)
    token = approved["invitation"]["invitation_url"].split("/")[-1]
    c = env["admin"]
    async with env["container"].session_factory() as db:
        before = await db.scalar(select(func.count()).select_from(User))
    await post(c, AUTH + "/invitations/claim", {"token": token})
    await post(env["operator"], AUTH + "/invitations/claim", {"token": token}, 401)
    await post(env["operator"], AUTH + "/invitations/accept", {"token": token}, 401)
    await post(c, AUTH + "/invitations/accept", {"token": token})
    boot = (await c.get("/api/v1/admin/bootstrap")).json()
    assert len(boot["companies"]) == 2
    async with env["container"].session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == before


@pytest.mark.parametrize("invalidate", ["expired", "revoked", "company", "inviter"])
async def test_invalidation_during_mfa_fails_closed(env, invalidate):
    inv = await invite(env)
    c, secret = await register(env, inv, finish=False)
    async with env["container"].session_factory() as db, db.begin():
        row = await db.get(EmployeeInvitation, UUID(inv["id"]))
        user_id = row.claimed_by_user_id
        if invalidate == "expired":
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif invalidate == "revoked":
            row.status = "revoked"
        elif invalidate == "company":
            company = await db.get(ManagementCompany, row.company_id)
            company.status = "suspended"
        else:
            member = await db.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.user_id == row.invited_by_user_id
                )
            )
            member.status = "revoked"
    response = await c.post(AUTH + "/mfa/verify", json={"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 401
    async with env["container"].session_factory() as db:
        assert not await db.scalar(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user_id)
        )
        assert not await db.scalar(select(AppSession).where(AppSession.user_id == user_id))


async def test_invitation_roles_foreign_company_and_idempotency(env):
    base = f"/api/v1/companies/{seed_id('alpha')}/employee-invitations"
    first = await post(
        env["admin"], base, {"organization_role": "operator"}, 201, key="same-invite-key"
    )
    second = await post(
        env["admin"], base, {"organization_role": "operator"}, 201, key="same-invite-key"
    )
    assert first["id"] == second["id"] and second["invitation_url"] is None
    await post(
        env["admin"], base, {"organization_role": "company_admin"}, 409, key="same-invite-key"
    )
    await post(env["admin"], base, {"organization_role": "superadmin"}, 422)
    await post(env["operator"], base, {"organization_role": "operator"}, 403)
    assert (await env["foreign"].get(base)).status_code == 404
    await post(env["foreign"], base + f"/{first['id']}/revoke", expected=404)


async def test_last_admin_concurrent_revoke_and_second_company_preserved(env):
    company = seed_id("alpha")
    base = f"/api/v1/companies/{company}/staff"
    await post(env["admin"], base + f"/{seed_id('admin')}/revoke", expected=409)
    async with env["container"].session_factory() as db, db.begin():
        member = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == seed_id("operator")
            )
        )
        member.role = "company_admin"
        db.add(
            OrganizationMembership(
                user_id=seed_id("operator"), tenant_id=seed_id("beta"), role="operator"
            )
        )
    results = await asyncio.gather(
        *[
            env["admin"].post(base + f"/{user}/revoke", json={})
            for user in (seed_id("admin"), seed_id("operator"))
        ]
    )
    assert sum(r.status_code == 200 for r in results) == 1
    async with env["container"].session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(
                    OrganizationMembership.tenant_id == company,
                    OrganizationMembership.status == "active",
                    OrganizationMembership.role == "company_admin",
                )
            )
            == 1
        )


async def test_houses_assignment_requests_approval_overlap_and_suspension(env):
    company = seed_id("alpha")
    base = f"/api/v1/companies/{company}"
    payload = {
        "requested_address": "Тестовый новый дом, 99",
        "requested_valid_from": datetime.now(UTC).isoformat(),
        "basis_text": "Проверяемое основание",
    }
    await post(env["operator"], base + "/house-management-requests", payload, 403)
    request = await post(env["admin"], base + "/house-management-requests", payload, 201)
    assert all(
        h["address"] != payload["requested_address"]
        for h in (await env["admin"].get(base + "/houses")).json()
    )
    result = await post(
        env["platform"],
        f"/api/v1/platform/house-management-requests/{request['id']}/approve",
        {
            "resolution": "new",
            "valid_from": payload["requested_valid_from"],
            "reason": "Управление проверено",
        },
    )
    houses = (await env["admin"].get(base + "/houses")).json()
    house = next(h for h in houses if h["management_id"] == result["management_id"])
    assert all(
        h["house_id"] != house["house_id"]
        for h in (await env["operator"].get(base + "/houses")).json()
    )
    await post(
        env["admin"],
        base + f"/staff/{seed_id('operator')}/assignments",
        {"management_id": house["management_id"], "role": "responsible"},
    )
    assert house["house_id"] in [
        h["house_id"] for h in (await env["operator"].get(base + "/houses")).json()
    ]
    duplicate = await post(env["admin"], base + "/house-management-requests", payload, 201)
    await post(
        env["platform"],
        f"/api/v1/platform/house-management-requests/{duplicate['id']}/approve",
        {
            "resolution": "existing",
            "house_id": house["house_id"],
            "valid_from": payload["requested_valid_from"],
            "reason": "Пересечение",
        },
        409,
    )
    await post(
        env["platform"],
        f"/api/v1/platform/companies/{company}/suspend",
        {"reason": "Проверка приостановки"},
    )
    assert (await env["operator"].get(base + "/houses")).status_code == 404
    await post(env["admin"], base + "/house-management-requests", payload, 404)
    await post(
        env["platform"],
        f"/api/v1/platform/companies/{company}/reactivate",
        {"reason": "Проверка завершена"},
    )
    assert (await env["operator"].get(base + "/houses")).status_code == 200


async def test_platform_privacy_every_read_endpoint(env, caplog):
    marker = "PRIVATE_RESIDENT_MARKER_" + uuid4().hex
    resident = await env["client"](seed_id("resident"))
    await post(
        resident,
        "/api/v1/reports",
        {"house_id": str(seed_id("a1")), "category": "water", "description": marker},
        201,
    )
    obj = await application(env)
    company = seed_id("alpha")
    request = await post(
        env["admin"],
        f"/api/v1/companies/{company}/house-management-requests",
        {
            "requested_address": "Privacy fixture house",
            "requested_valid_from": datetime.now(UTC).isoformat(),
            "basis_text": "Manual",
        },
        201,
    )
    paths = [
        "bootstrap",
        "company-applications",
        f"company-applications/{obj}",
        "companies",
        f"companies/{company}",
        "house-management-requests",
        f"house-management-requests/{request['id']}",
        "houses",
        "binding-disputes",
        "health",
        "audit",
        "dashboard?days=7",
        "dashboard?days=30",
        "chat-quota-requests",
        f"companies/{company}/chat-quota",
        f"companies/{company}/open-registration",
    ]
    for path in paths:
        response = await env["platform"].get("/api/v1/platform/" + path)
        assert response.status_code == 200, response.text
        assert marker not in response.text
    for action in ("start-review", "request-info", "approve"):
        result = await post(
            env["platform"],
            f"/api/v1/platform/company-applications/{obj}/{action}",
            {"reason": "Administrative review"},
        )
        assert marker not in json.dumps(result)
    approved_company = result["application"]["company_id"]
    result = await post(
        env["platform"],
        f"/api/v1/platform/companies/{approved_company}/invitations/first-admin",
        {"reason": "Replace unclaimed invitation"},
        201,
    )
    assert marker not in json.dumps(result)
    for action in ("suspend", "reactivate"):
        result = await post(
            env["platform"],
            f"/api/v1/platform/companies/{approved_company}/{action}",
            {"reason": "Administrative control"},
        )
        assert marker not in json.dumps(result)
    for action in ("start-review", "request-info", "approve"):
        body = {"reason": "Administrative house review"}
        if action == "approve":
            body.update(resolution="new", valid_from=datetime.now(UTC).isoformat())
        result = await post(
            env["platform"],
            f"/api/v1/platform/house-management-requests/{request['id']}/{action}",
            body,
        )
        assert marker not in json.dumps(result)
    await post(
        env["public"], "/api/v1/onboarding/company-applications", {**APP, "inn": "7709999999"}, 202
    )
    rejected = (await env["platform"].get("/api/v1/platform/company-applications")).json()[0]
    result = await post(
        env["platform"],
        f"/api/v1/platform/company-applications/{rejected['id']}/reject",
        {"reason": "Incomplete"},
    )
    assert marker not in json.dumps(result)
    denied_house = await post(
        env["admin"],
        f"/api/v1/companies/{company}/house-management-requests",
        {
            "requested_address": "Rejected privacy fixture",
            "basis_text": "Review required",
            "requested_valid_from": datetime.now(UTC).isoformat(),
        },
        201,
    )
    result = await post(
        env["platform"],
        f"/api/v1/platform/house-management-requests/{denied_house['id']}/reject",
        {"reason": "Incomplete"},
    )
    assert marker not in json.dumps(result)
    assert marker not in caplog.text
    assert (
        await env["platform"].get(f"/api/v1/houses/{seed_id('a1')}/incidents")
    ).status_code == 404


async def test_csrf_and_platform_require_employee_mfa(env):
    token = env["admin"].headers.pop("X-CSRF-Token")
    await post(
        env["admin"],
        f"/api/v1/companies/{seed_id('alpha')}/employee-invitations",
        {"organization_role": "operator"},
        403,
    )
    env["admin"].headers["X-CSRF-Token"] = token
    assert (await env["public"].get("/api/v1/platform/bootstrap")).status_code == 401
    assert (await env["operator"].get("/api/v1/platform/bootstrap")).status_code == 403


async def test_revocation_preserves_work_and_unassigns_open_ticket(env):
    from domsignal.db.models import Ticket, TicketEvent, WorkAttempt

    resident = await env["client"](seed_id("resident"))
    responsible = await env["client"](seed_id("responsible"))
    created = await post(
        resident,
        "/api/v1/reports",
        {
            "house_id": str(seed_id("a1")),
            "category": "water",
            "description": "Revocation history fixture",
        },
        201,
    )
    work = (await resident.get(f"/api/v1/incidents/{created['incident']['id']}/work-status")).json()
    tid = work["ticket_id"]

    async def command(action, body=None, client=responsible):
        view = (await client.get(f"/api/v1/tickets/{tid}")).json()
        return await post(
            client,
            f"/api/v1/tickets/{tid}/{action}",
            {
                "expected_version": view["version"],
                **(body or {}),
            },
        )

    await command("accept")
    await command("start")
    result = await command(
        "work-attempts", {"public_description": "Historical work remains intact"}
    )
    async with env["container"].session_factory() as db, db.begin():
        db.add(
            OrganizationMembership(
                user_id=seed_id("responsible"), tenant_id=seed_id("beta"), role="operator"
            )
        )
        before = (await db.get(WorkAttempt, UUID(result["attempt_id"]))).public_description
    await post(
        env["admin"], f"/api/v1/companies/{seed_id('alpha')}/staff/{seed_id('responsible')}/revoke"
    )
    assert (await responsible.get(f"/api/v1/tickets/{tid}")).status_code == 404
    assert (await responsible.get(AUTH + "/session")).json()["stage"] == "authenticated"
    contexts = (await responsible.get("/api/v1/admin/bootstrap")).json()["companies"]
    assert [c["company_id"] for c in contexts] == [str(seed_id("beta"))]
    async with env["container"].session_factory() as db:
        ticket = await db.get(Ticket, UUID(tid))
        assert ticket.assignee_id is ticket.accepted_by is ticket.accepted_at is None
        assert ticket.status == "verification_pending"
        attempt = await db.get(WorkAttempt, UUID(result["attempt_id"]))
        assert attempt.public_description == before and attempt.performed_by == seed_id(
            "responsible"
        )
        event = await db.scalar(
            select(TicketEvent).where(
                TicketEvent.ticket_id == UUID(tid), TicketEvent.reason == "employee_revoked"
            )
        )
        assert event.from_status == event.to_status == "verification_pending"
    assert (await env["admin"].get(f"/api/v1/tickets/{tid}/events")).status_code == 200


async def test_concurrent_claim_accept_revoke(env):
    inv = await invite(env)
    token = inv["invitation_url"].split("/")[-1]
    claims = await asyncio.gather(
        *[
            c.post(AUTH + "/invitations/claim", json={"token": token})
            for c in (env["operator"], env["foreign"])
        ]
    )
    assert sorted(r.status_code for r in claims) == [200, 401]
    owner = env["operator"] if claims[0].status_code == 200 else env["foreign"]
    results = await asyncio.gather(
        owner.post(AUTH + "/invitations/accept", json={"token": token}),
        env["admin"].post(
            f"/api/v1/companies/{seed_id('alpha')}/employee-invitations/{inv['id']}/revoke", json={}
        ),
    )
    assert [r.status_code for r in results] in ([200, 409], [401, 200])


async def test_backdating_explicit_reuse_and_concurrent_house_approve(env):
    request = await post(
        env["admin"],
        f"/api/v1/companies/{seed_id('alpha')}/house-management-requests",
        {
            "requested_address": "Existing physical house",
            "requested_valid_from": "2026-01-01T00:00:00Z",
            "basis_text": "Historical documents",
        },
        201,
    )
    from domsignal.db.models import House

    house_id = uuid4()
    async with env["container"].session_factory() as db, db.begin():
        db.add(House(id=house_id, name="Existing", address="Existing physical house"))
    path = f"/api/v1/platform/house-management-requests/{request['id']}/approve"
    body = {
        "resolution": "existing",
        "house_id": str(house_id),
        "valid_from": "2026-01-01T00:00:00Z",
        "reason": "Explicit documents",
    }
    await post(env["platform"], path, body, 409)
    results = await asyncio.gather(
        *[env["platform"].post(path, json={**body, "confirm_backdate": True}) for _ in range(2)]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with env["container"].session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(HouseManagement)
                .where(HouseManagement.house_id == house_id)
            )
            == 1
        )


async def test_multiple_responsibles_warning_and_operator_not_organization_overview(env):
    base = f"/api/v1/companies/{seed_id('alpha')}"
    await post(
        env["admin"],
        base + f"/staff/{seed_id('operator')}/assignments",
        {
            "management_id": str(seed_id("management-a1")),
            "role": "responsible",
        },
    )
    houses = (await env["admin"].get(base + "/houses")).json()
    assert next(h for h in houses if h["house_id"] == str(seed_id("a1")))["warning"]
    assert (await env["operator"].get(base + "/overview")).status_code == 403
    assert (await env["operator"].get(base + "/organization")).status_code == 403


async def test_first_admin_reissue_revokes_old_link_and_never_replays_raw_token(env):
    obj = await application(env)
    approved = await post(
        env["platform"],
        f"/api/v1/platform/company-applications/{obj}/approve",
        {"reason": "Reviewed documents"},
    )
    company = approved["application"]["company_id"]
    old = (await admin_link(env, obj))["invitation_url"].split("/")[-1]
    path = f"/api/v1/platform/companies/{company}/invitations/first-admin"
    key = str(uuid4())
    new = await post(env["platform"], path, {"reason": "Lost unclaimed link"}, 201, key)
    repeated = await post(env["platform"], path, {"reason": "Lost unclaimed link"}, 201, key)
    assert new["id"] == repeated["id"] and repeated["invitation_url"] is None
    await post(env["foreign"], AUTH + "/invitations/claim", {"token": old}, 401)
    token = new["invitation_url"].split("/")[-1]
    await post(env["foreign"], AUTH + "/invitations/claim", {"token": token})
    await post(env["foreign"], AUTH + "/invitations/accept", {"token": token})
    await post(env["platform"], path, {"reason": "Must not add a second first admin"}, 409)
    # Администратор создан: страница статуса больше не выпускает приглашений.
    await admin_link(env, obj, 409)


async def test_revoke_racing_ticket_accept_leaves_no_current_assignment(env):
    from domsignal.db.models import Ticket

    resident = await env["client"](seed_id("resident"))
    responsible = await env["client"](seed_id("responsible"))
    created = await post(
        resident,
        "/api/v1/reports",
        {"house_id": str(seed_id("a1")), "category": "water", "description": "Race fixture"},
        201,
    )
    work = (await resident.get(f"/api/v1/incidents/{created['incident']['id']}/work-status")).json()
    tid = work["ticket_id"]
    view = (await responsible.get(f"/api/v1/tickets/{tid}")).json()
    accepted, revoked = await asyncio.gather(
        responsible.post(
            f"/api/v1/tickets/{tid}/accept",
            json={"expected_version": view["version"]},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        env["admin"].post(
            f"/api/v1/companies/{seed_id('alpha')}/staff/{seed_id('responsible')}/revoke", json={}
        ),
    )
    assert accepted.status_code in (200, 404) and revoked.status_code == 200
    async with env["container"].session_factory() as db:
        ticket = await db.get(Ticket, UUID(tid))
        assert ticket.assignee_id is ticket.accepted_by is ticket.accepted_at is None
    assert (await responsible.get(f"/api/v1/tickets/{tid}")).status_code == 404
