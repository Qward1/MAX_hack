"""D2: выгрузка «игрового чата» → строки формата D3 для `evaluation/p6_eval.py`.

    uv run python evaluation/d2_convert.py export.jsonl aliases.json \
        --out datasets/synthetic/d2_dialogs.v1.jsonl

- `export.jsonl` — read-only выгрузка реплик сессии из буфера production (её
  делает DEV-B в P7b по согласию участников): одна строка на реплику, поля
  `session`, `mid`, `sent_at` (ISO 8601), `author` (псевдоним буфера),
  `reply_to` (`mid` или `null`), `text`, `synthetic: true`,
  `origin: "d2_roleplay"`.
- `aliases.json` — соответствие псевдонима буфера участнику `P01…P12` по
  сессиям: `{"S1": {"A": "P01", …}}`. Ведёт ведущий сессии; в git не кладётся.

k-я реплика участника сопоставляется с его k-й карточкой по времени
(`datasets/d2/truth.v1.jsonl`). Лишние реплики остаются без эталонной роли и
без инцидента; карточка без реплики считается невыполненной и в оценку не
входит. Одна сессия — один диалог.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

TRUTH_FILE = pathlib.Path("datasets/d2/truth.v1.jsonl")
AUTHOR = "D2: реплики добровольцев по карточкам, разметка — таблица правды карточек"


def load_truth(path: pathlib.Path = TRUTH_FILE) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    incidents: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        if "card" in row:
            cards.append(row)
        else:
            incidents[row["incident"]] = row
    return cards, incidents


def convert(
    export: Sequence[dict[str, Any]],
    aliases: dict[str, dict[str, str]],
    cards: Sequence[dict[str, Any]],
    incidents: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for session in sorted({item["session"] for item in export}):
        messages = sorted(
            (item for item in export if item["session"] == session),
            key=lambda item: item["sent_at"],
        )
        start = datetime.fromisoformat(messages[0]["sent_at"])
        numbers = {item["mid"]: index for index, item in enumerate(messages, start=1)}
        queue: dict[str, list[dict[str, Any]]] = {}
        for card in sorted(
            (card for card in cards if card["session"] == session),
            key=lambda card: (card["minute"], card["card"]),
        ):
            queue.setdefault(card["participant"], []).append(card)
        lines: list[dict[str, Any]] = []
        used: set[str] = set()
        for index, item in enumerate(messages, start=1):
            participant = aliases.get(session, {}).get(item["author"])
            pending = queue.get(participant or "", [])
            card = pending.pop(0) if pending else None
            incident = card["incident"] if card else None
            if incident:
                used.add(incident)
            lines.append(
                {
                    "n": index,
                    "offset_s": int(
                        (datetime.fromisoformat(item["sent_at"]) - start).total_seconds()
                    ),
                    "author": item["author"],
                    "reply_to": numbers.get(item.get("reply_to") or ""),
                    "text": item["text"],
                    "role": card["expected_role"] if card else None,
                    "incidents": [incident] if incident else [],
                    "danger": None,
                    "card": card["card"] if card else None,
                }
            )
        rows.append(
            {
                "kind": "dialog",
                "id": f"d2-{session}",
                "scenario": "d2",
                "family": "d2",
                "style": "roleplay",
                "split": "control",
                "lines": lines,
                "incidents": [
                    {
                        "id": key,
                        "subtype": value["subtype"],
                        "location_scope": value["location_scope"],
                        "entrance": value["entrance"],
                        "floor": None,
                        "since": None,
                        "facets": {"current": "yes", "local": "yes", "observed": "yes"},
                        "uk_scope": "unclear",
                        "danger_kind": value["danger_kind"],
                        "signal_expected": value["signal_expected"],
                        "expected_route_type": value["expected_route_type"],
                    }
                    for key, value in sorted(incidents.items())
                    if value["session"] == session and key in used
                ],
                "synthetic": True,
                "origin": "d2_roleplay",
                "author": AUTHOR,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a D2 session export to D3 rows")
    parser.add_argument("export", type=pathlib.Path)
    parser.add_argument("aliases", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    export = [
        json.loads(raw)
        for raw in args.export.read_text(encoding="utf-8").splitlines()
        if raw.strip()
    ]
    if not all(row.get("synthetic") is True for row in export):
        raise SystemExit("в выгрузке D2 есть строки без synthetic: true — оценка остановлена")
    aliases = json.loads(args.aliases.read_text(encoding="utf-8"))
    cards, incidents = load_truth()
    rows = convert(export, aliases, cards, incidents)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    args.out.write_bytes(body.encode("utf-8"))
    print(f"{len(rows)} сессий, {sum(len(row['lines']) for row in rows)} реплик → {args.out}")


if __name__ == "__main__":
    main()
