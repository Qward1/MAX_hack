"""Materialize the assistant-reviewed incident links without message text."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from manual_review import message_key
from replay_real import load_day


HERE = Path(__file__).resolve().parent


def build(data_root: Path) -> tuple[list[dict], dict]:
    spec = yaml.safe_load((HERE / "manual_incidents_v1.yaml").read_text(encoding="utf-8"))
    annotations = []
    summary = {"version": spec["version"], "days": {}, "annotator": "assistant_manual_review",
               "independent_human_adjudication": False}
    for day, config in spec["days"].items():
        rows = load_day(data_root, day)
        fingerprint = hashlib.sha256("|".join(
            source + ":" + row["id"] for source, row in rows).encode()).hexdigest()
        if len(rows) != config["expected_rows"] or fingerprint != config["fingerprint"]:
            raise ValueError(f"source changed for {day}; annotation indices are invalid")
        memberships = defaultdict(list)
        for incident, detail in config["incidents"].items():
            for index in detail["indices"]:
                if not 0 <= index < len(rows):
                    raise ValueError(f"index out of bounds for {day}")
                if incident in memberships[index]:
                    raise ValueError(f"duplicate link for {day}:{index}")
                memberships[index].append(incident)
        uncertain = set(config["uncertain_indices"])
        context = set(config["context_indices"])
        resolution = set(config["resolution_indices"])
        if any(not 0 <= i < len(rows) for i in uncertain | context | resolution):
            raise ValueError(f"role index out of bounds for {day}")
        if uncertain & memberships.keys():
            raise ValueError(f"uncertain and linked messages overlap for {day}")
        if (context | resolution) - memberships.keys():
            raise ValueError(f"context/resolution without incident for {day}")
        counts = Counter()
        for index, (source, row) in enumerate(rows):
            incident_ids = sorted(memberships[index])
            override = config["primary_by_index"].get(index)
            if len(incident_ids) > 1 and override not in incident_ids:
                raise ValueError(f"multi-issue primary missing for {day}:{index}")
            if override and override not in incident_ids:
                raise ValueError(f"primary not linked for {day}:{index}")
            primary = override or (incident_ids[0] if incident_ids else None)
            role = ("uncertain" if index in uncertain else
                    "resolution" if index in resolution else
                    "context" if index in context else
                    "report" if incident_ids else "negative")
            item = {"day": day, "index": index,
                    "message_key": message_key(source, row["id"]),
                    "source": source, "incident_ids": incident_ids,
                    "primary_incident": primary, "role": role}
            annotations.append(item)
            counts[role] += 1
            counts["multi_issue"] += len(incident_ids) > 1
        summary["days"][day] = {"purpose": config["purpose"], "messages": len(rows),
                                 "incidents": len(config["incidents"]),
                                 "roles": dict(counts)}
    return annotations, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    annotations, summary = build(args.data_root)
    output = HERE / "manual_gold_v1.jsonl"
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                              for row in annotations), encoding="utf-8")
    summary_path = HERE / "manual_gold_v1_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
