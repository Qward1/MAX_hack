"""Read v3.0 only. Never modify source datasets or print raw texts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SOURCES = ("real_whatsapp", "real_telegram")


def ensure_v3(root: Path) -> Path:
    root = root.expanduser().resolve()
    card = root / "README.md"
    if not (root / "labels_taxonomy.yaml").is_file() or not card.is_file():
        raise FileNotFoundError(f"v3.0 datasets not found under {root}")
    if "v3.0" not in card.read_text(encoding="utf-8")[:500]:
        raise ValueError("dataset card does not declare v3.0")
    return root


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_real(root: Path, split: str) -> dict[str, list[dict[str, Any]]]:
    if split not in {"train", "val", "test"}:
        raise ValueError("split must be train, val or test")
    root = ensure_v3(root)
    return {source: read_jsonl(root / source / f"{split}.jsonl") for source in SOURCES}


def load_synthetic(root: Path, split: str = "train") -> list[dict[str, Any]]:
    if split not in {"train", "val"}:
        raise ValueError("synthetic has no test split")
    return read_jsonl(ensure_v3(root) / "synthetic" / f"{split}.jsonl")


def load_safety(root: Path, split: str) -> list[dict[str, Any]]:
    return [
        row for row in read_jsonl(ensure_v3(root) / "safety" / "emergency_cases.jsonl")
        if row.get("split") == split
    ]


def label_of(row: dict[str, Any], field: str) -> Any:
    return row["label"][field]


def positives(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if label_of(row, "class") != "not_a_problem"]
