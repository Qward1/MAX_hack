"""Сборка машиночитаемой части отчёта P6 из сохранённых прогонов.

    uv run python evaluation/p6_report.py --out evaluation/reports/2026-09-23-p6-evaluation.json
    uv run python evaluation/p6_report.py --errors <прогон> [--limit 8]

Модель здесь не вызывается: сводки пересчитываются из сырых записей окон
`reports/p6-runs/*.jsonl`, поэтому отчёт воспроизводим без сети.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evaluation.metrics import sha256_of  # noqa: E402
from evaluation.p6_eval import (  # noqa: E402
    DATASETS,
    LEDGER,
    RUNS_DIR,
    load_units,
    route_reference_accuracy,
    summarize,
)

D1_FILE = pathlib.Path("evaluation/reports/2026-09-23-p6-d1-aggregates.json")


def _records(run: str) -> list[dict[str, Any]]:
    path = RUNS_DIR / f"{run}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _git_sha() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        return done.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build(runs: list[str]) -> dict[str, Any]:
    summaries = {run: summarize(_records(run)) for run in runs}
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "datasets": {
            name: {"file": path.as_posix(), "sha256": sha256_of(path)}
            for name, path in DATASETS.items()
            if path.exists()
        },
        "runs": summaries,
        "routing_reference": route_reference_accuracy(),
        "d1_aggregates": json.loads(D1_FILE.read_text(encoding="utf-8"))
        if D1_FILE.exists()
        else None,
        "slice_budget": ledger,
    }


def errors(run: str, limit: int) -> list[dict[str, Any]]:
    """Примеры ошибок прогона D3 — только синтетические реплики."""
    records = _records(run)
    dataset = records[0]["dataset"]
    units = {unit.id: unit for unit in load_units(dataset)}
    summary = summarize(records)["d3"]
    found: list[dict[str, Any]] = []
    for incident_id in summary["missed_incidents"]:
        unit_id = incident_id.split(".")[0]
        labels = units[unit_id].labels
        incident = next(item for item in labels["incidents"] if item["id"] == incident_id)
        texts = [line["text"] for line in labels["lines"] if incident_id in line["incidents"]]
        found.append({"kind": "missed", "incident": incident_id, "subtype": incident["subtype"],
                      "lines": texts[:4]})
    for detail in summary["route_details"]:
        if detail["route"][0] != detail["route"][1] or detail["subtype"][0] != detail["subtype"][1]:
            unit_id = detail["incident"].split(".")[0]
            labels = units[unit_id].labels
            texts = [
                line["text"] for line in labels["lines"] if detail["incident"] in line["incidents"]
            ]
            found.append({"kind": "wrong", **detail, "lines": texts[:3]})
    return found[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble the P6 report JSON from saved runs")
    parser.add_argument("--runs", nargs="*", default=[])
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--errors")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if args.errors:
        print(json.dumps(errors(args.errors, args.limit), ensure_ascii=False, indent=2))
        return
    runs = args.runs or sorted(
        path.name.removesuffix(".jsonl") for path in RUNS_DIR.glob("*.jsonl")
    )
    report = build(runs)
    body = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_bytes(body.encode("utf-8"))
    else:
        print(body, end="")


if __name__ == "__main__":
    main()
