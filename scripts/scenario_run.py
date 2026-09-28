"""Сквозные сценарии продукта на локальном стенде — таблица PASS/FAIL по шагам (D5 §7).

    DATABASE_URL=postgresql+asyncpg://.../domsignal_scenarios \\
      uv run python scripts/scenario_run.py --out scenario-run.json

Стенд — тот же, что у PostgreSQL-тестов: API приложения через ASGI, своя БД,
MAX — записывающий двойник (сообщения, посты, правки не уходят наружу),
модель — фейковый провайдер или правила. Каждый шаг сценария — сквозной
тест, который проходит этот шаг через HTTP API и воркер; время шага — время
теста. Скрипт отказывается работать с APP_ENV=production и с БД,
в имени которой есть «prod».
"""

# Таблица сценариев — данные: длинные строки узлов pytest не переносятся.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IT = "tests/integration/"

#: Сценарий → шаги: (описание шага, узел pytest).
SCENARIOS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "1. Личка: «Попробовать» → открытый дом → карточка маршрута → черновик → «Я отправил»",
        [
            (
                "без дома бот предлагает открытые дома",
                f"{IT}test_d1_personal_bot.py::test_a_user_without_houses_is_offered_the_open_ones",
            ),
            (
                "«Попробовать» → выбор дома → карточка маршрута",
                f"{IT}test_d1_personal_bot.py::test_an_example_button_leads_a_stranger_to_the_route_card_in_one_tap",
            ),
            (
                "черновик обращения из проверенных данных и слов жителя",
                f"{IT}test_appeal_drafts.py::test_draft_is_composed_from_verified_data_and_the_residents_words",
            ),
            (
                "«Я отправил» — только отметка жителя",
                f"{IT}test_appeal_drafts.py::test_mark_filed_records_only_the_residents_assertion",
            ),
        ],
    ),
    (
        "2. Групповой /report → заявка → принятие → отчёт исполнителя → подтверждение → закрытие; «не устранено» → тот же T-N",
        [
            (
                "/report в зоне УК создаёт заявку",
                f"{IT}test_explicit_reports.py::test_uk_zone_with_a_confident_location_creates_a_ticket",
            ),
            (
                "бот отвечает в группе один раз",
                f"{IT}test_d1_personal_bot.py::test_a_group_report_without_a_dialog_is_answered_in_the_group_once",
            ),
            (
                "принятие → отчёт → «не устранено» → доработка той же заявки",
                f"{IT}test_tickets.py::test_tk02_lifecycle_late_objection_rework_and_stale",
            ),
            (
                "подтверждение жителем и закрытие",
                f"{IT}test_tickets.py::test_tk05_self_verification_and_participation",
            ),
        ],
    ),
    (
        "3. Ветка реплик → сигнал → «Создать заявку» → пост в чате → правка того же сообщения → «Меня тоже касается»",
        [
            (
                "ветка из 7 реплик — один сигнал",
                f"{IT}test_passive_signals.py::test_a_thread_of_seven_lines_is_one_signal_with_growing_counters",
            ),
            (
                "«Создать заявку» из сигнала с цитатами",
                f"{IT}test_signal_inbox.py::test_create_ticket_uses_the_quotes_and_the_employee_context",
            ),
            (
                "пост о заявке в чате",
                f"{IT}test_d3_ticket_chat.py::test_an_operator_ticket_from_a_signal_posts_the_status",
            ),
            (
                "смена статуса правит то же сообщение",
                f"{IT}test_d3_ticket_chat.py::test_status_changes_edit_the_same_message",
            ),
            (
                "«Меня тоже касается»",
                f"{IT}test_d3_ticket_chat.py::test_me_too_joins_counts_and_notifies_personally",
            ),
        ],
    ),
    (
        "4. Опасность → оповещение и памятка без модели; модель выключена → правила",
        [
            (
                "газ: памятка в чат и оповещение оператора",
                f"{IT}test_p6b_chat_memo.py::test_gas_gives_the_memo_and_the_alert",
            ),
            (
                "учения и благодарность — без памятки",
                f"{IT}test_p6b_chat_memo.py::test_a_drill_and_thanks_give_no_signal_and_no_memo",
            ),
            (
                "остановленный пул модели — окно разбирают правила",
                f"{IT}test_window_fallback.py::test_a_stopped_ai_pool_is_covered_by_the_rules_watchdog",
            ),
            (
                "провайдер недоступен — правила",
                f"{IT}test_passive_signals.py::test_an_unavailable_provider_falls_back_to_rules",
            ),
            (
                "опасность уходит раньше рассылки на 1 000 чатов",
                f"{IT}test_d5_queue.py::test_danger_goes_before_a_broadcast_to_a_thousand_chats",
            ),
        ],
    ),
    (
        "5. Заявка УК → одобрение с квотой → дома пачкой с регионом → подключение чата → лимит → расширение",
        [
            (
                "одобрение с квотой, администратор создаёт себя сам",
                f"{IT}test_d2_company_signup.py::test_approval_with_smaller_quota_and_self_service_admin",
            ),
            (
                "адреса заявки УК → заявки на дома → одобрение пачкой",
                f"{IT}test_d5_bulk_houses.py::test_addresses_of_an_approved_company_application_become_house_requests",
            ),
            (
                "список адресов → одобрение пачкой с регионом",
                f"{IT}test_d5_bulk_houses.py::test_admin_pastes_a_list_and_platform_approves_it_in_one_action",
            ),
            (
                "подключение чата показывает остаток квоты",
                f"{IT}test_d2_chat_quota.py::test_quota_view_on_initiate_shows_remaining",
            ),
            (
                "лимит: гонка за последний слот",
                f"{IT}test_d2_chat_quota.py::test_race_for_the_last_slot_activates_exactly_one",
            ),
            (
                "расширение квоты",
                f"{IT}test_d2_company_signup.py::test_expansion_request_partial_approval_and_permissions",
            ),
        ],
    ),
    (
        "6. Рассылка → предпросмотр → доставка → отписка",
        [
            (
                "черновик → предпросмотр → доставка → статистика",
                f"{IT}test_d3_mailings.py::test_announcement_from_draft_to_statistics",
            ),
            (
                "кнопка «Не получать рассылки»",
                f"{IT}test_d3_mailings.py::test_the_unsubscribe_button_opts_out_without_replacing_the_message",
            ),
            (
                "отписавшиеся пропущены и посчитаны",
                f"{IT}test_d3_mailings.py::test_unsubscribed_residents_are_skipped_and_counted",
            ),
        ],
    ),
    (
        "7. Опрос → голос → итог правкой того же сообщения",
        [
            (
                "опрос в чате с кнопкой «Голосовать»",
                f"{IT}test_d3_polls.py::test_a_poll_goes_to_the_chat_with_a_vote_button_and_a_disclaimer",
            ),
            (
                "один голос на человека",
                f"{IT}test_d3_polls.py::test_one_vote_per_person_can_change_until_closed",
            ),
            (
                "закрытие правит тот же пост",
                f"{IT}test_d3_polls.py::test_closing_edits_immediately_and_refuses_new_votes",
            ),
        ],
    ),
    (
        "8. Вход и выход из чата → доступ появляется и пропадает",
        [
            (
                "участник получает дом, вышедший теряет",
                f"{IT}test_d1_chat_membership.py::test_a_chat_member_gets_the_house_and_a_leaver_loses_it",
            ),
            (
                "отозванная привязка сразу закрывает доступ",
                f"{IT}test_d1_chat_membership.py::test_a_revoked_binding_stops_chat_membership",
            ),
        ],
    ),
    (
        "9. Открытый доступ вкл/выкл",
        [
            (
                "вкл — постороннему открыт дом, выкл — доступ закрыт",
                f"{IT}test_d1_open_access.py::test_open_access_lets_an_outsider_in_and_closing_it_stops_access",
            ),
        ],
    ),
    (
        "10. Московский дом → «Наш город»; владивостокский → тихие часы по местному времени",
        [
            (
                "дом RU-MOW → «Наш город»",
                f"{IT}test_d4_house_region.py::test_moscow_house_approved_with_its_region_routes_to_nash_gorod",
            ),
            (
                "владивостокский дом: пост ждёт утра по местному времени",
                f"{IT}test_d4_region_time.py::test_the_chat_post_waits_for_the_morning_of_the_house_zone[RU-PRI-vladivostok-until0]",
            ),
            (
                "московский дом: в то же время пост уходит сразу",
                f"{IT}test_d4_region_time.py::test_the_chat_post_waits_for_the_morning_of_the_house_zone[RU-MOW-moscow-None]",
            ),
        ],
    ),
]


