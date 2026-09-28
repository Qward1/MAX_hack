"""D6 §2.4: памятки на размеченных реальных окнах — только числа (синтетическая выгрузка)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from domsignal.ai.rules import danger
from evaluation.d5_labeling import build
from evaluation.d6_realdata_memo import run
from tests.unit.test_d5_realdata import MARKERS, telegram, whatsapp_zip


def test_report_has_numbers_only(tmp_path: Path) -> None:
    telegram(tmp_path / "a.json")
    whatsapp_zip(tmp_path / "wa.zip")
    labels = tmp_path / "labeling"
    labels.mkdir()
    sample = build([tmp_path])
    with (labels / "labels.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["window_id", "stratum", "danger_now"])
        writer.writeheader()
        for item in sample:
            writer.writerow(
                {"window_id": item["window_id"], "stratum": item["stratum"], "danger_now": "0"}
            )
    report = run([tmp_path], labels, "HEAD", before_module=danger)
    dumped = json.dumps(report, ensure_ascii=False)
    for marker in (*MARKERS, "лифт не работает", "пахнет газом", "user1"):
        assert marker not in dumped, marker
    assert report["labelled_windows"] == len(sample)
    assert report["before"]["memo_windows"] == report["after"]["memo_windows"] >= 1
    assert report["true_danger_alerts_lost"] == 0
