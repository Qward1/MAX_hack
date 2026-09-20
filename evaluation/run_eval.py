"""Воспроизводимая оценка AI-ядра на синтетических наборах.

    uv run python evaluation/run_eval.py --provider rules --out evaluation/reports/

Сети и PostgreSQL не требуется. Два прогона подряд дают одинаковый JSON,
кроме поля `generated_at`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

if __package__ in (None, ""):  # запуск файлом, а не модулем
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domsignal.ai import WindowAnalyzer  # noqa: E402
from domsignal.ai.providers.fake import FakeProvider  # noqa: E402
from domsignal.ai.rules.lexicon import load_lexicon  # noqa: E402
from domsignal.ai.taxonomy import load_taxonomy  # noqa: E402
from evaluation import metrics  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    DATASETS,
    dataset_card,
    load_jsonl,
)

WARNING = (
    "**СИНТЕТИКА, ВНУТРИВЫБОРОЧНАЯ ОЦЕНКА — ЭТО НЕ ОЦЕНКА КАЧЕСТВА.** "
    "Наборы написаны теми же людьми и агентами, что и правила; реальных "
    "сообщений жителей здесь нет. Числа годятся как порог регрессии и как "
    "ориентир, но не как заявление о работе на реальных домовых чатах."
)

FLOORS: dict[str, str] = {
    "typical_category": "типичный срез: категория ≥ 0,95",
    "typical_role": "типичный срез: роль ≥ 0,95",
    "missed_problems": "пропущено проблем ≤ 8",
    "false_problems": "ложных проблем ≤ 2",
    "emergency_recall": "срез опасности: 10 из 10",
    "gate_recall": "гейт E0b: recall ≥ 64/66",
    "stream_relevant_recall": "поток E0c, вариант C: recall значимых реплик ≥ 0,70",
}


def git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build_analyzer(provider: str) -> WindowAnalyzer:
    if provider == "rules":
        return WindowAnalyzer()
    return WindowAnalyzer(FakeProvider("ok"))


def check_floors(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Полы регрессии определены для режима правил.

    С Fake-провайдером по умолчанию модель отвечает «ничего не нашёл»: такой
    прогон проверяет ветку модели, валидатор и fusion, а не качество разбора,
    поэтому полы к нему не применяются.
    """
    applicable = report["provider"] == "rules"
    singles = report["single_messages"]
    typical = next(
        (item for item in singles["slices"] if item["slice"] == "typical"), None
    )
    total = singles["total"]
    emergency = next(
        (item for item in singles["slices"] if item["slice"] == "emergency"), None
    )
    checks = [
        ("typical_category", (typical or {}).get("category_exact", {}).get("value") or 0, 0.95,
         "ge"),
        ("typical_role", (typical or {}).get("role", {}).get("value") or 0, 0.95, "ge"),
        ("missed_problems", total["missed_problems"]["k"], 8, "le"),
        ("false_problems", total["false_problems"]["k"], 2, "le"),
        ("emergency_recall", (emergency or {}).get("emergency", {}).get("k", 0), 10, "ge"),
        ("gate_recall", total["gate_recall"]["k"], 64, "ge"),
        ("stream_relevant_recall", report["chat_stream"]["relevant_recall"]["value"] or 0,
         0.70, "ge"),
    ]
    result: list[dict[str, Any]] = []
    for name, value, threshold, direction in checks:
        passed = value >= threshold if direction == "ge" else value <= threshold
        result.append(
            {
                "floor": name,
                "description": FLOORS[name],
                "value": value,
                "threshold": threshold,
                "direction": direction,
                "applicable": applicable,
                "passed": bool(passed) or not applicable,
            }
        )
    return result


