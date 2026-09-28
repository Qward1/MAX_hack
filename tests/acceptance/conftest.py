"""Приёмочные кейсы на работающем локальном стенде (F1 §3.3).

Стенд — `docker compose up --build` в режиме эмулятора MAX:

    MAX_TRANSPORT=record PASSIVE_CAPTURE_ENABLED=true docker compose up --build -d
    ACCEPTANCE_BASE_URL=http://127.0.0.1:8000 uv run pytest tests/acceptance

Тесты ходят в стенд как люди и MAX: публичные страницы и кабинеты — по HTTP с
cookie, CSRF и `Idempotency-Key`; события MAX — через `scripts/max_emulator.py`
внутри контейнера `api` (там общий с воркерами каталог двойника MAX API);
служебные команды — `python -m domsignal.tools.*` в том же контейнере. Коды TOTP
считает `pyotp`. Без `ACCEPTANCE_BASE_URL` кейсы пропускаются.

`ACCEPTANCE_EXEC` задаёт, как выполнить команду на стенде: по умолчанию
`docker compose exec -T api`; для стенда без Docker — `local` (команда
запускается здесь же, с `MAX_RECORD_DIR` и `DATABASE_URL` из окружения).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pyotp
import pytest

ROOT = Path(__file__).resolve().parents[2]
EMPLOYEE = "/api/v1/auth/employee"
PASSWORD = "Acceptance staff password 2026!"


class Problem(Exception):
    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"{status}: {body}")
        self.status = status
        self.body = body

    @property
    def code(self) -> str | None:
        return self.body.get("code") if isinstance(self.body, dict) else None


class Web:
    """HTTP-клиент как браузер: cookie `__Host-` переносятся вручную, CSRF и Origin."""

    def __init__(self, base: str, bearer: str | None = None) -> None:
        self.base = base
        # Origin — публичный адрес стенда (PUBLIC_BASE_URL): в compose это localhost.
        self.origin = os.getenv("ACCEPTANCE_ORIGIN") or base.replace("127.0.0.1", "localhost")
        self.bearer = bearer
        self.cookies: dict[str, str] = {}
        self.csrf = ""

    def call(self, method: str, path: str, body: Any = None, *, expect: int | None = None) -> Any:
        headers = {"Content-Type": "application/json", "Origin": self.origin}
        if method != "GET":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                self._cookies(response.headers.get_all("Set-Cookie") or [])
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read().decode("utf-8", "replace")
        value: Any = json.loads(raw) if raw.strip().startswith(("{", "[")) else raw
        if isinstance(value, dict) and value.get("csrf_token"):
            self.csrf = value["csrf_token"]
        if expect is not None and status != expect:
            raise Problem(status, value)
        if expect is None and status >= 400:
            raise Problem(status, value)
        return value

    def _cookies(self, headers: list[str]) -> None:
        for header in headers:
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if value:
                self.cookies[name.strip()] = value
            else:
                self.cookies.pop(name.strip(), None)

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self.call("POST", path, {} if body is None else body, **kw)


class Stand:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        mode = os.getenv("ACCEPTANCE_EXEC", "docker")
        self.prefix = (
            []
            if mode == "local"
            else shlex.split(mode)
            if mode != "docker"
            else ["docker", "compose", "exec", "-T", "api"]
        )
        self.local = mode == "local"
        self.run_id = uuid.uuid4().hex[:6]

    # ------------------------------------------------------------ команды на стенде
    def exec(self, *args: str) -> str:
        """Команда на стенде; `args` начинаются с `python`."""
        command = [sys.executable, *args[1:]] if self.local else [*self.prefix, *args]
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=120,
        )
        if result.returncode not in (0, 1) and not result.stdout.strip():
            raise RuntimeError(f"{' '.join(command)}: {result.stderr[-500:]}")
        return result.stdout.strip()

    def tool(self, module: str, *args: str) -> dict[str, Any]:
        out = self.exec("python", "-m", module, *args)
        return json.loads(out[out.index("{") :])

    def emu(self, *args: str) -> Any:
        # В контейнере эмулятор ходит в API по адресу по умолчанию (127.0.0.1:8000).
        base = ["--base-url", self.base] if self.local else []
        out = self.exec("python", "scripts/max_emulator.py", *base, *args)
        if args and args[0] == "outbox":
            return [json.loads(line) for line in out.splitlines() if line.strip()]
        return json.loads(out.splitlines()[-1]) if out else None

    def outbox(self, since: int) -> list[dict[str, Any]]:
        return self.emu("outbox", "--json", "--since-ms", str(since))

    def wait_outbox(
        self, since: int, match: Callable[[dict[str, Any]], bool], timeout: float = 60
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        seen: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            seen = self.outbox(since)
            for row in seen:
                if match(row):
                    return row
            time.sleep(2)
        texts = [text_of(row)[:120] for row in seen]
        raise AssertionError(f"бот не отправил ожидаемое за {timeout} с; отправлено: {texts}")

    def no_outbox(
        self, since: int, match: Callable[[dict[str, Any]], bool], wait: float
    ) -> list[dict[str, Any]]:
        time.sleep(wait)
        return [row for row in self.outbox(since) if match(row)]

    # ------------------------------------------------------------ люди
    def public(self) -> Web:
        return Web(self.base)

    def employee(self, login: str, password: str, secret: str) -> Web:
        web = Web(self.base)
        web.get(EMPLOYEE + "/session")
        stage = web.post(EMPLOYEE + "/login", {"login_name": login, "password": password})["stage"]
        assert stage == "mfa_challenge", stage
        web.post(EMPLOYEE + "/mfa/challenge", {"code": next_code(secret)})
        assert web.get(EMPLOYEE + "/session")["stage"] == "authenticated"
        return web

    def resident(self, user_id: int, name: str, start_param: str | None = None) -> Web:
        args = ["webapp", "--user", str(user_id), "--name", name, "--show-token"]
        if start_param:
            args += ["--start-param", start_param]
        result = self.emu(*args)
        assert result and result.get("status") == 200, result
        return Web(self.base, bearer=result["token"])


def next_code(secret: str) -> str:
    """Код следующего окна TOTP: повтор кода защита входа не принимает."""
    totp = pyotp.TOTP(secret)
    used = totp.now()
    deadline = time.monotonic() + 40
    while totp.now() == used and time.monotonic() < deadline:
        time.sleep(1)
    return totp.now()


def text_of(row: dict[str, Any]) -> str:
    body = row.get("body") or {}
    return str(body.get("text") or body.get("notification") or "")


def buttons_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    body = row.get("body") or {}
    return [
        button
        for attachment in body.get("attachments", []) or []
        for line in (attachment.get("payload", {}) or {}).get("buttons", []) or []
        for button in line
    ]


def to_user(user_id: int) -> Callable[[dict[str, Any]], bool]:
    return lambda row: (
        row.get("kind") == "send" and str(row["params"].get("user_id")) == str(user_id)
    )


def to_chat(chat_id: int) -> Callable[[dict[str, Any]], bool]:
    return lambda row: str(row["params"].get("chat_id")) == str(chat_id)


def now_ms() -> int:
    return int(time.time() * 1000)


@pytest.fixture(scope="session")
def stand() -> Iterator[Stand]:
    base = os.getenv("ACCEPTANCE_BASE_URL")
    if not base:
        pytest.skip("ACCEPTANCE_BASE_URL не задан: приёмочные кейсы идут на работающем стенде")
    s = Stand(base)
    ready = s.public().get("/ready")
    assert ready.get("status") == "ready", ready
    yield s
