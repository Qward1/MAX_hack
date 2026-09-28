"""Прогон проверок из DATA-API.yaml против стенда: коды, Content-Type, обязательные поля.

    uv run python scripts/data_api_check.py                      # только проверки без входа
    uv run python scripts/data_api_check.py --accounts accounts.json
    uv run python scripts/data_api_check.py --base-url http://localhost:8000 --accounts …

`accounts.json` — список `{"login", "password", "totp_secret", "role"}` проверочных
учётных записей: формат — шаблон `docs/api/accounts.example.json` с заглушками,
значения — с закрытого служебного слайда (в репозитории их нет); роль
проверки (`operator`, `company_admin`, `platform_admin`) сопоставляется логину по
`DATA-API.yaml` → `accounts`. Вход — как в браузере: сессия → пароль → код TOTP;
между входами одного аккаунта скрипт ждёт новый 30-секундный код. Не удался вход —
проверки этой роли не прошли, остальные выполняются. Проверки, которые меняют
данные, в файле не заявлены. Выход: строка на проверку и итог двумя строками —
«без входа: X из Y» и «с входом по TOTP: X из Y» (`requires_totp` в
`DATA-API.yaml`); код возврата 0 — все обязательные проверки прошли.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import pyotp
import yaml

ROOT = Path(__file__).resolve().parents[1]


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookies: dict[str, str] = {}
        self.csrf = ""

    def call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        body: Any = None,
    ) -> tuple[int, str, Any]:
        url = self.base + path
        if query:
            url += "?" + "&".join(f"{k}={v}" for k, v in query.items())
        sent = {"Origin": self.base, "Accept": "application/json"}
        if body is not None:
            sent["Content-Type"] = "application/json"
        if method != "GET":
            sent["Idempotency-Key"] = str(uuid.uuid4())
        if self.csrf:
            sent["X-CSRF-Token"] = self.csrf
        if self.cookies:
            sent["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        sent.update(headers or {})
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        request = urllib.request.Request(url, data=data, headers=sent, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, ctype = response.status, response.headers.get("Content-Type", "")
                self._cookies(response.headers.get_all("Set-Cookie") or [])
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status, ctype = exc.code, exc.headers.get("Content-Type", "")
            raw = exc.read().decode("utf-8", "replace")
        try:
            value: Any = json.loads(raw)
        except ValueError:
            value = raw
        if isinstance(value, dict) and value.get("csrf_token"):
            self.csrf = value["csrf_token"]
        return status, ctype, value

    def _cookies(self, headers: list[str]) -> None:
        for header in headers:
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if value:
                self.cookies[name.strip()] = value
            else:
                self.cookies.pop(name.strip(), None)


def fresh_code(secret: str, last: dict[str, str]) -> str:
    """Код TOTP, который этот аккаунт ещё не отправлял (повтор кода сервер отвергает)."""
    totp = pyotp.TOTP(secret)
    deadline = time.monotonic() + 35
    while totp.now() == last.get(secret) and time.monotonic() < deadline:
        time.sleep(1)
    last[secret] = totp.now()
    return last[secret]


def login(base: str, account: dict[str, Any], flow: dict[str, Any], last: dict[str, str]) -> Client:
    client = Client(base)
    status, _, value = client.call("GET", flow["session"])
    if status != 200:
        raise RuntimeError(f"session {status}: {value}")
    status, _, value = client.call(
        "POST",
        flow["login"],
        body={"login_name": account["login"], "password": account["password"]},
    )
    if status != 200 or value.get("stage") != "mfa_challenge":
        raise RuntimeError(f"login {status}: {value}")
    code = fresh_code(account["totp_secret"], last)
    status, _, value = client.call("POST", flow["mfa"], body={"code": code})
    if status != 200 or value.get("stage") != "authenticated":
        raise RuntimeError(f"mfa {status}: {value}")
    return client


def field(value: Any, dotted: str) -> bool:
    for part in dotted.split("."):
        if part == "[]":
            if not isinstance(value, list):
                return False
            if not value:
                return True
            value = value[0]
            continue
        if not isinstance(value, dict) or part not in value:
            return False
        value = value[part]
    return True


def summary_lines(results: list[dict[str, Any]]) -> list[str]:
    """Итог двумя строками: проверки без входа и с входом сотрудника по TOTP."""
    lines = []
    for title, totp in (("без входа", False), ("с входом по TOTP", True)):
        group = [r for r in results if r["requires_totp"] is totp]
        passed = sum(r["result"] == "PASS" for r in group)
        failed = sum(r["result"] == "FAIL" for r in group)
        skipped = sum(r["result"] == "SKIP" for r in group)
        line = f"{title}: {passed} из {len(group)}"
        if failed:
            line += f" — не прошли {failed}"
        if skipped:
            line += f" — пропущено {skipped}: нет учётных записей, запустите с --accounts"
        lines.append(line)
    return lines


def substitute(text: str, data: dict[str, Any]) -> str:
    for key, value in data.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--spec", type=Path, default=ROOT / "DATA-API.yaml")
    parser.add_argument("--base-url")
    parser.add_argument("--accounts", type=Path, help="JSON-список проверочных учётных записей")
    parser.add_argument("--report", type=Path, help="сохранить итог в JSON")
    args = parser.parse_args()
    spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
    base = (args.base_url or spec["base_url"]).rstrip("/")
    data = spec.get("test_data", {})
    accounts = json.loads(args.accounts.read_text(encoding="utf-8")) if args.accounts else []
    by_login = {item["login"]: item for item in accounts}
    flow = spec["authentication"]["employee_session"]["endpoints"]
    print(f"{args.spec.name} → {base}")
    sessions: dict[str, Client] = {"anonymous": Client(base)}
    failed_logins: dict[str, str] = {}
    last_codes: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    failed_required = 0
    for check in spec["checks"]:
        role = check.get("role", "anonymous")
        totp = bool(check.get("requires_totp", role != "anonymous"))
        if role not in sessions and role not in failed_logins:
            login_name = spec["accounts"].get(role, {}).get("login")
            account = by_login.get(login_name or "")
            if account is None:
                results.append(
                    {
                        "id": check["id"],
                        "requires_totp": totp,
                        "result": "SKIP",
                        "why": f"нет учётки {role}",
                    }
                )
                print(f"SKIP  {check['id']:<32} нет учётной записи роли {role}")
                continue
            try:
                sessions[role] = login(base, account, flow, last_codes)
            except (RuntimeError, ValueError) as exc:  # ValueError — секрет TOTP не base32
                failed_logins[role] = f"вход {login_name} не удался: {exc}"
        if role in failed_logins:
            if check.get("required", True):
                failed_required += 1
            results.append(
                {
                    "id": check["id"],
                    "role": role,
                    "requires_totp": totp,
                    "result": "FAIL",
                    "problems": [failed_logins[role]],
                }
            )
            print(f"FAIL  {check['id']:<32} {failed_logins[role]}")
            continue
        request = check["request"]
        status, ctype, value = sessions[role].call(
            request["method"],
            substitute(request["path"], data),
            query={k: substitute(str(v), data) for k, v in (request.get("query") or {}).items()},
            headers=request.get("headers"),
            body=request.get("body"),
        )
        expect = check["expect"]
        problems = []
        if status not in expect["status"]:
            problems.append(f"код {status}, ожидался {expect['status']}")
        if expect.get("content_type") and not ctype.startswith(expect["content_type"]):
            problems.append(f"Content-Type {ctype!r}")
        missing = [f for f in expect.get("required_fields", []) if not field(value, f)]
        if missing:
            problems.append(f"нет полей {missing}")
        for key, want in (expect.get("equals") or {}).items():
            got = value
            for part in key.split("."):
                got = got.get(part) if isinstance(got, dict) else None
            if got != want:
                problems.append(f"{key}={got!r}, ожидалось {want!r}")
        verdict = "PASS" if not problems else "FAIL"
        if problems and check.get("required", True):
            failed_required += 1
        results.append(
            {
                "id": check["id"],
                "role": role,
                "requires_totp": totp,
                "status": status,
                "result": verdict,
                "problems": problems,
            }
        )
        print(
            f"{verdict:<5} {check['id']:<32} {request['method']} {request['path']} → {status}"
            + ("" if not problems else "  " + "; ".join(problems))
        )
    summary = summary_lines(results)
    print("\n" + "\n".join(summary))
    if args.report:
        args.report.write_text(
            json.dumps(
                {
                    "base_url": base,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "summary": summary,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if failed_required else 0


if __name__ == "__main__":
    sys.exit(main())