async def build_report(provider: str) -> dict[str, Any]:
    analyzer = build_analyzer(provider)
    rules_only = WindowAnalyzer()
    singles = load_jsonl(DATASETS / "single_messages.v1.jsonl")
    scope = load_jsonl(DATASETS / "scope_and_danger.v1.jsonl")
    stream = load_jsonl(DATASETS / "chat_stream.v1.jsonl")
    dedup = load_jsonl(DATASETS / "dedup.v1.jsonl")
    taxonomy = load_taxonomy()
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "provider": provider,
        "warning": WARNING,
        "versions": {
            "taxonomy": taxonomy.version,
            "rules": load_lexicon().version,
            "schema": "window_output.v1",
            "prompt": None,
            "model": None,
        },
        "datasets": [
            dataset_card(DATASETS / "single_messages.v1.jsonl", singles).as_dict(),
            dataset_card(DATASETS / "scope_and_danger.v1.jsonl", scope).as_dict(),
            dataset_card(DATASETS / "chat_stream.v1.jsonl", stream).as_dict(),
            dataset_card(DATASETS / "dedup.v1.jsonl", dedup).as_dict(),
        ],
        "single_messages": await metrics.evaluate_singles(analyzer, singles),
        "scope_and_danger": await metrics.evaluate_scope(analyzer, scope),
        "chat_stream": await metrics.evaluate_stream(analyzer, stream),
        "dedup": await metrics.evaluate_dedup(analyzer, rules_only, dedup),
    }
    report["floors"] = check_floors(report)
    return report


def _cell(value: dict[str, Any] | None) -> str:
    if not value or value.get("n") in (0, None):
        return "—"
    if value.get("value") is None:
        return f"{value['k']}/{value['n']}"
    low, high = value["ci95"]
    return f"{value['value']:.2f} ({value['k']}/{value['n']}, ДИ {low:.2f}–{high:.2f})"


