"""Прогон приёмочных кейсов (F1 §3.4) — журнал PASS/FAIL по кейсам.

    uv run python scripts/acceptance_run.py --target prod-readonly --expect-commit <sha>
    uv run python scripts/acceptance_run.py --target local

Результат — `output/acceptance/<время>/report.json` и `report.md`.

* `prod-readonly` — production только на чтение: служебные адреса, 401 без
  входа, закрытые локальные режимы, публичные страницы; при `--jury-file`
  (приватный JSON вне git) — вход проверочными аккаунтами с TOTP и чтение их
  разделов. Ничего не создаёт и не меняет, кроме пробного входа.
* `local` — тот же коммит на локальном стенде: тесты, указанные в
  `docs/qa/ACCEPTANCE_MATRIX.md` (колонка «Чем проверяется»), — pytest
  (`tests/unit`, `tests/integration`, `tests/acceptance` на работающем стенде с
  эмулятором MAX) и Playwright (`miniapp/tests`). Тест указан файлом или узлом
  `файл::тест`; кейс проходит, если прошли все его тесты. Кейсы `human-MAX`
  получают отметку HUMAN и результат своей автоматической части.

  Базы разные: `ACCEPTANCE_PYTEST_DATABASE_URL` — для `tests/integration`,
  `ACCEPTANCE_BROWSER_DATABASE_URL` — для фикстур Playwright (стенд
  `PLAYWRIGHT_BASE_URL`); `ACCEPTANCE_BASE_URL` — стенд `tests/acceptance`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROD = "https://domsignal.176-108-244-168.sslip.io"


@dataclass
class CaseResult:
    case: str
    title: str
    result: str  # PASS | FAIL | SKIP
    evidence: list[str] = field(default_factory=list)
    seconds: float = 0.0


def http(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
) -> tuple[int, str, dict[str, str]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.read().decode("utf-8", "replace"),
                dict(response.headers),
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), dict(exc.headers or {})


class Checks:
    def __init__(self) -> None:
        self.results: list[CaseResult] = []

    def case(self, case: str, title: str, steps: list[tuple[str, bool]], started: float) -> None:
        ok = all(passed for _, passed in steps)
        self.results.append(
            CaseResult(
                case,
                title,
                "PASS" if ok else "FAIL",
                [f"{'✓' if passed else '✗'} {step}" for step, passed in steps],
                round(time.monotonic() - started, 2),
            )
        )


def prod_readonly(base: str, expect_commit: str | None, jury_file: Path | None) -> list[CaseResult]:
    checks = Checks()
    started = time.monotonic()
    status, body, _ = http("GET", f"{base}/ready")
    ready = status == 200 and '"ready"' in body
    status, body, _ = http("GET", f"{base}/version")
    version = json.loads(body) if status == 200 else {}
    commit = str(version.get("commit", ""))
    steps = [
        ("/ready = ready", ready),
        (f"/version отвечает, commit {commit[:7] or '—'}", status == 200 and bool(commit)),
        ("пакеты регионов в /version", bool(version.get("region_packs"))),
    ]
    if expect_commit:
        steps.append((f"commit = ожидаемому {expect_commit[:7]}", commit.startswith(expect_commit)))
    checks.case("TC-001 / ПР-01", "Служебные адреса отвечают, версия совпадает", steps, started)

    started = time.monotonic()
    protected = [
        "/api/v1/me",
        "/api/v1/tickets",
        "/api/v1/signals",
        "/api/v1/admin/bootstrap",
        "/api/v1/platform/bootstrap",
        "/api/v1/platform/company-applications",
    ]
    steps = []
    for path in protected:
        code, _, _ = http("GET", base + path)
        steps.append((f"GET {path} без входа → {code}", code == 401))
    code, _, _ = http("POST", f"{base}/max/webhook", body={})
    steps.append((f"вебхук без секрета → {code}", code == 401))
    code, _, _ = http(
        "POST", f"{base}/max/webhook", body={}, headers={"X-Max-Bot-Api-Secret": "wrong"}
    )
    steps.append((f"вебхук с неверным секретом → {code}", code == 401))
    code, _, _ = http("POST", f"{base}/api/v1/auth/test-session", body={"actor": "demo"})
    steps.append((f"тестовый вход выключен → {code}", code in (403, 404, 503)))
    code, _, _ = http("POST", f"{base}/max/replay", body={})
    steps.append((f"replay выключен или закрыт → {code}", code in (401, 403, 404, 503)))
    checks.case(
        "TC-002 / ПР-02", "Без входа данные недоступны, локальные режимы закрыты", steps, started
    )

    started = time.monotonic()
    steps = []
    for path, marker in [
        ("/", '<div id="root"'),
        ("/site", "og:image"),
        ("/login", '<div id="root"'),
        ("/company/apply", '<div id="root"'),
        ("/privacy", "Qwen3-30B-A3B"),
        ("/favicon.svg", "<svg"),
        ("/og.png", ""),
    ]:
        code, body, _ = http("GET", base + path)
        steps.append(
            (
                f"GET {path} → {code}{' и содержит ' + marker if marker else ''}",
                code == 200 and (not marker or marker in body),
            )
        )
    checks.case(
        "TC-003",
        "Публичные страницы открываются: лендинг, вход, заявка УК, политика данных",
        steps,
        started,
    )

    if jury_file and jury_file.exists():
        checks.results.extend(jury_logins(base, json.loads(jury_file.read_text(encoding="utf-8"))))
    else:
        checks.results.append(
            CaseResult(
                "§5.5",
                "Вход проверочными аккаунтами жюри",
                "SKIP",
                ["нет --jury-file: аккаунты жюри не проверялись"],
            )
        )
    return checks.results


def jury_logins(base: str, accounts: list[dict[str, Any]]) -> list[CaseResult]:
    """Вход каждым аккаунтом: пароль → TOTP → чтение разделов → выход. Данные не меняются.

    Клиент — как у `docker_smoke.py`: cookie сессии, `Origin`, CSRF. Код TOTP
    одного окна второй раз не принимается, поэтому между аккаунтами с общим
    секретом ждём следующее окно.
    """
    import pyotp  # зависимость проекта

    sys.path.insert(0, str(ROOT / "scripts"))
    from docker_smoke import EMPLOYEE, EmployeeClient

    results: list[CaseResult] = []
    for account in accounts:
        started = time.monotonic()
        steps: list[tuple[str, bool]] = []
        client = EmployeeClient(base, base)

        def call(
            method: str,
            path: str,
            body: dict[str, Any] | None = None,
            client: EmployeeClient = client,
        ) -> tuple[int, Any]:
            try:
                return 200, client.call(method, path, body)
            except urllib.error.HTTPError as exc:
                return exc.code, None

        call("GET", EMPLOYEE + "/session")
        code, login = call(
            "POST",
            EMPLOYEE + "/login",
            {"login_name": account["login"], "password": account["password"]},
        )
        stage = login.get("stage") if isinstance(login, dict) else None
        steps.append((f"пароль → {code}, этап {stage}", code == 200 and stage == "mfa_challenge"))
        if stage == "mfa_challenge":
            code, _ = call(
                "POST",
                EMPLOYEE + "/mfa/challenge",
                {"code": pyotp.TOTP(account["totp_secret"]).now()},
            )
            code, session = call("GET", EMPLOYEE + "/session")
            steps.append(
                (
                    "код TOTP → вход выполнен",
                    isinstance(session, dict) and session.get("stage") == "authenticated",
                )
            )
        for path in account.get("read", []):
            code, _ = call("GET", path)
            steps.append((f"GET {path} → {code}", code == 200))
        code, _ = call("POST", EMPLOYEE + "/logout", {})
        steps.append((f"выход → {code}", code == 200))
        ok = all(passed for _, passed in steps)
        results.append(
            CaseResult(
                f"§5.5 {account['role']}",
                f"Вход {account['login']}",
                "PASS" if ok else "FAIL",
                [f"{'✓' if p else '✗'} {s}" for s, p in steps],
                round(time.monotonic() - started, 2),
            )
        )
    return results


def local(matrix: Path, out: Path) -> list[CaseResult]:
    """Тесты, привязанные к кейсам в матрице, и результат по каждому кейсу."""
    rows = parse_matrix(matrix)
    results: list[CaseResult] = []
    runnable = [row for row in rows if row["class"] in {"auto-local", "auto-prod", "human-MAX"}]
    py_nodes = sorted({t for row in runnable for t in row["tests"] if t.startswith("tests/")})
    pw_specs = sorted({t for row in runnable for t in row["tests"] if t.startswith("miniapp/")})
    outcomes: dict[str, tuple[str, float]] = {}
    if py_nodes:
        outcomes.update(run_pytest(py_nodes))
    if pw_specs:
        outcomes.update(run_playwright(pw_specs, out))
    for row in rows:
        if row["class"] == "N/A" or not row["tests"]:
            results.append(CaseResult(row["case"], row["title"], "N/A", []))
            continue
        found = [(node, outcomes.get(node, ("NOT RUN", 0.0))) for node in row["tests"]]
        ok = all(result == "PASS" for _, (result, _) in found)
        verdict = "PASS" if ok else "FAIL"
        if row["class"] == "human-MAX":
            verdict = "HUMAN" if ok else "FAIL"
        results.append(
            CaseResult(
                row["case"],
                row["title"],
                verdict,
                [f"{result} {node}" for node, (result, _) in found],
                round(sum(seconds for _, (_, seconds) in found), 2),
            )
        )
    return results


def parse_matrix(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or not re.match(r"^(TC|ПР)-\d+", cells[0]):
            continue
        tests = re.findall(r"`([^`]+)`", cells[3])
        rows.append(
            {"case": cells[0], "title": cells[1], "class": cells[2].strip("* "), "tests": tests}
        )
    return rows


def run_pytest(nodes: list[str]) -> dict[str, tuple[str, float]]:
    """Узлы и файлы pytest; у файла — FAIL, если упал хоть один тест, SKIP — если все пропущены."""
    report = ROOT / "output" / "acceptance" / "pytest.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if os.getenv("ACCEPTANCE_PYTEST_DATABASE_URL"):
        env["DATABASE_URL"] = os.environ["ACCEPTANCE_PYTEST_DATABASE_URL"]
    subprocess.run(
        ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={report}", *nodes],
        cwd=ROOT,
        env=env,
        check=False,
    )
    outcomes: dict[str, tuple[str, float]] = {}
    files: dict[str, list[tuple[str, float]]] = {}
    for case in ET.parse(report).getroot().iter("testcase"):
        path = case.get("classname", "").replace(".", "/") + ".py"
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        outcome = ("FAIL" if failed else "SKIP" if skipped else "PASS", float(case.get("time", 0)))
        outcomes[f"{path}::{case.get('name')}"] = outcome
        files.setdefault(path, []).append(outcome)
    for path, items in files.items():
        states = {state for state, _ in items}
        state = "FAIL" if "FAIL" in states else "PASS" if "PASS" in states else "SKIP"
        outcomes[path] = (state, round(sum(seconds for _, seconds in items), 2))
    return outcomes


def run_playwright(specs: list[str], out: Path) -> dict[str, tuple[str, float]]:
    report = ROOT / "output" / "acceptance" / "playwright.json"
    env = dict(os.environ, PLAYWRIGHT_JSON_OUTPUT_NAME=str(report))
    if os.getenv("ACCEPTANCE_BROWSER_DATABASE_URL"):
        env["DATABASE_URL"] = os.environ["ACCEPTANCE_BROWSER_DATABASE_URL"]
    results_dir = out / "playwright"
    rel = [spec.removeprefix("miniapp/") for spec in specs]
    npx = "npx.cmd" if os.name == "nt" else "npx"
    subprocess.run(
        [npx, "playwright", "test", "--reporter=json", f"--output={results_dir}", *rel],
        cwd=ROOT / "miniapp",
        env=env,
        check=False,
    )
    outcomes: dict[str, tuple[str, float]] = {}
    if not report.exists():
        return outcomes
    data = json.loads(report.read_text(encoding="utf-8"))

    def walk(suite: dict[str, Any]) -> None:
        for spec in suite.get("specs", []):
            file = "miniapp/tests/" + spec.get("file", "").replace("\\", "/")
            statuses = [
                result.get("status")
                for test in spec.get("tests", [])
                for result in test.get("results", [])
            ]
            seconds = (
                sum(
                    result.get("duration", 0)
                    for test in spec.get("tests", [])
                    for result in test.get("results", [])
                )
                / 1000
            )
            status = (
                "PASS"
                if statuses and all(s == "passed" for s in statuses)
                else "SKIP"
                if statuses and all(s == "skipped" for s in statuses)
                else "FAIL"
            )
            previous = outcomes.get(file)
            if previous is None or previous[0] == "PASS":
                outcomes[file] = (status, seconds + (previous[1] if previous else 0))
        for child in suite.get("suites", []):
            walk(child)

    for suite in data.get("suites", []):
        walk(suite)
    return outcomes


def write_report(target: str, results: list[CaseResult], out: Path, meta: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        **meta,
        "target": target,
        "results": [asdict(r) for r in results],
        "summary": {
            k: sum(r.result == k for r in results) for k in ("PASS", "FAIL", "SKIP", "HUMAN", "N/A")
        },
    }
    (out / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    lines = [
        f"# Приёмочный прогон — {target}",
        "",
        f"Время: {meta['started']}. Коммит: `{meta.get('commit') or '—'}`.",
        f"Адрес: {meta.get('base_url') or '—'}.",
        "",
        "Итог: " + ", ".join(f"{key} {value}" for key, value in payload["summary"].items()) + ".",
        "",
        "| Кейс | Что | Результат | Шаги и тесты |",
        "|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.case} | {r.title} | **{r.result}** | {'<br>'.join(r.evidence)} |")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target", choices=["local", "prod-readonly"], required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--expect-commit", default=None)
    parser.add_argument(
        "--jury-file", type=Path, default=None, help="приватный JSON аккаунтов жюри (вне git)"
    )
    parser.add_argument(
        "--matrix", type=Path, default=ROOT / "docs" / "qa" / "ACCEPTANCE_MATRIX.md"
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    started = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out = args.out or ROOT / "output" / "acceptance" / f"{started}-{args.target}"
    if args.target == "prod-readonly":
        base = (args.base_url or PROD).rstrip("/")
        results = prod_readonly(base, args.expect_commit, args.jury_file)
        commit = json.loads(http("GET", f"{base}/version")[1] or "{}").get("commit")
    else:
        base = args.base_url or "local"
        results = local(args.matrix, out)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
    write_report(
        args.target, results, out, {"started": started, "commit": commit, "base_url": base}
    )
    failed = [r for r in results if r.result == "FAIL"]
    counts = {
        k: sum(r.result == k for r in results) for k in ("PASS", "FAIL", "SKIP", "HUMAN", "N/A")
    }
    print(f"{args.target}: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v) + f" → {out}")
    for r in failed:
        bad = [e for e in r.evidence if e.startswith(("✗", "FAIL", "NOT RUN"))]
        print(f"FAIL {r.case}: {'; '.join(bad)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
