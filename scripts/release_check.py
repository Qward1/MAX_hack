"""Проверка выпуска перед строкой на служебном слайде (F1 §5.8, `docs/RELEASE.md`).

    uv run python scripts/release_check.py [--fetch] [--base-url https://…] [--since <tag|sha>]

Проверяет: рабочее дерево чистое; `HEAD` = `origin/main`; `/version` production =
`HEAD`; `/ready`; вебхук без секрета → 401; OpenAPI из кода = `docs/openapi.json`;
gitleaks по коммитам с прошлого выпуска (`--since`, по умолчанию — последний тег
`online-submission-*`). Печатает строку для служебного слайда. Секретов не читает
и не печатает; production — только чтение.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = "https://domsignal.176-108-244-168.sslip.io"
REPO = "https://github.com/Qward1/MAX_hack"
GITLEAKS_IMAGE = "zricethezav/gitleaks:v8.28.0"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8", check=True
    ).stdout.strip()


def http(method: str, url: str, body: bytes | None = None) -> tuple[int, str]:
    request = urllib.request.Request(
        url, data=body, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, str(exc)


def gitleaks(since: str | None, head: str) -> tuple[bool, str]:
    log_opts = f"{since}..{head}" if since else f"-1 {head}"
    # В рабочем дереве (`git worktree`) история лежит в общем каталоге основного
    # репозитория: сканируем его, диапазон задан явными SHA.
    repo = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    binary = shutil.which("gitleaks")
    if binary:
        command = [
            binary,
            "git",
            "--no-banner",
            "--no-color",
            "--redact",
            f"--log-opts={log_opts}",
            str(repo),
        ]
    elif shutil.which("docker"):
        command = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{repo}:/repo",
            GITLEAKS_IMAGE,
            "git",
            "--no-banner",
            "--no-color",
            "--redact",
            f"--log-opts={log_opts}",
            "/repo",
        ]
    else:
        return False, "gitleaks не найден (ни программы, ни Docker)"
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
    lines = (result.stderr + result.stdout).splitlines()
    scanned = next(
        (line.split("INF", 1)[-1].strip() for line in lines if "commits scanned" in line), ""
    )
    verdict = next(
        (line.split("INF", 1)[-1].strip() for line in lines if "leaks found" in line), ""
    )
    ok = result.returncode == 0 and not scanned.startswith("0 commits")
    return ok, f"{log_opts[:30]}: {scanned or '?'} {verdict}".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=PROD)
    parser.add_argument("--fetch", action="store_true", help="git fetch origin перед сравнением")
    parser.add_argument("--since", default=None, help="тег или коммит прошлого выпуска")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    checks: list[tuple[str, bool, str]] = []

    if args.fetch:
        git("fetch", "--quiet", "origin")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    checks.append(("Рабочее дерево чистое", not dirty, "есть изменения" if dirty else "да"))
    head = git("rev-parse", "HEAD")
    try:
        origin = git("rev-parse", "origin/main")
    except subprocess.CalledProcessError:
        origin = ""
    checks.append(("HEAD = origin/main", head == origin, f"{head[:7]} / {origin[:7] or '—'}"))

    status, body = http("GET", f"{base}/version")
    commit = json.loads(body).get("commit", "") if status == 200 and body.startswith("{") else ""
    same = bool(commit) and (head.startswith(commit) or commit.startswith(head))
    detail = commit[:7] if commit else f"HTTP {status}"
    if commit and not same:
        # После выкладки в main могут прийти только документы: код образа тот же.
        try:
            changed = git("diff", "--name-only", commit, head).splitlines()
        except subprocess.CalledProcessError:
            changed = ["?"]
        docs_only = bool(changed) and all(
            path.startswith(("docs/", "evaluation/reports/")) or path.endswith(".md")
            for path in changed
        )
        if docs_only:
            same = True
            detail = f"{commit[:7]}; после него только документы ({len(changed)} файлов)"
    checks.append(("/version = HEAD", same, detail))
    status, body = http("GET", f"{base}/ready")
    ready = status == 200 and '"ready"' in body
    checks.append(("/ready", ready, body[:40] if status == 200 else f"HTTP {status}"))
    status, _ = http("POST", f"{base}/max/webhook", b"{}")
    checks.append(("Вебхук без секрета → 401", status == 401, f"HTTP {status}"))

    exported = subprocess.run(
        ["uv", "run", "python", "scripts/export_openapi.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    checks.append(
        (
            "OpenAPI = docs/openapi.json",
            exported.returncode == 0,
            "совпадает" if exported.returncode == 0 else "расходится",
        )
    )

    since = args.since
    if since is None:
        tags = git("tag", "--list", "online-submission-*", "--sort=-creatordate").splitlines()
        since = tags[0] if tags and git("rev-parse", tags[0]) != head else None
        if since is None and origin and origin != head:
            since = origin
    clean, detail = gitleaks(since, head)
    checks.append(("gitleaks по новым коммитам", clean, detail))

    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print(f"{'OK  ' if ok else 'FAIL'} {name.ljust(width)}  {detail}")
    date = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"\nСлужебный слайд: {REPO} · commit {head[:7]} · {date} МСК")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
