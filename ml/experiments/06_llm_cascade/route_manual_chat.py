"""Offline candidate routing on assistant-annotated chat days; no API calls.

Only aggregate counts are written. The oracle columns are ceilings, not measured
LLM performance and not independent gold.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GROUP = ROOT / "experiments/04_grouping"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(GROUP))
from domsignal_ml.grouping import ChatTracker, CONTEXT_CUE, SERVICE_CUES  # noqa: E402
from domsignal_ml.heavy import HeavyEngine  # noqa: E402
from manual_review import message_key  # noqa: E402
from replay_real import load_day  # noqa: E402
from eval_manual_incidents import oracle_predictions, run_policy  # noqa: E402


def hours_between(a: str, b: datetime) -> float:
    parsed = datetime.fromisoformat(a.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed - b).total_seconds() / 3600


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    annotations = [json.loads(line) for line in
                   (GROUP / "manual_gold_v1.jsonl").read_text(encoding="utf-8").splitlines()]
    spec = yaml.safe_load((GROUP / "manual_incidents_v1.yaml").read_text(encoding="utf-8"))
    heavy = HeavyEngine(ROOT)
    result = {"scope_warning": "Assistant annotation and reused days; exploratory oracle ceilings only.",
              "policies": {}, "api_calls": 0}
    for scope in ("development", "heldout"):
        scope_counts = Counter()
        pair_counts = Counter()
        for day, config in spec["days"].items():
            if config["purpose"] != scope:
                continue
            rows = load_day(args.data_root, day)
            gold = [a for a in annotations if a["day"] == day]
            if len(rows) != len(gold) or any(
                    a["message_key"] != message_key(source, row["id"])
                    for (source, row), a in zip(rows, gold)):
                raise ValueError("annotation/source mismatch")
            predictions = heavy.predict_batch([row["text"] for _, row in rows])
            classes = {name: details["class"] for name, details in config["incidents"].items()}
            oracle = oracle_predictions(gold, rows, classes)
            tracker = ChatTracker(merge_policy="service_context_6h")
            route = []
            reasons = []
            for (_, row), annotation, prediction in zip(rows, gold, predictions):
                now = row["ts"]
                open_recent = [case for case in tracker.cases if case.status == "open"
                               and 0 <= hours_between(now, case.last_at) <= 6]
                reply_link = bool(row.get("reply_to") and any(
                    row["reply_to"] in case.message_ids for case in open_recent))
                context_cue = bool(CONTEXT_CUE.search(row["text"]))
                service_cue = any(cue.search(row["text"]) for cue in SERVICE_CUES.values())
                class_conflict = bool(prediction["is_problem"] and open_recent and
                                      any(case.fine_class != prediction["fine_class"]
                                          for case in open_recent))
                reason = None
                if reply_link:
                    reason = "reply_to_open_case"
                elif not prediction["is_problem"] and open_recent and context_cue:
                    reason = "rejected_context_near_case"
                elif not prediction["is_problem"] and open_recent and service_cue:
                    reason = "rejected_service_near_case"
                elif class_conflict and context_cue:
                    reason = "accepted_class_conflict"
                selected = bool(reason)
                route.append(selected)
                reasons.append(reason)
                tracker.consume({"id": row["id"], "text": row["text"], "ts": row["ts"],
                                 "reply_to": row.get("reply_to"), "house_id": "one_house"},
                                prediction)
            baseline = run_policy(rows, gold, predictions, "service_context_6h")
            for prefix, metrics in (("baseline", baseline),):
                for key in ("tp", "fp", "fn"):
                    pair_counts[f"{prefix}_{key}"] += metrics["pair_all"][key]
            scorable = [i for i, item in enumerate(gold) if item["role"] != "uncertain"]
            missed = [i for i in scorable if gold[i]["incident_ids"]
                      and not predictions[i]["is_problem"]]
            variants = {
                "all_candidates": route,
                "context_or_reply": [reason in {"reply_to_open_case",
                                                "rejected_context_near_case",
                                                "rejected_service_near_case"}
                                     for reason in reasons],
                "reply_only": [reason == "reply_to_open_case" for reason in reasons],
            }
            for variant, mask in variants.items():
                corrected = [dict(pred) for pred in predictions]
                for i, selected in enumerate(mask):
                    if selected:
                        corrected[i]["is_problem"] = oracle[i]["is_problem"]
                        corrected[i]["fine_class"] = oracle[i]["fine_class"]
                        if gold[i]["role"] == "resolution":
                            corrected[i]["utterance"] = "resolved_notice"
                ceiling = run_policy(rows, gold, corrected, "service_context_6h")
                for key in ("tp", "fp", "fn"):
                    pair_counts[f"{variant}_{key}"] += ceiling["pair_all"][key]
                scope_counts.update({
                    f"{variant}_selected": sum(mask),
                    f"{variant}_routed_missed_positive": sum(mask[i] for i in missed),
                })
            scope_counts.update({
                "messages": len(rows), "scorable": len(scorable),
                "selected": sum(route), "selected_scorable": sum(route[i] for i in scorable),
                "selected_gold_positive": sum(route[i] and bool(gold[i]["incident_ids"])
                                              for i in scorable),
                "selected_gold_negative": sum(route[i] and not gold[i]["incident_ids"]
                                              for i in scorable),
                "selected_uncertain": sum(route[i] and gold[i]["role"] == "uncertain"
                                          for i in range(len(rows))),
                "missed_positive": len(missed),
                "routed_missed_positive": sum(route[i] for i in missed),
            })
            scope_counts.update({f"reason_{r}": n for r, n in Counter(
                reason for reason in reasons if reason).items()})
        def prf(prefix: str) -> dict:
            tp, fp, fn = (pair_counts[f"{prefix}_{key}"] for key in ("tp", "fp", "fn"))
            p = tp / (tp + fp) if tp + fp else 0
            r = tp / (tp + fn) if tp + fn else 0
            return {"precision": round(p, 4), "recall": round(r, 4),
                    "f1": round(2 * p * r / (p + r), 4) if p + r else 0,
                    "tp": tp, "fp": fp, "fn": fn}
        result["policies"][scope] = {"routing": dict(scope_counts),
                                     "baseline_pair": prf("baseline"),
                                     "all_candidates_oracle_pair_ceiling": prf("all_candidates"),
                                     "context_or_reply_oracle_pair_ceiling": prf("context_or_reply"),
                                     "reply_only_oracle_pair_ceiling": prf("reply_only")}
    output = Path(__file__).with_name("route_manual_chat.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
