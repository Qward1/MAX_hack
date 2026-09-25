"""AUTH acceptance: real HTTP application + independent PostgreSQL transactions."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pyotp
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from domsignal.db.models import (
    AppSession,
    AuthChallenge,
    AuthRateLimit,
    EmployeeCredential,
    HouseAssignment,
    HouseManagement,
    InboxReceipt,
    ManagementCompany,
    OrganizationMembership,
    RecoveryCode,
    ResidentMembership,
)
from domsignal.main import create_app
from domsignal.services.employee_auth import (
    COOKIE,
    PRE_COOKIE,
    SOURCE,
    EmployeeAuthService,
    normalize_login,
    verify_password,
)
from domsignal.tools.seed_tickets import seed, seed_id

BASE = "/api/v1/auth/employee"
PASSWORD = "A long unique test password 946!"


@pytest_asyncio.fixture
async def auth(integration_settings):
    settings = integration_settings.model_copy(
        update={
            "auth_mfa_encryption_key": Fernet.generate_key().decode(),
            "public_base_url": "https://testserver",
        }
    )
    await seed(settings)
    app = create_app(settings)
    container = app.state.container
    service = EmployeeAuthService(settings)
    async with container.session_factory() as db, db.begin():
        db.add(
            HouseAssignment(
                user_id=seed_id("operator"), management_id=seed_id("management-a1"), role="operator"
            )
        )
        temporary = await service.provision(db, seed_id("operator"), "create", "Employee.ONE")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as client:
        yield {
            "client": client,
            "app": app,
            "container": container,
            "service": service,
            "temporary": temporary,
            "settings": settings,
        }
    await container.engine.dispose()


async def state(d):
    r = await d["client"].get(BASE + "/session")
    assert r.status_code == 200, r.text
    d["csrf"] = r.json()["csrf_token"]
    return r.json()


async def post(d, path, payload=None, **kwargs):
    r = await d["client"].post(
        BASE + path,
        json=payload or {},
        headers={
            "Origin": "https://testserver",
            "X-CSRF-Token": d["csrf"],
            **kwargs,
        },
    )
    if r.status_code == 200 and "csrf_token" in r.json():
        d["csrf"] = r.json()["csrf_token"]
    return r


async def begin(d, password=None):
    await state(d)
    return await post(
        d, "/login", {"login_name": "EMPLOYEE.one", "password": password or d["temporary"]}
    )


async def enroll(d):
    assert (await begin(d)).json()["stage"] == "password_change"
    assert (await post(d, "/password/change", {"password": PASSWORD})).json()[
        "stage"
    ] == "mfa_enroll"
    r = await post(d, "/mfa/enroll")
    assert r.status_code == 200, r.text
    d["secret"] = r.json()["secret"]
    return r


async def finish(d):
    await enroll(d)
    r = await post(d, "/mfa/verify", {"code": pyotp.TOTP(d["secret"]).now()})
    assert r.status_code == 200, r.text
    d["codes"] = r.json()["recovery_codes"]
    return r


async def operator(d, action):
    async with d["container"].session_factory() as db, db.begin():
        return await d["service"].provision(db, seed_id("operator"), action)


async def test_auth01_06_first_login_and_password_storage(auth):
    d = auth
    initial = await state(d)
    old = d["client"].cookies.get(PRE_COOKIE)
    r = await begin(d)
    assert r.json()["stage"] == "password_change"
    assert old != d["client"].cookies.get(PRE_COOKIE)
    assert (await d["client"].get("/api/v1/me")).status_code == 401
    assert (await post(d, "/mfa/enroll")).status_code == 401
    assert (await post(d, "/password/change", {"password": "passwordpassword"})).status_code == 403
    r = await post(d, "/password/change", {"password": PASSWORD})
    assert r.json()["stage"] == "mfa_enroll"
    assert (await d["client"].get("/api/v1/me")).status_code == 401
    setup = await post(d, "/mfa/enroll")
    assert setup.status_code == 200
    assert pyotp.parse_uri(setup.json()["otpauth_uri"]).secret == setup.json()["secret"]
    assert "<svg" in setup.json()["qr_svg"]
    assert "https://" not in setup.json()["qr_svg"]
    async with d["container"].session_factory() as db:
        credential = await db.scalar(select(EmployeeCredential))
        assert credential.login_name == "employee.one"
        assert credential.password_hash.startswith("$argon2id$")
        assert await verify_password(credential.password_hash, PASSWORD)
        assert not credential.password_change_required
        assert (
            await db.scalar(
                select(func.count()).select_from(AppSession).where(AppSession.source == SOURCE)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ResidentMembership)
                .where(ResidentMembership.user_id == seed_id("operator"))
            )
            == 0
        )
    assert initial["stage"] == "login"


async def test_auth02_unknown_and_wrong_indistinguishable(auth):
    await state(auth)
    responses = [
        await post(auth, "/login", {"login_name": name, "password": "bad-password"})
        for name in ["unknown-person", "employee.one"]
    ]
    assert [r.status_code for r in responses] == [401, 401]
    bodies = [{k: v for k, v in r.json().items() if k != "trace_id"} for r in responses]
    assert bodies[0] == bodies[1]


async def test_auth07_14_34_cookie_rotation_logout_and_replay(auth):
    await enroll(auth)
    pre = auth["client"].cookies.get(PRE_COOKIE)
    assert (await post(auth, "/mfa/verify", {"code": "invalid"})).status_code == 401
    r = await post(auth, "/mfa/verify", {"code": pyotp.TOTP(auth["secret"]).now()})
    assert r.status_code == 200
    cookie = r.headers.get_list("set-cookie")[0]
    assert all(x in cookie for x in ["Secure", "HttpOnly", "SameSite=lax", "Path=/"])
    token = auth["client"].cookies.get(COOKIE)
    assert token and token != pre
    assert auth["client"].cookies.get(PRE_COOKIE) is None
    assert (await state(auth))["stage"] == "authenticated"
    assert (await auth["client"].get("/api/v1/me")).status_code == 200
    # Employee cookie token cannot be used in bearer path to bypass CSRF.
    assert (
        await auth["client"].get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 401
    assert (await post(auth, "/logout")).status_code == 200
    assert (await auth["client"].get("/api/v1/me")).status_code == 401
    assert (await post(auth, "/logout")).status_code == 200
    auth["client"].cookies.set(COOKIE, token)
    assert (await auth["client"].get("/api/v1/me")).status_code == 401
    auth["client"].cookies.clear()
    auth["client"].cookies.set(PRE_COOKIE, pre)
    auth["csrf"] = auth["service"].csrf(pre)
    assert (
        await post(auth, "/mfa/verify", {"code": pyotp.TOTP(auth["secret"]).now()})
    ).status_code == 401


async def test_auth15_16_recovery_is_one_time_second_factor(auth):
    await finish(auth)
    code = auth["codes"][0]
    await post(auth, "/logout")
    await state(auth)
    assert (await post(auth, "/recovery", {"code": code})).status_code == 401
    assert (await begin(auth, PASSWORD)).json()["stage"] == "mfa_challenge"
    assert (await post(auth, "/recovery", {"code": code})).status_code == 200
    await post(auth, "/logout")
    await begin(auth, PASSWORD)
    assert (await post(auth, "/recovery", {"code": code})).status_code == 401
    async with auth["container"].session_factory() as db:
        codes = (await db.scalars(select(RecoveryCode))).all()
        assert len(codes) == 10
        assert sum(c.used_at is not None for c in codes) == 1
        assert all(c.code_hash != code for c in codes)


@pytest.mark.parametrize("action", ["reset-mfa", "reset-password", "revoke"])
async def test_auth17_19_32_35_reset_revokes_sessions_and_challenges(auth, action):
    await finish(auth)
    token = auth["client"].cookies.get(COOKIE)
    # A resident session belonging to the same identity must survive operator reset.
    async with auth["container"].session_factory() as db:
        resident = await auth["container"].session_service.issue_max_session(
            db, max_user_id="a16-synthetic-operator", display_name="Existing employee"
        )
    auth["client"].cookies.clear()
    await begin(auth, PASSWORD)
    temporary = await operator(auth, action)
    assert (
        await auth["client"].get("/api/v1/me", headers={"Cookie": f"{COOKIE}={token}"})
    ).status_code == 401
    assert (await post(auth, "/recovery", {"code": auth["codes"][0]})).status_code == 401
    assert (
        await auth["client"].get(
            "/api/v1/me", headers={"Authorization": f"Bearer {resident.access_token}"}
        )
    ).status_code == 200
    if action == "revoke":
        assert (await begin(auth, PASSWORD)).status_code == 401
    if action == "reset-password":
        assert (await begin(auth, PASSWORD)).status_code == 401
        assert (await begin(auth, temporary)).json()["stage"] == "password_change"
    assert token is not None


@pytest.mark.parametrize("relation", ["membership", "assignment", "company", "management", "moved"])
async def test_auth20_23_33_current_authority_after_login(auth, relation):
    await finish(auth)
    client = auth["client"]
    own = f"/api/v1/tickets?house_id={seed_id('a1')}"
    assert (await client.get(own)).status_code == 200
    assert (await client.get(f"/api/v1/tickets?house_id={seed_id('b1')}")).status_code == 404
    assert (await client.get(f"/api/v1/tickets?house_id={seed_id('a2')}")).status_code == 404
    async with auth["container"].session_factory() as db, db.begin():
        if relation == "membership":
            await db.execute(
                update(OrganizationMembership)
                .where(OrganizationMembership.user_id == seed_id("operator"))
                .values(status="revoked")
            )
        elif relation == "assignment":
            await db.execute(
                update(HouseAssignment)
                .where(HouseAssignment.user_id == seed_id("operator"))
                .values(status="revoked")
            )
        elif relation == "company":
            await db.execute(
                update(ManagementCompany)
                .where(ManagementCompany.id == seed_id("alpha"))
                .values(status="suspended")
            )
        elif relation == "management":
            await db.execute(
                update(HouseManagement)
                .where(HouseManagement.id == seed_id("management-a1"))
                .values(status="ended")
            )
        else:
            await db.execute(
                update(HouseAssignment)
                .where(HouseAssignment.user_id == seed_id("operator"))
                .values(management_id=seed_id("management-a2"))
            )
    assert (await client.get(own)).status_code == 404
    assert (await state(auth))["stage"] == "authenticated"  # Identity-only remains.


async def test_auth24_26_36_csrf_origins_and_rate_limit(auth):
    await state(auth)
    payload = {"login_name": "employee.one", "password": auth["temporary"]}
    assert (await auth["client"].post(BASE + "/login", json=payload)).status_code == 403
    assert (await post(auth, "/login", payload, Origin="https://evil.example")).status_code == 403
    assert (await begin(auth)).status_code == 200
    await post(auth, "/logout")
    await state(auth)
    attempts = [
        await post(auth, "/login", {"login_name": "employee.one", "password": "wrong"})
        for _ in range(11)
    ]
    assert attempts[-1].status_code == 429
    assert attempts[-1].headers["content-type"].startswith("application/problem+json")


async def test_p7b_ip_rate_limit_keeps_only_keyed_slot(auth):
    """P7b §2: ограничитель по адресу работает, а адреса в базе нет.

    Адрес превращается в номер ячейки — HMAC-SHA256 с `SESSION_SECRET` по
    модулю 65 536; в таблице только номер, счётчик и время.
    """
    app, service = auth["app"], auth["service"]
    blocked_ip, other_ip = "203.0.113.77", "198.51.100.23"
    slot = int(service.digest(blocked_ip, "rate-ip")[:8], 16) % 65536
    assert slot != int(service.digest(other_ip, "rate-ip")[:8], 16) % 65536
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(blocked_ip, 40000)),
        base_url="https://testserver",
    ) as client:
        d = {"client": client}
        await state(d)
        # Разные имена: ячейки имён не переполняются, срабатывает ячейка адреса
        # (порог имени × 5 = 50 попыток за окно).
        codes = [
            (
                await post(d, "/login", {"login_name": f"nobody.{n}", "password": "wrong"})
            ).status_code
            for n in range(55)
        ]
    assert codes[0] == 401 and codes[-1] == 429
    assert codes.index(429) == 49  # 1 запрос сессии + 49 входов = 50 разрешённых
    async with AsyncClient(
        transport=ASGITransport(app=app, client=(other_ip, 40001)),
        base_url="https://testserver",
    ) as client:
        assert (await client.get(BASE + "/session")).status_code == 200
    async with auth["container"].session_factory() as db:
        columns = set(AuthRateLimit.__table__.columns.keys())
        assert columns == {"slot", "attempts", "window_at", "locked_until"}
        row = await db.get(AuthRateLimit, slot)
        assert row is not None and row.locked_until is not None
        receipts = [
            json.dumps(item.payload)
            for item in await db.scalars(
                select(InboxReceipt).where(InboxReceipt.event_type.like("employee_auth.%"))
            )
        ]
    assert all(blocked_ip not in item and other_ip not in item for item in receipts)


async def test_auth31_concurrent_mfa_consumed_once(auth):
    await enroll(auth)
    code = pyotp.TOTP(auth["secret"]).now()
    responses = await asyncio.gather(*[post(auth, "/mfa/verify", {"code": code}) for _ in range(2)])
    assert sorted(r.status_code for r in responses) == [200, 401]
    async with auth["container"].session_factory() as db:
        assert (
            await db.scalar(
                select(func.count()).select_from(AppSession).where(AppSession.source == SOURCE)
            )
            == 1
        )


async def test_auth37_39_restart_persistence_encryption_audit(auth, caplog):
    await finish(auth)
    token = auth["client"].cookies.get(COOKIE)
    app = create_app(auth["settings"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver", cookies={COOKIE: token}
    ) as client:
        assert (await client.get("/api/v1/me")).status_code == 200
        await operator(auth, "revoke")
        assert (await client.get("/api/v1/me")).status_code == 401
    await app.state.container.engine.dispose()
    async with auth["container"].session_factory() as db:
        credential = await db.scalar(select(EmployeeCredential))
        assert credential.encrypted_totp_secret != auth["secret"]
        assert (
            auth["service"].cipher().decrypt(credential.encrypted_totp_secret.encode()).decode()
            == auth["secret"]
        )
        events = (
            await db.scalars(
                select(InboxReceipt).where(InboxReceipt.event_type.like("employee_auth.%"))
            )
        ).all()
        serialized = json.dumps([e.payload for e in events]) + caplog.text
        for secret in [token, auth["secret"], PASSWORD, auth["temporary"], *auth["codes"]]:
            assert secret not in serialized
        assert {
            "employee_auth.login_success",
            "employee_auth.mfa_enrolled",
            "employee_auth.credential_revoked",
        }.issubset({e.event_type for e in events})


@pytest.mark.parametrize("expiry", ["idle", "absolute", "challenge", "temporary"])
async def test_expiry(auth, expiry):
    past = datetime.now(UTC) - timedelta(seconds=1)
    if expiry in {"idle", "absolute"}:
        await finish(auth)
        async with auth["container"].session_factory() as db, db.begin():
            await db.execute(
                update(AppSession)
                .where(AppSession.source == SOURCE)
                .values(**{"idle_expires_at" if expiry == "idle" else "expires_at": past})
            )
        assert (await auth["client"].get("/api/v1/me")).status_code == 401
    else:
        await state(auth)
        async with auth["container"].session_factory() as db, db.begin():
            if expiry == "challenge":
                await db.execute(update(AuthChallenge).values(expires_at=past))
            else:
                await db.execute(update(EmployeeCredential).values(temporary_expires_at=past))
        assert (
            await post(
                auth, "/login", {"login_name": "employee.one", "password": auth["temporary"]}
            )
        ).status_code == 401


async def test_provision_never_creates_membership_or_duplicate_credential(auth):
    assert normalize_login(" Employee.ONE ") == "employee.one"
    async with auth["container"].session_factory() as db:
        for user in ["resident", "revoked"]:
            with pytest.raises(ValueError, match="membership"):
                async with db.begin():
                    await auth["service"].provision(db, seed_id(user), "create", f"employee-{user}")
        with pytest.raises(ValueError, match="exists"):
            async with db.begin():
                await auth["service"].provision(db, seed_id("operator"), "create", "other-login")


async def test_totp_replay_and_temporary_single_use(auth):
    await finish(auth)
    code = pyotp.TOTP(auth["secret"]).now()
    await post(auth, "/logout")
    assert (await begin(auth, auth["temporary"])).status_code == 401
    await begin(auth, PASSWORD)
    assert (await post(auth, "/mfa/challenge", {"code": code})).status_code == 401
    # Accepted adjacent timestep is deterministic and uses the same standard library.
    next_code = pyotp.TOTP(auth["secret"]).at(datetime.now(UTC) + timedelta(seconds=30))
    assert (await post(auth, "/mfa/challenge", {"code": next_code})).status_code == 200


async def test_auth24_25_33_business_mutation_csrf_and_membership(auth):
    await finish(auth)
    client = auth["client"]
    resident = (
        await client.post("/api/v1/auth/test-session", json={"actor": "a16-resident"})
    ).json()
    report = await client.post(
        "/api/v1/reports",
        headers={
            "Authorization": f"Bearer {resident['access_token']}",
            "Idempotency-Key": "auth-report-123",
        },
        json={
            "house_id": str(seed_id("a1")),
            "category": "water",
            "description": "A10 CSRF test report",
        },
    )
    assert report.status_code == 201, report.text
    ticket = (await client.get(f"/api/v1/tickets?house_id={seed_id('a1')}")).json()["items"][0]
    admin = (await client.post("/api/v1/auth/test-session", json={"actor": "a16-admin"})).json()
    assigned = await client.post(
        f"/api/v1/tickets/{ticket['id']}/assign",
        headers={
            "Authorization": f"Bearer {admin['access_token']}",
            "Idempotency-Key": "auth-assign-123",
        },
        json={
            "expected_version": ticket["version"],
            "assignee_id": str(seed_id("operator")),
            "reason": "Auth test assignment",
        },
    )
    assert assigned.status_code == 200, assigned.text
    ticket = (await client.get(f"/api/v1/tickets/{ticket['id']}")).json()
    path = f"/api/v1/tickets/{ticket['id']}/accept"
    headers = {"Origin": "https://testserver", "Idempotency-Key": "auth-command-123"}
    assert (
        await client.post(path, json={"expected_version": ticket["version"]}, headers=headers)
    ).status_code == 403
    headers["X-CSRF-Token"] = auth["csrf"]
    accepted = await client.post(
        path, json={"expected_version": ticket["version"]}, headers=headers
    )
    assert accepted.status_code == 200, accepted.text
    ticket = (await client.get(f"/api/v1/tickets/{ticket['id']}")).json()
    async with auth["container"].session_factory() as db, db.begin():
        await db.execute(
            update(OrganizationMembership)
            .where(OrganizationMembership.user_id == seed_id("operator"))
            .values(status="revoked")
        )
    headers["Idempotency-Key"] = "auth-command-456"
    denied = await client.post(
        f"/api/v1/tickets/{ticket['id']}/start",
        json={"expected_version": ticket["version"]},
        headers=headers,
    )
    assert denied.status_code == 404
