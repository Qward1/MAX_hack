"""D6 §2.4: памятки и оповещения правил на размеченных реальных окнах — до и после.

    uv run python evaluation/d6_realdata_memo.py <выгрузки...> --dir data/labeling \
        --before-ref 9932f80 --out evaluation/reports/2026-09-28-d6-realdata-memo.json

**Приватность.** Скрипт запускается только локально. Он читает исходные
выгрузки из `data/` и `labels.csv` (id окна и метки), но **не выводит и не
записывает ни одного текста** — только числа с интервалами Уилсона. Модели
и внешние API тексты не получают. Тест `tests/unit/test_d6_realdata_memo.py`
проверяет, что в выводе нет текста реплик.

Окна режутся правилами «до» (`--before-ref`): так id окон совпадают с
разметкой D5 (опасность закрывает окно, и новые правила сдвинули бы границы).
На тех же окнах считаются памятка (`chat_memo_hits`) и оповещение оператора
по правилам «до» и по текущим.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Callable, Sequence
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domsignal.ai.rules import danger as current  # noqa: E402
from evaluation.d5_labeling import build, flag, read_labels, wilson  # noqa: E402
from evaluation.rules_ref import load_danger  # noqa: E402


def window_facts(texts: Sequence[str], danger: Any) -> dict[str, bool]:
    memo = alert = active = False
    for text in texts:
        hits = danger.screen_message_for_danger(text)
        memo = memo or bool(danger.chat_memo_hits(hits))
        alert = alert or any(not hit.negated for hit in hits)
        active = active or any(not hit.negated and not hit.displaced for hit in hits)
    return {"memo": memo, "alert": alert, "active": active}


def summarize(
    items: Sequence[dict[str, Any]],
    labels: dict[str, dict[str, str]],
    key: str,
) -> dict[str, Any]:
    def count(predicate: Callable[[dict[str, Any]], bool]) -> int:
        return sum(1 for item in items if predicate(item))

    def danger_now(item: dict[str, Any]) -> bool:
        return flag(labels[item["window_id"]], "danger_now")

    memo = [item for item in items if item[key]["memo"]]
    active = [item for item in items if item[key]["active"]]
    alert = [item for item in items if item[key]["alert"]]
    return {
        "memo_windows": len(memo),
        "memo_false_share": wilson(
            count(lambda i: i[key]["memo"] and not danger_now(i)), len(memo)
        ),
        "memo_true": count(lambda i: i[key]["memo"] and danger_now(i)),
        "alert_windows_excluding_displaced": len(active),
        "alert_false_share_excluding_displaced": wilson(
            count(lambda i: i[key]["active"] and not danger_now(i)), len(active)
        ),
        "alert_windows_product": len(alert),
        "alert_false_share_product": wilson(
            count(lambda i: i[key]["alert"] and not danger_now(i)), len(alert)
        ),
        "alert_true_product": count(lambda i: i[key]["alert"] and danger_now(i)),
    }


def run(
    paths: Sequence[pathlib.Path],
    directory: pathlib.Path,
    before_ref: str,
    *,
    before_module: Any = None,
) -> dict[str, Any]:
    before = before_module or load_danger(before_ref)
    original = current.screen_message_for_danger
    # Окна — правилами «до», чтобы id совпали с разметкой D5.
    current.screen_message_for_danger = before.screen_message_for_danger  # type: ignore[assignment]
    try:
        sample = build(paths)
    finally:
        current.screen_message_for_danger = original  # type: ignore[assignment]
    labels = read_labels(directory / "labels.csv")
    items: list[dict[str, Any]] = []
    for item in sample:
        if item["window_id"] not in labels:
            continue
        messages = item["_messages"]
        texts = [messages[index].text for index in item["_window"]]
        items.append(
            {
                "window_id": item["window_id"],
                "before": window_facts(texts, before),
                "after": window_facts(texts, current),
            }
        )

    def danger_now(item: dict[str, Any]) -> bool:
        return flag(labels[item["window_id"]], "danger_now")

    kept = sum(1 for i in items if i["before"]["memo"] and danger_now(i) and i["after"]["memo"])
    lost_memo = sum(
        1 for i in items if i["before"]["memo"] and danger_now(i) and not i["after"]["memo"]
    )
    lost_alert = sum(
        1 for i in items if i["before"]["alert"] and danger_now(i) and not i["after"]["alert"]
    )
    return {
        "label": (
            "разметка ИИ-агентом по маскированным текстам (D5), не людьми; окна — правилами "
            f"до D6 ({before_ref}); тексты не выводятся"
        ),
        "labelled_windows": len(items),
        "danger_now_windows": sum(1 for i in items if danger_now(i)),
        "before": summarize(items, labels, "before"),
        "after": summarize(items, labels, "after"),
        "true_memos_kept": kept,
        "true_memos_lost": lost_memo,
        "true_danger_alerts_lost": lost_alert,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="D6 memo precision on labelled real windows")
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    parser.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("data/labeling"))
    parser.add_argument("--before-ref", default="9932f80")
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    body = run(args.paths, args.dir, args.before_ref)
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(text.encode("utf-8"))
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
