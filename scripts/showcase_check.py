"""Ежедневная самопроверка витрины жюри (F1 §5.5) — для uptime.yml.

    SHOWCASE_URL=https://… SHOWCASE_CHECK_TOKEN=… python3 scripts/showcase_check.py

Спрашивает у production `/api/v1/showcase/health` (только да/нет по
инвариантам: УК активна, квота покрывает чаты, управление домом действует,
открытый доступ включён, демо-чат подключён и читается, бот в чате,
проверочные аккаунты не отозваны и в штате) и печатает таблицу. Нарушен хотя
бы один инвариант — код выхода 1; workflow открывает issue. Как восстановить
каждый инвариант — `docs/RELEASE.md`, «Витрина жюри». Только стандартная
библиотека: запускается на чистом раннере.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

LABELS = {
    "showcase_marked": "витрина отмечена (УК «Пилотная, 7»)",
    "company_active": "УК витрины активна",
    "quota_covers_chats": "квота не меньше подключённых чатов",
    "house_managed": "управление демо-домом действует",
    "open_access_on": "открытый доступ к демо-дому включён",
    "chat_active": "демо-чат подключён",
    "chat_reading_on": "чтение демо-чата включено",
    "bot_in_chat": "бот в демо-чате (MAX API)",
    "reviewers_present": "проверочные аккаунты есть",
    "reviewers_not_revoked": "вход проверочных аккаунтов не отозван",
    "reviewer_staff_active": "проверочные аккаунты в штате УК витрины",
}


def main() -> int:
    url = os.environ.get("SHOWCASE_URL", "https://domsignal.176-108-244-168.sslip.io").rstrip("/")
    token = os.environ.get("SHOWCASE_CHECK_TOKEN", "")
    if not token:
        print("SHOWCASE_CHECK_TOKEN не задан — проверка пропущена")
        return 0
    request = urllib.request.Request(
        f"{url}/api/v1/showcase/health", headers={"X-Showcase-Check-Token": token}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"showcase health: HTTP {exc.code}")
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"showcase health: нет ответа ({type(exc).__name__})")
        return 1
    checks = data.get("checks", {})
    for key, value in checks.items():
        print(f"{'OK  ' if value else 'FAIL'} {LABELS.get(key, key)}")
    broken = [LABELS.get(key, key) for key, value in checks.items() if not value]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("### Витрина жюри\n\n")
            out.writelines(
                f"- {'✅' if v else '❌'} {LABELS.get(k, k)}\n" for k, v in checks.items()
            )
    if broken:
        print("Нарушено: " + "; ".join(broken))
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
