from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEMO_HOUSE_ID = "00000000-0000-0000-0000-000000000101"
EMPLOYEE = "/api/v1/auth/employee"
SMOKE_LOGIN = "smoke.platform"
SMOKE_PASSWORD = "Smoke platform password 2026!"


def compose(project: str, *args: str, env: dict[str, str]) -> None:
    subprocess.run(
        ["docker", "compose", "-p", project, *args],
        cwd=ROOT,
        env=env,
        check=True,
    )


def request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(
        f"{base_url}{path}", data=payload, headers=request_headers, method=method
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_ready(base_url: str, timeout: int = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if request(base_url, "GET", "/ready")["status"] == "ready":
                return
        except (OSError, urllib.error.URLError, KeyError, json.JSONDecodeError):
            time.sleep(2)
    raise RuntimeError("API did not become ready")


def login(base_url: str) -> str:
    return request(
        base_url,
        "POST",
        "/api/v1/auth/test-session",
        body={"actor": "demo"},
    )["access_token"]


class EmployeeClient:
    """Вход сотрудника так же, как браузер: cookie сессии, `Origin`, CSRF.

    Cookie `__Host-` помечены Secure; браузер отправляет их на
    `http://localhost`, а здесь они переносятся вручную.
    """

    def __init__(self, base_url: str, origin: str) -> None:
        self.base_url = base_url
        self.origin = origin
        self.cookies: dict[str, str] = {}
        self.csrf = ""

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=payload, headers=headers, method=method
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            for header in response.headers.get_all("Set-Cookie") or []:
                name, _, rest = header.partition("=")
                value = rest.split(";", 1)[0]
                if value:
                    self.cookies[name.strip()] = value
                else:
                    self.cookies.pop(name.strip(), None)
            data = json.loads(response.read().decode("utf-8") or "{}")
        if isinstance(data, dict) and data.get("csrf_token"):
            self.csrf = data["csrf_token"]
        return data


def employee_login_with_totp(project: str, base_url: str, origin: str, env: dict[str, str]) -> str:
    """B-01: суперадмин штатной командой → вход в /login с паролем и TOTP."""
    import pyotp

    created = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            project,
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "domsignal.tools.employee_auth",
            "bootstrap-platform",
            "--login-name",
            SMOKE_LOGIN,
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    temporary = json.loads(created.stdout.strip().splitlines()[-1])["temporary_password"]
    client = EmployeeClient(base_url, origin)
    client.call("GET", EMPLOYEE + "/session")
    stage = client.call(
        "POST", EMPLOYEE + "/login", {"login_name": SMOKE_LOGIN, "password": temporary}
    )["stage"]
    if stage != "password_change":
        raise RuntimeError(f"unexpected stage after temporary password: {stage}")
    client.call("POST", EMPLOYEE + "/password/change", {"password": SMOKE_PASSWORD})
    secret = client.call("POST", EMPLOYEE + "/mfa/enroll")["secret"]
    verified = client.call("POST", EMPLOYEE + "/mfa/verify", {"code": pyotp.TOTP(secret).now()})
    if len(verified.get("recovery_codes") or []) != 10:
        raise RuntimeError("recovery codes were not issued")
    session = client.call("GET", EMPLOYEE + "/session")
    if session.get("stage") != "authenticated":
        raise RuntimeError(f"employee is not authenticated: {session.get('stage')}")
    # Второй вход: пароль → код TOTP следующего окна (повтор кода запрещён).
    second = EmployeeClient(base_url, origin)
    second.call("GET", EMPLOYEE + "/session")
    stage = second.call(
        "POST", EMPLOYEE + "/login", {"login_name": SMOKE_LOGIN, "password": SMOKE_PASSWORD}
    )["stage"]
    if stage != "mfa_challenge":
        raise RuntimeError(f"unexpected stage on the second login: {stage}")
    totp = pyotp.TOTP(secret)
    used = totp.now()
    deadline = time.monotonic() + 40
    while totp.now() == used and time.monotonic() < deadline:
        time.sleep(1)
    second.call("POST", EMPLOYEE + "/mfa/challenge", {"code": totp.now()})
    if second.call("GET", EMPLOYEE + "/session").get("stage") != "authenticated":
        raise RuntimeError("second login with TOTP failed")
    return str(session.get("user_id") or "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default=f"domsignal-smoke-{os.getpid()}")
    parser.add_argument("--api-port", default="18080")
    args = parser.parse_args()
    if not re.fullmatch(r"domsignal-(?:smoke|ci)-[a-z0-9-]+", args.project):
        raise ValueError("Smoke project must start with domsignal-smoke- or domsignal-ci-")
    env = {
        **os.environ,
        "API_PORT": args.api_port,
    }
    base_url = f"http://127.0.0.1:{args.api_port}"
    origin = f"http://localhost:{args.api_port}"
    try:
        compose(args.project, "up", "--build", "-d", env=env)
        wait_ready(base_url)
        employee_login_with_totp(args.project, base_url, origin, env)
        print("Employee login with TOTP passed")
        token = login(base_url)
        auth = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": "docker-smoke-0001",
        }
        created = request(
            base_url,
            "POST",
            "/api/v1/reports",
            headers=auth,
            body={
                "house_id": DEMO_HOUSE_ID,
                "category": "lighting",
                "description": "Проверка сохранения после перезапуска контейнера",
                "classification_mode": "manual",
            },
        )
        incident_id = created["incident"]["id"]
        compose(args.project, "restart", "api", env=env)
        wait_ready(base_url)
        token = login(base_url)
        board = request(
            base_url,
            "GET",
            f"/api/v1/houses/{DEMO_HOUSE_ID}/incidents",
            headers={"Authorization": f"Bearer {token}"},
        )
        if incident_id not in {item["id"] for item in board["items"]}:
            raise RuntimeError("Created incident disappeared after API restart")
        print(f"Docker smoke passed; persisted incident {incident_id}")
        return 0
    finally:
        compose(args.project, "down", "-v", "--remove-orphans", env=env)


if __name__ == "__main__":
    raise SystemExit(main())
