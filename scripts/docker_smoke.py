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
    try:
        compose(args.project, "up", "--build", "-d", env=env)
        wait_ready(base_url)
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