def _floor_status(floor: dict[str, Any]) -> str:
    if not floor["applicable"]:
        return "не применяется"
    return "PASS" if floor["passed"] else "FAIL"


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    versions = report["versions"]
    lines.append(
        f"# Оценка AI-ядра — {report['generated_at'][:10]}, "
        f"провайдер `{report['provider']}`"
    )
    lines.append("")
    lines.append(f"> {report['warning']}")
    lines.append("")
    lines.append(f"- Дата прогона: {report['generated_at']}")
    lines.append(f"- Commit: `{report['git_sha']}`")
    lines.append(
        f"- Версии: таксономия `{versions['taxonomy']}`, правила `{versions['rules']}`, "
        f"схема `{versions['schema']}`, промпт `{versions['prompt']}`, модель `{versions['model']}`"
    )
    lines.append("")
    lines.append("## Наборы данных")
    lines.append("")
    lines.append("| Файл | Записей | SHA-256 |")
    lines.append("|---|---|---|")
    for card in report["datasets"]:
        lines.append(f"| `{card['file']}` | {card['records']} | `{card['sha256'][:32]}…` |")
    lines.append("")

    lines.append("## Одиночные сообщения (окно из одной реплики)")
    lines.append("")
    lines.append(
        "| Срез | n | Роль | Категория точно | Категория ∩ | Подтип | Пропущено | Ложных | "
        "Опасность | Подъезд |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    rows = [*report["single_messages"]["slices"], report["single_messages"]["total"]]
    for row in rows:
        emergency = row["emergency"]
        entrance = row["entrance"]
        lines.append(
            f"| {row['slice']} | {row['n']} | {_cell(row['role'])} | "
            f"{_cell(row['category_exact'])} | {_cell(row['category_any'])} | "
            f"{_cell(row['subtype_known'])} | "
            f"{row['missed_problems']['k']}/{row['missed_problems']['n']} | "
            f"{row['false_problems']['k']}/{row['false_problems']['n']} | "
            f"{emergency['k']}/{emergency['n']} (ложных {emergency['false_alarms']}) | "
            f"{entrance['k']}/{entrance['n']} (лишних {entrance['invented']}) |"
        )
    lines.append("")
    total = report["single_messages"]["total"]
    lines.append(f"Recall-гейт E0b на проблемах: {_cell(total['gate_recall'])}.")
    lines.append("")

    scope = report["scope_and_danger"]
    lines.append("## Территория и внешние подтипы (набор агента P1)")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---|---|")
    lines.append(f"| Роль | {_cell(scope['messages']['role'])} |")
    lines.append(f"| `location_scope` | {_cell(scope['messages']['location_scope'])} |")
    lines.append(f"| Подтип точно | {_cell(scope['subtype_exact'])} |")
    lines.append(
        f"| Пропущено проблем | {scope['messages']['missed_problems']['k']}"
        f"/{scope['messages']['missed_problems']['n']} |"
    )
    lines.append("")
    lines.append(
        "Окна с контекстной опасностью: правила их ловить не обязаны — они нужны для "
        "проверки fusion с моделью и для набора P6."
    )
    lines.append("")
    lines.append(
        "| Окно | Ожидаемая семантическая опасность | Правила нашли опасность | Сигналов |"
    )
    lines.append("|---|---|---|---|")
    for item in scope["contextual_windows"]:
        lines.append(
            f"| {item['id']} | {item['expected_semantic_danger']} | "
            f"{'да' if item['rules_found_danger'] else 'нет'} | {item['signals']} |"
        )
    lines.append("")

    stream = report["chat_stream"]
    lines.append("## Поток чата (E0c, 63 реплики, нарезка windowing.py)")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---|---|")
    lines.append(f"| Окон | {stream['windows']} на {stream['lines']} реплик |")
    lines.append(f"| Сигналов | {stream['signals']} |")
    lines.append(f"| Recall значимых реплик | {_cell(stream['relevant_recall'])} |")
    lines.append(
        f"| Лишних реплик | {stream['extra_lines']['k']}/{stream['extra_lines']['n']} |"
    )
    lines.append(f"| Recall инцидентов | {_cell(stream['incident_recall'])} |")
    lines.append(f"| Доля потока в Inbox | {_cell(stream['inbox_share'])} |")
    lines.append(f"| Доля потока в Audit Pool | {_cell(stream['audit_pool_share'])} |")
    lines.append("")

    dedup = report["dedup"]
    lines.append("## Привязка к открытым элементам (10 инцидентов, 22 запроса)")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---|---|")
    lines.append(f"| Верных привязок | {_cell(dedup['correct_joins'])} |")
    lines.append(f"| Привязок не к тому элементу | {dedup['wrong_target']} |")
    lines.append(f"| Не привязано, хотя надо было | {dedup['missed_joins']} |")
    lines.append(
        f"| Ложных привязок новых проблем | {dedup['false_joins']['k']}"
        f"/{dedup['false_joins']['n']} |"
    )
    lines.append("")
    lines.append(
        "Правила привязывают реплику к открытому элементу только когда он единственный "
        "того же подтипа и нет конфликта подъезда. Это сознательно осторожно: урок E0 — "
        "текстовое сходство непригодно для решения о совпадении."
    )
    lines.append("")

    lines.append("## Регрессионные полы")
    lines.append("")
    if report["provider"] != "rules":
        lines.append(
            "Прогон с Fake-провайдером проверяет ветку модели, валидатор и fusion. "
            "Fake по умолчанию отвечает «ничего не нашёл», поэтому полы регрессии "
            "к этому прогону не применяются."
        )
        lines.append("")
    lines.append("| Пол | Значение | Порог | Итог |")
    lines.append("|---|---|---|---|")
    for floor in report["floors"]:
        sign = "≥" if floor["direction"] == "ge" else "≤"
        value = floor["value"]
        shown = f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(
            f"| {floor['description']} | {shown} | {sign} {floor['threshold']} | "
            f"{_floor_status(floor)} |"
        )
    lines.append("")

    errors = report["single_messages"]["errors"]
    if errors:
        lines.append("## Ошибки на одиночных сообщениях")
        lines.append("")
        for item in errors:
            lines.append(
                f"- `{item['id']}` «{item['text']}» — ожидалось {item['expected']}, "
                f"получено {item['got']}"
            )
        lines.append("")
    scope_errors = report["scope_and_danger"]["errors"]
    if scope_errors:
        lines.append("## Ошибки на наборе территории")
        lines.append("")
        for item in scope_errors:
            lines.append(
                f"- `{item['id']}` «{item['text']}» — ожидалось {item['expected']}, "
                f"получено {item['got']}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Оценка AI-ядра ДомСигнала")
    parser.add_argument("--provider", choices=["rules", "fake"], default="rules")
    parser.add_argument("--out", default="evaluation/reports/")
    arguments = parser.parse_args()

    report = asyncio.run(build_report(arguments.provider))
    out_dir = pathlib.Path(arguments.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['generated_at'][:10]}-{arguments.provider}-{report['versions']['rules']}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    md_path.write_text(render_markdown(report), encoding="utf-8", newline="\n")
    failed = [floor for floor in report["floors"] if not floor["passed"]]
    print(f"report: {md_path}")
    print(f"report: {json_path}")
    for floor in report["floors"]:
        sign = ">=" if floor["direction"] == "ge" else "<="
        status = "PASS" if floor["passed"] else "FAIL"
        if not floor["applicable"]:
            status = "SKIP"
        print(f"  {status}  {floor['floor']} = {floor['value']} ({sign} {floor['threshold']})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
