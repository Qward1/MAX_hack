"""D5 §2: агрегаты реальных выгрузок — только числа (проверка на синтетической выгрузке)."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evaluation.d5_realdata import load_chats, run

MARKERS = ("Синтетикаальфа", "Синтетикабета", "Автор Приметный")


def telegram(path: Path, *, days: int = 3) -> None:
    start = datetime(2026, 9, 1, 18, 0, tzinfo=UTC)
    messages = []
    for index in range(days * 12):
        at = start + timedelta(hours=index * 2, seconds=index % 7 * 9)
        text = (
            "В подъезде сильно пахнет газом"
            if index == 5
            else f"{MARKERS[index % 2]} лифт не работает во втором подъезде {index}"
        )
        messages.append(
            {
                "id": index,
                "type": "message",
                "date": at.isoformat(),
                "date_unixtime": str(int(at.timestamp())),
                "from": MARKERS[2],
                "from_id": f"user{index % 3}",
                "text": text,
            }
        )
    path.write_text(json.dumps({"name": MARKERS[2], "messages": messages}), encoding="utf-8")


def whatsapp_zip(path: Path) -> None:
    lines = [
        f"01.09.2026, 1{hour}:0{minute} - {MARKERS[2]}: {MARKERS[0]} нет горячей воды {hour}"
        for hour in range(5)
        for minute in range(3)
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("_chat.txt", "\n".join(lines))


def test_output_is_numbers_only_and_reexports_are_counted_once(tmp_path: Path) -> None:
    telegram(tmp_path / "a.json")
    telegram(tmp_path / "b.json")  # повторный экспорт того же чата
    whatsapp_zip(tmp_path / "wa.zip")
    chats, dedupe = load_chats([tmp_path])
    assert dedupe == {"exports_read": 3, "same_chat_reexports_skipped": 1, "chats": 2}
    assert len(chats) == 2
    report, profile, _ = run([tmp_path])
    dumped = json.dumps(report, ensure_ascii=False) + json.dumps(profile, ensure_ascii=False)
    for marker in (*MARKERS, "лифт не работает", "пахнет газом", "user1"):
        assert marker not in dumped, marker
    busy = report["chats"][0]
    assert busy["windows"]["policy"]["silence_seconds"] == 30
    assert busy["rules"]["danger_per_1000"]["active"] > 0
    assert sum(profile["hourly_share"]) > 0.99
