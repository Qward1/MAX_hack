"""Своя УК с нуля — путь жюри (F1 §3.3, §5.5) и кейсы бота через эмулятор MAX.

Шаги идут по порядку и опираются на предыдущие: заявка УК → одобрение
проверочным аккаунтом платформы → администратор УК с TOTP → дом с регионом →
подключение группы MAX → чтение чата → жители из группы → `/report` → работа по
заявке до подтверждения жителем → личка бота → опасность и ловушки D6 →
переписка → сигнал. Имена тестов — номера кейсов из `docs/qa/TEST_CASES.md`.
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from typing import Any

import pyotp
import pytest

from tests.acceptance.conftest import (
    EMPLOYEE,
    PASSWORD,
    Problem,
    Stand,
    Web,
    buttons_of,
    now_ms,
    text_of,
    to_chat,
    to_user,
)

pytestmark = pytest.mark.acceptance

S: dict[str, Any] = {}
REGION = {"region_code": "RU-TA", "municipality_code": "kazan", "territory_policy": "mixed"}


def need(*keys: str) -> None:
    missing = [key for key in keys if key not in S]
    if missing:
        pytest.skip(f"предыдущий шаг не выполнен: {missing}")


def first_login(stand: Stand, login: str, temporary: str) -> tuple[Web, str]:
    """Первый вход по временному паролю: свой пароль → TOTP → коды восстановления."""
    web = Web(stand.base)
    web.get(EMPLOYEE + "/session")
    stage = web.post(EMPLOYEE + "/login", {"login_name": login, "password": temporary})["stage"]
    assert stage == "password_change", stage
    web.post(EMPLOYEE + "/password/change", {"password": PASSWORD})
    secret = web.post(EMPLOYEE + "/mfa/enroll")["secret"]
    verified = web.post(EMPLOYEE + "/mfa/verify", {"code": pyotp.TOTP(secret).now()})
    assert len(verified.get("recovery_codes") or []) == 10
    assert web.get(EMPLOYEE + "/session")["stage"] == "authenticated"
    return web, secret


def wait_for(read, check, timeout: float = 40, step: float = 1.5) -> Any:
    deadline = time.monotonic() + timeout
    value = read()
    while not check(value) and time.monotonic() < deadline:
        time.sleep(step)
        value = read()
    assert check(value), value
    return value


def ticket(stand: Stand, ticket_id: str) -> dict[str, Any]:
    return S["admin"].get(f"/api/v1/tickets/{ticket_id}")


def button(row: dict[str, Any], text: str) -> dict[str, Any]:
    found = [b for b in buttons_of(row) if b.get("text") == text]
    assert found, f"нет кнопки «{text}»: {[b.get('text') for b in buttons_of(row)]}"
    return found[0]


def mid(row: dict[str, Any]) -> str:
    return f"mid.rec{row['at']}"


# ---------------------------------------------------------------- заявка и доступ


def test_tc014_company_application_and_status_page(stand: Stand) -> None:
    run = stand.run_id
    base = random.randint(10_000, 89_999) * 100
    S.update(
        inn="77" + f"{random.randint(0, 99_999_999):08d}",
        address=f"Казань, ул. Приёмочная, {base // 100 % 900 + 100}",
        chat=-(3_000_000_000 + base),
        admin_max=base + 1,
        r1=base + 2,
        r2=base + 3,
        outsider=base + 4,
        name=f"УК «Приёмка {run}»",
    )
    public = stand.public()
    received = public.post(
        "/api/v1/onboarding/company-applications",
        {
            "legal_name": f"ООО «Приёмка {run}»",
            "short_name": S["name"],
            "inn": S["inn"],
            "contact_name": "Иван Проверкин",
            "contact_email": "acceptance@example.org",
            "requested_chat_count": 2,
            "house_addresses": [S["address"]],
        },
        expect=202,
    )
    S["status_token"] = received["status_url"].rstrip("/").split("/")[-1]
    view = public.post("/api/v1/onboarding/application-status", {"token": S["status_token"]})
    assert view["status"] == "submitted"
    assert view["house_addresses"] == [S["address"]]
    assert view["admin_account"] == "unavailable"


def test_tc016_platform_approves_with_quota_and_admin_enrolls_totp(stand: Stand) -> None:
    need("status_token")
    login = f"acc.platform.{stand.run_id}"
    created = stand.tool(
        "domsignal.tools.showcase",
        "create-platform-reviewer",
        "--login-name",
        login,
        "--operator",
        "acceptance",
        "--reason",
        "Приёмочный прогон F1: путь жюри",
    )
    platform, _ = first_login(stand, login, created["temporary_password"])
    rows = platform.get("/api/v1/platform/company-applications")
    mine = [row for row in rows if row.get("inn") == S["inn"]]
    assert len(mine) == 1, [row.get("inn") for row in rows][:5]
    approved = platform.post(
        f"/api/v1/platform/company-applications/{mine[0]['id']}/approve",
        {"reason": "Проверено: приёмочный прогон", "chat_quota": 2},
    )
    S["company"] = approved["application"]["company_id"]
    S["platform"] = platform
    public = stand.public()
    assert (
        public.post("/api/v1/onboarding/application-status", {"token": S["status_token"]})[
            "admin_account"
        ]
        == "create"
    )
    link = public.post(
        "/api/v1/onboarding/application-status/admin-invitation", {"token": S["status_token"]}
    )
    token = link["invitation_url"].rstrip("/").split("/")[-1]
    admin = Web(stand.base)
    admin.get(EMPLOYEE + "/session")
    S["admin_login"] = f"acc.admin.{stand.run_id}"
    admin.post(
        EMPLOYEE + "/invitations/register",
        {
            "token": token,
            "display_name": "Иван Проверкин",
            "login_name": S["admin_login"],
            "password": PASSWORD,
        },
    )
    secret = admin.post(EMPLOYEE + "/mfa/enroll")["secret"]
    verified = admin.post(EMPLOYEE + "/mfa/verify", {"code": pyotp.TOTP(secret).now()})
    assert len(verified.get("recovery_codes") or []) == 10
    admin.post(EMPLOYEE + "/logout", {})
    # Повторный вход — пароль и код TOTP следующего окна.
    S["admin"] = stand.employee(S["admin_login"], PASSWORD, secret)
    boot = S["admin"].get("/api/v1/admin/bootstrap")
    assert [c["company_id"] for c in boot["companies"]] == [S["company"]]
    quota = S["admin"].get(f"/api/v1/companies/{S['company']}/chat-quota")["quota"]
    assert quota["limit"] == 2 and quota["used"] == 0


def test_tc020_house_from_application_approved_with_region(stand: Stand) -> None:
    need("platform", "admin")
    rows = S["platform"].get("/api/v1/platform/house-management-requests")
    mine = [row for row in rows if row.get("requested_address") == S["address"]]
    assert mine, "адрес из заявки УК не стал заявкой на дом"
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    result = S["platform"].post(
        "/api/v1/platform/house-management-requests/approve-batch",
        {
            "reason": "Договор управления проверен",
            "request_ids": [mine[0]["id"]],
            "valid_from": today.isoformat(),
            **REGION,
        },
    )
    assert result, result
    houses = wait_for(
        lambda: S["admin"].get(f"/api/v1/companies/{S['company']}/houses"),
        lambda rows: any(h["address"] == S["address"] for h in rows),
    )
    house = next(h for h in houses if h["address"] == S["address"])
    S["house"] = house["house_id"]
    assert house["open_resident_access"] is False


# ---------------------------------------------------------------- группа MAX


def test_tc068_group_connected_bot_rights_checked_then_confirmed(stand: Stand) -> None:
    need("house")
    chat, owner = S["chat"], S["admin_max"]
    since = now_ms()
    conn = S["admin"].post(
        f"/api/v1/houses/{S['house']}/chat-connections", {"scope_type": "house"}, expect=201
    )
    code = conn["correlation_token"]
    assert code
    stand.emu(
        "chat",
        "--chat-id",
        str(chat),
        "--title",
        f"Дом · {S['address']}",
        "--admin",
        str(owner),
        "--member",
        str(S["r1"]),
        "--member",
        str(S["r2"]),
        "--no-bot-admin",
    )
    stand.emu("start", "--user", str(owner), "--payload", code)
    accepted = stand.wait_outbox(since, to_user(owner))
    assert "Код подключения принят" in text_of(accepted)
    stand.emu("bot-added", "--chat-id", str(chat), "--by", str(owner))
    view = wait_for(
        lambda: S["admin"].get(f"/api/v1/chat-connections/{conn['id']}"),
        lambda v: v["last_error_code"] == "bot_permission_missing",
    )
    assert view["candidate_max_chat_id"] == str(chat)
    # Бот без прав администратора: подключение не проходит, объяснение — код ошибки.
    with pytest.raises(Problem) as denied:
        S["admin"].post(f"/api/v1/chat-connections/{conn['id']}/approve", {"confirm": True})
    assert denied.value.status == 409 and denied.value.code == "bot_permission_missing"
    # Права выданы в MAX — та же кнопка «Подтвердить подключение» проверяет заново (d28d4d9).
    stand.emu(
        "chat", "--chat-id", str(chat), "--title", f"Дом · {S['address']}", "--admin", str(owner)
    )
    binding = S["admin"].post(f"/api/v1/chat-connections/{conn['id']}/approve", {"confirm": True})
    assert binding["status"] == "active"
    S["binding"] = binding["id"]
    quota = S["admin"].get(f"/api/v1/companies/{S['company']}/chat-quota")["quota"]
    assert quota["used"] == 1


def test_tc066_chat_reading_enabled_notice_once(stand: Stand) -> None:
    need("binding")
    since = now_ms()
    view = S["admin"].post(
        f"/api/v1/chat-bindings/{S['binding']}/passive-capture", {"enabled": True}
    )
    assert view["passive_capture_enabled"] is True and view["notice_queued"] is True
    notice = stand.wait_outbox(since, to_chat(S["chat"]))
    assert "чита" in text_of(notice).lower()


def test_tc067_publication_settings_without_quiet_hours(stand: Stand) -> None:
    """ПР-21 шаг 2: без тихих часов посты не ждут утра (прогон может идти ночью)."""
    need("binding")
    path = f"/api/v1/chat-bindings/{S['binding']}/settings"
    view = S["admin"].get(path)
    assert view["post_ticket_status"] and view["post_company_messages"] and view["post_polls"]
    assert not view["post_platform_messages"]
    saved = S["admin"].post(
        path,
        {
            "post_ticket_status": True,
            "post_company_messages": True,
            "post_polls": True,
            "post_platform_messages": False,
            "quiet_start": "00:00",
            "quiet_end": "00:00",
        },
    )
    assert saved["quiet_start"] == saved["quiet_end"]


def test_tc072_group_member_gets_house_outsider_does_not(stand: Stand) -> None:
    need("binding")
    resident = stand.resident(S["r1"], "Житель Один")
    houses = [h["id"] for h in resident.get("/api/v1/me").get("houses", [])]
    assert S["house"] in houses
    S["r1_web"] = resident
    outsider = stand.resident(S["outsider"], "Посторонний")
    assert S["house"] not in [h["id"] for h in outsider.get("/api/v1/me").get("houses", [])]


# ---------------------------------------------------------------- заявка из группы


def test_tc057_report_in_group_creates_ticket_and_post(stand: Stand) -> None:
    need("binding")
    stand.emu("start", "--user", str(S["r1"]))
    since = now_ms()
    stand.emu(
        "message",
        "--chat-id",
        str(S["chat"]),
        "--user",
        str(S["r1"]),
        "--text",
        "/report в первом подъезде не работает лифт",
        "--name",
        "Житель Один",
    )
    post = stand.wait_outbox(
        since, lambda r: to_chat(S["chat"])(r) and r["kind"] == "send" and "Заявка" in text_of(r)
    )
    assert "Статус" in text_of(post)
    S["post"] = post
    items = wait_for(
        lambda: S["admin"].get(f"/api/v1/tickets?house_id={S['house']}")["items"],
        lambda rows: len(rows) == 1,
    )
    assert items[0]["source"] == "max_group"
    S["ticket"] = items[0]["id"]


def test_tc058_me_too_from_group_post(stand: Stand) -> None:
    need("post")
    since = now_ms()
    payload = button(S["post"], "Меня тоже касается")["payload"]
    result = stand.emu(
        "callback",
        "--user",
        str(S["r2"]),
        "--payload",
        payload,
        "--message-id",
        mid(S["post"]),
        "--chat-id",
        str(S["chat"]),
    )
    assert result["status"] == 200
    answer = stand.wait_outbox(since, lambda r: r["kind"] == "answer")
    assert text_of(answer) or answer["body"]


def test_tc035_ticket_cycle_objection_then_confirmed_problem_resolved(stand: Stand) -> None:
    need("ticket")
    tid, r1 = S["ticket"], S["r1"]
    since = now_ms()
    t = ticket(stand, tid)
    t = S["admin"].post(f"/api/v1/tickets/{tid}/accept", {"expected_version": t["version"]})[
        "ticket"
    ]
    edit = stand.wait_outbox(
        since, lambda r: r["kind"] == "edit" and "УК приняла в работу" in text_of(r)
    )
    assert edit
    accepted = stand.wait_outbox(
        since, lambda r: to_user(r1)(r) and "принята в работу" in text_of(r)
    )
    assert accepted
    t = S["admin"].post(f"/api/v1/tickets/{tid}/start", {"expected_version": t["version"]})[
        "ticket"
    ]
    since = now_ms()
    t = S["admin"].post(
        f"/api/v1/tickets/{tid}/work-attempts",
        {"expected_version": t["version"], "public_description": "Заменили реле лифта"},
    )["ticket"]
    assert t["status"] == "verification_pending"
    check = stand.wait_outbox(
        since,
        lambda r: to_user(r1)(r) and "Проблема осталась" in [b.get("text") for b in buttons_of(r)],
    )
    stand.emu(
        "callback",
        "--user",
        str(r1),
        "--payload",
        button(check, "Проблема осталась")["payload"],
        "--message-id",
        mid(check),
    )
    t = wait_for(lambda: ticket(stand, tid), lambda v: v["status"] == "in_progress")
    since = now_ms()
    t = S["admin"].post(
        f"/api/v1/tickets/{tid}/work-attempts",
        {"expected_version": t["version"], "public_description": "Заменили кнопку вызова"},
    )["ticket"]
    again = stand.wait_outbox(
        since, lambda r: to_user(r1)(r) and "Исправлено" in [b.get("text") for b in buttons_of(r)]
    )
    stand.emu(
        "callback",
        "--user",
        str(r1),
        "--payload",
        button(again, "Исправлено")["payload"],
        "--message-id",
        mid(again),
    )
    t = wait_for(lambda: ticket(stand, tid), lambda v: v["status"] == "closed")
    # B-04: проблема закрыта вместе с заявкой и видна жителю в «Решённые за 30 дней».
    resolved = S["r1_web"].get(f"/api/v1/houses/{S['house']}/incidents?state=resolved_recent")[
        "items"
    ]
    mine = [i for i in resolved if i["id"] == t["incident_id"]]
    assert mine and mine[0]["status"] == "resolved" and mine[0]["closure"] == "residents_confirmed"
    opened = S["r1_web"].get(f"/api/v1/houses/{S['house']}/incidents?state=open")["items"]
    assert t["incident_id"] not in [i["id"] for i in opened]


# ---------------------------------------------------------------- личка бота


def test_tc051_bot_commands_help_and_version(stand: Stand) -> None:
    need("binding")
    since = now_ms()
    stand.emu("dm", "--user", str(S["r2"]), "--text", "/help")
    assert "ДомСигнал" in text_of(stand.wait_outbox(since, to_user(S["r2"])))
    since = now_ms()
    stand.emu("dm", "--user", str(S["r2"]), "--text", "/version")
    assert "версия" in text_of(stand.wait_outbox(since, to_user(S["r2"]))).lower()


def test_tc052_dm_problem_in_uk_zone_creates_ticket(stand: Stand) -> None:
    need("binding")
    before = len(S["admin"].get(f"/api/v1/tickets?house_id={S['house']}")["items"])
    since = now_ms()
    stand.emu(
        "dm",
        "--user",
        str(S["r2"]),
        "--text",
        "В третьем подъезде не работает домофон, дверь не открывается",
        "--name",
        "Житель Два",
    )
    reply = stand.wait_outbox(
        since, lambda r: to_user(S["r2"])(r) and "управляющ" in text_of(r).lower()
    )
    assert reply
    items = wait_for(
        lambda: S["admin"].get(f"/api/v1/tickets?house_id={S['house']}")["items"],
        lambda rows: len(rows) == before + 1,
    )
    assert any(i["source"] == "max_dm" for i in items)


# ---------------------------------------------------------------- опасность в группе


def memo(row: dict[str, Any]) -> bool:
    return row["kind"] == "send" and "112" in text_of(row)


def test_tc065_d6_traps_give_no_chat_memo(stand: Stand) -> None:
    need("binding")
    since = now_ms()
    for text in (
        "В доме напротив горит квартира, приехали пожарные",
        "Опять накурили в подъезде, дышать нечем",
    ):
        stand.emu("message", "--chat-id", str(S["chat"]), "--user", str(S["r2"]), "--text", text)
    assert stand.no_outbox(since, lambda r: to_chat(S["chat"])(r) and memo(r), wait=15) == []


def test_tc064_gas_in_group_gives_chat_memo(stand: Stand) -> None:
    need("binding")
    since = now_ms()
    stand.emu(
        "message",
        "--chat-id",
        str(S["chat"]),
        "--user",
        str(S["r1"]),
        "--text",
        "В нашем подъезде пахнет газом",
    )
    row = stand.wait_outbox(since, lambda r: to_chat(S["chat"])(r) and memo(r), timeout=30)
    assert "газ" in text_of(row).lower() or "112" in text_of(row)


# ---------------------------------------------------------------- переписка → сигнал


def test_tc062_neighbours_thread_becomes_signal(stand: Stand) -> None:
    need("binding")
    lines = [
        (S["r1"], "Во втором подъезде опять не горит свет на лестнице"),
        (S["r2"], "Да, между третьим и четвёртым этажом темно"),
        (S["r1"], "Уже третий день так"),
    ]
    for user, text in lines:
        stand.emu("message", "--chat-id", str(S["chat"]), "--user", str(user), "--text", text)
    signals = wait_for(
        lambda: S["admin"].get(f"/api/v1/signals?house_id={S['house']}")["items"],
        lambda rows: any(
            "light" in (s.get("subtype") or "") or "освещ" in str(s).lower() for s in rows
        ),
        timeout=120,
        step=5,
    )
    assert signals
