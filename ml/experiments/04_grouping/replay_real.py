"""Replay selected anonymized chat days; aggregate only, never persist texts."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, read_jsonl  # noqa: E402
from domsignal_ml.grouping import ChatTracker  # noqa: E402
from domsignal_ml.pipeline import classify_text, load_bundle, load_mapping  # noqa: E402


def load_day(root: Path, day: str):
    rows = []
    for source in SOURCES:
        for name in ("all.jsonl", "excluded.jsonl"):
            for row in read_jsonl(root / source / name):
                if row["ts"].startswith(day):
                    rows.append((source, row))
    return sorted(rows, key=lambda pair: (pair[1]["ts"], pair[1]["id"]))


def replay(day: str, rows, predictions, policy: str):
    if len(rows) != len(predictions):
        raise ValueError("prediction count does not match message count")
    tracker = ChatTracker(merge_policy=policy)
    events = Counter()
    source_counts = Counter()
    accepted = Counter()
    gold_by_case = defaultdict(list)
    case_ids_by_gold = defaultdict(set)
    start = time.perf_counter()
    for (source, row), prediction in zip(rows, predictions):
        payload = {"id": row["id"], "text": row["text"], "ts": row["ts"],
                   "reply_to": row.get("reply_to"), "house_id": "one_house"}
        event = tracker.consume(payload, prediction)
        source_counts[source] += 1
        events[event["action"]] += 1
        events["urgent_review"] += int(prediction["urgent_human_review"])
        label = row.get("label")
        if label:
            gold = label["class"] != "not_a_problem"
            pred = prediction["is_problem"]
            accepted["messages"] += 1
            accepted["gold_problem"] += int(gold)
            accepted["tp"] += int(gold and pred)
            accepted["fp"] += int(not gold and pred)
            accepted["fn"] += int(gold and not pred)
            accepted["tn"] += int(not gold and not pred)
            if event["case_id"]:
                gold_by_case[event["case_id"]].append(label["class"])
                if gold:
                    entrance = label["fields"].get("entrance")
                    case_ids_by_gold[(label["class"], entrance)].add(event["case_id"])
        else:
            accepted["excluded_unlabelled"] += 1
            accepted["excluded_predicted_problem"] += int(prediction["is_problem"])
    cases = tracker.cases
    sizes = Counter(case.message_count for case in cases)
    mixed = sum(len(set(c for c in values if c != "not_a_problem")) > 1
                for values in gold_by_case.values())
    possible_fragments = sum(len(ids) > 1 for ids in case_ids_by_gold.values())
    return {"day": day, "merge_policy": policy, "rows": len(rows), "sources": dict(source_counts),
            "seconds": round(time.perf_counter() - start, 2),
            "events": dict(events), "accepted_only": dict(accepted),
            "cases_created": len(cases),
            "cases_open_at_end": sum(c.status == "open" for c in cases),
            "case_size_distribution": {str(k): v for k, v in sorted(sizes.items())},
            "cases_with_multiple_gold_problem_classes": mixed,
            "gold_class_entrance_groups_in_multiple_cases": possible_fragments,
            "warning": "Gold labels are LLM labels for individual messages. Neither count is incident accuracy."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--days", nargs="+", default=["2022-10-10", "2025-06-13", "2026-02-21"])
    parser.add_argument("--engine", choices=["light", "heavy"], default="light")
    args = parser.parse_args()
    if args.engine == "heavy":
        from domsignal_ml.heavy import HeavyEngine
        engine = HeavyEngine(ROOT)
        predict = engine.predict_batch
    else:
        bundle = load_bundle(ROOT / "artifacts/light.joblib")
        mapping = load_mapping(ROOT / "configs/class_mapping.yaml")
        predict = lambda texts: [classify_text(text, bundle, mapping) for text in texts]
    results = []
    inference = {}
    for day in args.days:
        rows = load_day(args.data_root, day)
        start = time.perf_counter()
        predictions = predict([row["text"] for _, row in rows])
        inference[day] = round(time.perf_counter() - start, 2)
        for policy in ("conservative", "broad_6h", "broad_24h"):
            results.append(replay(day, rows, predictions, policy))
    report = {"selection": "high-volume quiet day, cross-channel problem day, Telegram problem day",
              "engine": args.engine, "inference_seconds_by_day": inference, "days": results}
    Path(__file__).with_name(f"replay_real_{args.engine}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
