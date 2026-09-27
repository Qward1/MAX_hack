"""D6: памятки и оповещения правил на наборах настройки — без модели и без сети.

    uv run python evaluation/d6_memo_eval.py [--out evaluation/reports/<файл>.json]

Считает по `d5_dev` и `open_danger_dev` (наборы настройки; контроль D5 и
holdout D3 здесь не читаются — handoff §9): для каждой строки — было ли
оповещение оператора (срабатывание без отрицания) и памятка в чат
(`chat_memo_hits`). Печатает только числа и id строк, тексты реплик не
выводятся.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domsignal.ai.rules import danger as current_danger  # noqa: E402
from evaluation.guard import load_allowed_jsonl  # noqa: E402
from evaluation.rules_ref import load_danger  # noqa: E402

DATASETS = {
    "d5_dev": pathlib.Path("datasets/synthetic/d5_dev.v1.jsonl"),
    "open_danger_dev": pathlib.Path("datasets/synthetic/open_danger_dev.v1.jsonl"),
}


def row_facts(row: dict[str, Any], danger: Any) -> tuple[bool, bool]:
    alert = memo = False
    for line in row.get("lines", []):
        hits = danger.screen_message_for_danger(line["text"])
        # Как в продукте: предварительный критический сигнал и оповещение —
        # на любое срабатывание без отрицания, «не у нас» тоже (без памятки).
        alert = alert or any(not hit.negated for hit in hits)
        memo = memo or bool(danger.chat_memo_hits(hits))
    return alert, memo


def evaluate(ref: str | None = None) -> dict[str, Any]:
    danger = load_danger(ref) if ref else current_danger
    report: dict[str, Any] = {
        "label": "правила без модели, наборы настройки",
        "rules": ref or "рабочее дерево",
    }
    for name, path in DATASETS.items():
        rows = load_allowed_jsonl(path)
        families: dict[str, dict[str, int]] = defaultdict(
            lambda: {"rows": 0, "alert": 0, "memo": 0}
        )
        trap_memo: list[str] = []
        danger_missed: list[str] = []
        for row in rows:
            alert, memo = row_facts(row, danger)
            key = f"{row.get('group')}/{row.get('family')}"
            entry = families[key]
            entry["rows"] += 1
            entry["alert"] += int(alert)
            entry["memo"] += int(memo)
            if row.get("group") == "trap" and memo:
                trap_memo.append(row["id"])
            if row.get("expected_danger") and not alert:
                danger_missed.append(row["id"])
        groups: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "alert": 0, "memo": 0})
        for key, entry in families.items():
            group = key.split("/")[0]
            for field in ("rows", "alert", "memo"):
                groups[group][field] += entry[field]
        report[name] = {
            "rows": len(rows),
            "groups": dict(groups),
            "families": dict(sorted(families.items())),
            "trap_memo_ids": trap_memo,
            "expected_danger_without_alert_ids": danger_missed,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--rules-ref", help="ревизия git с правилами «до», например 9932f80")
    args = parser.parse_args()
    text = json.dumps(evaluate(args.rules_ref), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(text.encode("utf-8"))
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
