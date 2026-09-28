"""Первый вход проверочного аккаунта жюри — штатным путём продукта (F1 §5.5.2).

Аккаунты создаёт `python -m domsignal.tools.showcase` (на сервере) и печатает
временный пароль. Этот скрипт проходит первый вход через `/login` так же, как
человек: временный пароль → свой пароль → TOTP → коды восстановления. После
него проверяющему не нужно менять пароль или заново подключать TOTP.

    uv run python scripts/jury_setup.py --base-url https://… --login jury.admin
        --role "Администратор УК" --temporary-file tmp.json --out <PRIVATE>/jury.admin.json
    uv run python scripts/jury_setup.py --base-url https://… --check-file <PRIVATE>/jury.admin.json

Секреты (пароль, TOTP, коды восстановления) пишутся только в `--out` —
приватная папка вне git — и никогда не печатаются. `--check-file` входит
готовым аккаунтом (пароль + код TOTP следующего окна) и выходит.
"""

from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
import time
from pathlib import Path
from typing import Any

import pyotp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docker_smoke import EMPLOYEE, EmployeeClient  # noqa: E402


def strong_password() -> str:
    alphabet = string.ascii_letters + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(18))
    return f"{body[:6]}-{body[6:12]}-{body[12:]}"


def next_code(secret: str) -> str:
    """Код следующего 30-секундного окна: повтор кода защита не принимает."""
    totp = pyotp.TOTP(secret)
    used = totp.now()
    deadline = time.monotonic() + 40
    while totp.now() == used and time.monotonic() < deadline:
        time.sleep(1)
    return totp.now()


def complete_first_login(base: str, login_name: str, temporary: str) -> dict[str, Any]:
    client = EmployeeClient(base, base)
    client.call("GET", EMPLOYEE + "/session")
    login = {"login_name": login_name, "password": temporary}
    stage = client.call("POST", EMPLOYEE + "/login", login)["stage"]
    if stage != "password_change":
        raise SystemExit(f"{login_name}: unexpected stage {stage}")
    password = strong_password()
    client.call("POST", EMPLOYEE + "/password/change", {"password": password})
    secret = client.call("POST", EMPLOYEE + "/mfa/enroll")["secret"]
    verified = client.call("POST", EMPLOYEE + "/mfa/verify", {"code": pyotp.TOTP(secret).now()})
    if client.call("GET", EMPLOYEE + "/session").get("stage") != "authenticated":
        raise SystemExit(f"{login_name}: first login did not finish")
    client.call("POST", EMPLOYEE + "/logout", {})
    return {
        "login": login_name,
        "password": password,
        "totp_secret": secret,
        "recovery_codes": verified.get("recovery_codes") or [],
    }


def check(base: str, account: dict[str, Any]) -> None:
    client = EmployeeClient(base, base)
    client.call("GET", EMPLOYEE + "/session")
    login = {"login_name": account["login"], "password": account["password"]}
    stage = client.call("POST", EMPLOYEE + "/login", login)["stage"]
    if stage != "mfa_challenge":
        raise SystemExit(f"{account['login']}: unexpected stage {stage}")
    client.call("POST", EMPLOYEE + "/mfa/challenge", {"code": next_code(account["totp_secret"])})
    if client.call("GET", EMPLOYEE + "/session").get("stage") != "authenticated":
        raise SystemExit(f"{account['login']}: login with TOTP failed")
    client.call("POST", EMPLOYEE + "/logout", {})


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--login")
    parser.add_argument("--role", default="")
    parser.add_argument("--temporary-file", type=Path, help="JSON инструмента showcase")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check-file", type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    if args.check_file:
        account = json.loads(args.check_file.read_text(encoding="utf-8"))
        check(base, account)
        print(json.dumps({"login_ok": account["login"]}, ensure_ascii=False))
        return 0
    if not (args.login and args.temporary_file and args.out):
        raise SystemExit("--login, --temporary-file and --out are required")
    created = json.loads(args.temporary_file.read_text(encoding="utf-8"))
    account = complete_first_login(base, args.login, created["temporary_password"])
    account.update(role=args.role, user_id=created.get("user_id"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(account, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"completed": args.login}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
