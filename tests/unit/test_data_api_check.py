"""F2 §4: DATA-API.yaml помечает проверки с TOTP, раннер печатает итог двумя строками."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import data_api_check  # noqa: E402

sys.path.remove(str(ROOT / "scripts"))

SPEC = yaml.safe_load((ROOT / "DATA-API.yaml").read_text(encoding="utf-8"))


def test_every_staff_check_is_marked_requires_totp_and_stays_required() -> None:
    checks = SPEC["checks"]
    staff = [c for c in checks if c["role"] != "anonymous"]
    assert all(c.get("requires_totp") is True for c in staff)
    assert not any(c.get("requires_totp") for c in checks if c["role"] == "anonymous")
    assert all(c["required"] is True for c in checks)
    notes = SPEC["automation_notes"]
    assert notes["checks_total"] == len(checks) == 24
    assert notes["requires_totp"] == len(staff) == 12
    assert notes["without_login"] == len(checks) - len(staff)
    assert f"{len(staff)} из {len(checks)}" in notes["summary"]


def test_accounts_template_has_only_placeholders() -> None:
    template = json.loads((ROOT / "docs/api/accounts.example.json").read_text(encoding="utf-8"))
    logins = {
        SPEC["accounts"][role]["login"] for role in ("operator", "company_admin", "platform_admin")
    }
    assert {item["login"] for item in template} == logins
    for item in template:
        assert item["password"].startswith("<") and item["password"].endswith(">")
        assert item["totp_secret"].startswith("<") and item["totp_secret"].endswith(">")


def test_summary_is_two_lines_split_by_login() -> None:
    results = (
        [{"requires_totp": False, "result": "PASS"}] * 12
        + [{"requires_totp": True, "result": "PASS"}] * 10
        + [{"requires_totp": True, "result": "FAIL"}] * 2
    )
    assert data_api_check.summary_lines(results) == [
        "без входа: 12 из 12",
        "с входом по TOTP: 10 из 12 — не прошли 2",
    ]


def answer_from_spec(path: str, body: Any) -> tuple[int, str, Any]:
    """Ответ стенда, который удовлетворяет проверке без входа с этим запросом."""
    check = next(
        c
        for c in SPEC["checks"]
        if c["role"] == "anonymous"
        and c["request"]["path"] == path
        and c["request"].get("body") == body
    )
    expect = check["expect"]
    answer: dict[str, Any] = {}
    for dotted in expect.get("required_fields", []):
        node = answer
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node.setdefault(leaf, "x")
    for dotted, value in (expect.get("equals") or {}).items():
        node = answer
        *parents, leaf = dotted.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return expect["status"][0], expect["content_type"], answer


def fake_stand(monkeypatch: pytest.MonkeyPatch) -> None:
    def call(
        self: Any, method: str, path: str, *, body: Any = None, **_: Any
    ) -> tuple[int, str, Any]:
        return answer_from_spec(path, body)

    monkeypatch.setattr(data_api_check.Client, "call", call)


def run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str
) -> tuple[int, list[str]]:
    monkeypatch.setattr(sys, "argv", ["data_api_check.py", *args])
    code = data_api_check.main()
    return code, capsys.readouterr().out.strip().splitlines()


def test_without_accounts_only_anonymous_checks_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_stand(monkeypatch)
    code, lines = run(monkeypatch, capsys)
    assert lines[-2:] == [
        "без входа: 12 из 12",
        "с входом по TOTP: 0 из 12 — пропущено 12: нет учётных записей, запустите с --accounts",
    ]
    assert code == 0


def test_failed_login_is_reported_as_fail_not_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fake_stand(monkeypatch)
    attempts: list[str] = []

    def login(
        base: str, account: dict[str, Any], flow: dict[str, Any], last: dict[str, str]
    ) -> Any:
        attempts.append(account["login"])
        raise RuntimeError("login 401: неверный логин или пароль")

    monkeypatch.setattr(data_api_check, "login", login)
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        (ROOT / "docs/api/accounts.example.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    code, lines = run(monkeypatch, capsys, "--accounts", str(accounts))
    assert lines[-2:] == ["без входа: 12 из 12", "с входом по TOTP: 0 из 12 — не прошли 12"]
    assert sorted(attempts) == ["jury.admin", "jury.operator", "jury.platform"]  # по входу на роль
    assert code == 1