def junit_results(path: Path) -> dict[str, tuple[str, float]]:
    """Узел pytest → (исход, секунды) по отчёту JUnit."""
    results: dict[str, tuple[str, float]] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        module = case.get("classname", "").replace(".", "/") + ".py"
        node = f"{module}::{case.get('name')}"
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        results[node] = (
            "SKIP" if skipped else "FAIL" if failed else "PASS",
            float(case.get("time", 0)),
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    database = os.environ.get("DATABASE_URL", "")
    if os.environ.get("APP_ENV") == "production" or "prod" in database or not database:
        print("Сценарии только на своей тестовой БД (DATABASE_URL)", file=sys.stderr)
        return 2
    # F-12: новая БД — сначала миграции; не вышло — понятная подсказка, а не
    # 36 упавших шагов.
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if migrated.returncode != 0:
        print(
            "Не удалось применить миграции к DATABASE_URL (alembic upgrade head). "
            "Проверьте, что PostgreSQL запущена и БД существует. "
            + migrated.stderr[-2000:],
            file=sys.stderr,
        )
        return 2
    nodes = [node for _, steps in SCENARIOS for _, node in steps]
    with tempfile.TemporaryDirectory() as temp:
        report = Path(temp) / "junit.xml"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={report}",
                *nodes,
            ],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
        )
        results = junit_results(report)
    table = []
    lines = ["| Сценарий | Шаг | Итог | Время, с |", "|---|---|---|---|"]
    for scenario, steps in SCENARIOS:
        for title, node in steps:
            outcome, seconds = results.get(node, ("NOT RUN", 0.0))
            table.append(
                {
                    "scenario": scenario,
                    "step": title,
                    "node": node,
                    "outcome": outcome,
                    "seconds": round(seconds, 2),
                }
            )
            lines.append(f"| {scenario.split('.')[0]} | {title} | {outcome} | {seconds:.2f} |")
    passed = sum(1 for row in table if row["outcome"] == "PASS")
    summary = {"steps": len(table), "passed": passed, "rows": table}
    text = "\n".join(lines) + f"\n\nИтог: {passed} из {len(table)} шагов PASS\n"
    sys.stdout.buffer.write(text.encode("utf-8"))
    if args.out:
        args.out.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0 if passed == len(table) else 1


if __name__ == "__main__":
    raise SystemExit(main())
