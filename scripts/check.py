from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def run(*command: str, cwd: Path = ROOT) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def run_with_retry(*command: str, attempts: int = 5, delay_seconds: float = 1.0) -> None:
    for attempt in range(1, attempts + 1):
        print("+", " ".join(command), f"(attempt {attempt}/{attempts})", flush=True)
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode == 0:
            return
        if attempt < attempts:
            time.sleep(delay_seconds)
    raise subprocess.CalledProcessError(result.returncode, command)


def wait_for_database_port(timeout_seconds: int = 30) -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for integration checks")
    parsed = urlparse(database_url)
    if not parsed.hostname:
        raise RuntimeError("DATABASE_URL has no hostname")
    port = parsed.port or 5432
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((parsed.hostname, port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"PostgreSQL port {parsed.hostname}:{port} did not become ready")


def npm() -> str:
    executable = shutil.which("npm") or shutil.which("npm.cmd")
    if not executable:
        raise RuntimeError("npm is not installed")
    return executable


def backend() -> None:
    run("uv", "run", "ruff", "check", "src", "tests", "scripts", "migrations", "evaluation")
    run("uv", "run", "mypy", "src/domsignal")
    run("uv", "run", "pytest", "tests/unit", "tests/contract", "tests/ai")


def frontend() -> None:
    run(npm(), "run", "typecheck", cwd=ROOT / "miniapp")
    run(npm(), "run", "test", "--", "--run", cwd=ROOT / "miniapp")
    run(npm(), "run", "build", cwd=ROOT / "miniapp")


def contracts() -> None:
    run("uv", "run", "python", "scripts/export_openapi.py", "--check")
    run("uv", "run", "python", "scripts/validate_region_pack.py")
    with tempfile.TemporaryDirectory(prefix="domsignal-contract-") as temp_dir:
        generated = Path(temp_dir) / "schema.ts"
        run(
            npm(),
            "exec",
            "openapi-typescript",
            "--",
            "../docs/openapi.json",
            "-o",
            str(generated),
            cwd=ROOT / "miniapp",
        )
        committed = ROOT / "miniapp" / "src" / "shared" / "api" / "schema.ts"
        if generated.read_text(encoding="utf-8") != committed.read_text(encoding="utf-8"):
            raise RuntimeError("Generated TypeScript API is stale; run npm run api:generate")


def integration() -> None:
    wait_for_database_port()
    run_with_retry("uv", "run", "alembic", "upgrade", "head")
    run("uv", "run", "pytest", "tests/integration")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DomSignal quality checks")
    parser.add_argument(
        "--scope",
        choices=["backend", "frontend", "contracts", "integration", "all"],
        default="all",
    )
    scope = parser.parse_args().scope
    actions = {
        "backend": backend,
        "frontend": frontend,
        "contracts": contracts,
        "integration": integration,
    }
    selected = list(actions) if scope == "all" else [scope]
    try:
        for name in selected:
            actions[name]()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
