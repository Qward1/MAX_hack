"""Evaluate chat case grouping on frozen assistant-reviewed incident links.

The report contains only counts and scores, never message text.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.grouping import ChatTracker  # noqa: E402
from domsignal_ml.pipeline import classify_text, load_bundle, load_mapping  # noqa: E402
from domsignal_ml.slots import slots  # noqa: E402
from manual_review import message_key  # noqa: E402
from replay_real import load_day  # noqa: E402


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


def pair_counts(gold: list[dict], case_ids: list[str | None], indices: list[int]) -> tuple[int, int, int]:
    tp = fp = fn = 0
    for p, i in enumerate(indices):
        for j in indices[p + 1:]:
            same_gold = bool(set(gold[i]["incident_ids"]) & set(gold[j]["incident_ids"]))
            same_pred = bool(case_ids[i] and case_ids[i] == case_ids[j])
            tp += same_gold and same_pred
            fp += not same_gold and same_pred
            fn += same_gold and not same_pred
    return tp, fp, fn


def oracle_predictions(gold: list[dict], rows: list[tuple], classes: dict[str, str]) -> list[dict]:
    predictions = []
    for annotation, (_, row) in zip(gold, rows):
        primary = annotation["primary_incident"]
        predictions.append({"is_problem": bool(primary),
                            "fine_class": classes[primary] if primary else None,
                            "utterance": "resolved_notice" if annotation["role"] == "resolution"
                            else "report", "urgent_human_review": False,
                            "slots": slots(row["text"])})
    return predictions


def combine_predictions(light: list[dict], heavy: list[dict], mode: str) -> list[dict]:
    """Simple chat-level gate ensembles; heavy class wins when both gates accept."""
    if mode not in {"union", "intersection"}:
        raise ValueError(mode)
    combined = []
    for sparse, encoder in zip(light, heavy):
        accepted = (sparse["is_problem"] or encoder["is_problem"] if mode == "union"
                    else sparse["is_problem"] and encoder["is_problem"])
        source = encoder if encoder["is_problem"] else sparse
        prediction = dict(source)
        prediction["is_problem"] = bool(accepted)
        if not accepted:
            prediction["fine_class"] = None
        combined.append(prediction)
    return combined


def run_policy(rows: list[tuple], gold: list[dict], predictions: list[dict],
               policy: str) -> dict:
    tracker = ChatTracker(merge_policy=policy)
    case_ids = []
    actions = Counter()
    correct_closures = 0
    false_closures = 0
    previous_gold_by_case: dict[str, set[str]] = defaultdict(set)
    for (_, row), annotation, prediction in zip(rows, gold, predictions):
        event = tracker.consume({"id": row["id"], "text": row["text"], "ts": row["ts"],
                                 "reply_to": row.get("reply_to"), "house_id": "one_house"},
                                prediction)
        case_id = event["case_id"]
        case_ids.append(case_id)
        actions[event["action"]] += 1
        if annotation["role"] != "uncertain" and event["action"] == "closed_unverified":
            if annotation["role"] == "resolution" and set(annotation["incident_ids"]) & previous_gold_by_case[case_id]:
                correct_closures += 1
            else:
                false_closures += 1
        if case_id and annotation["role"] != "uncertain":
            previous_gold_by_case[case_id].update(annotation["incident_ids"])
    scorable = [i for i, item in enumerate(gold) if item["role"] != "uncertain"]
    explicit = [i for i in scorable if gold[i]["role"] == "report"
                and len(gold[i]["incident_ids"]) == 1]
    pair_all = prf(*pair_counts(gold, case_ids, scorable))
    pair_explicit = prf(*pair_counts(gold, case_ids, explicit))
    gold_positive = {i for i in scorable if gold[i]["incident_ids"]}
    gold_negative = set(scorable) - gold_positive
    predicted_positive = {i for i in scorable if predictions[i]["is_problem"]}
    gate = prf(len(gold_positive & predicted_positive),
               len(gold_negative & predicted_positive),
               len(gold_positive - predicted_positive))
    context = [i for i in scorable if gold[i]["role"] == "context"]
    resolutions = [i for i in scorable if gold[i]["role"] == "resolution"]
    cases_to_gold: dict[str, set[str]] = defaultdict(set)
    cases_to_negative: Counter = Counter()
    incident_to_cases: dict[str, set[str]] = defaultdict(set)
    for i in scorable:
        case_id = case_ids[i]
        if not case_id:
            continue
        if not gold[i]["incident_ids"]:
            cases_to_negative[case_id] += 1
        for incident in gold[i]["incident_ids"]:
            cases_to_gold[case_id].add(incident)
            incident_to_cases[incident].add(case_id)
    all_incidents = {incident for i in scorable for incident in gold[i]["incident_ids"]}
    report = {
        "messages": len(rows), "scorable_messages": len(scorable),
        "uncertain_messages": len(rows) - len(scorable),
        "gold_incidents": len(all_incidents),
        "gold_multi_issue_messages": sum(len(gold[i]["incident_ids"]) > 1 for i in scorable),
        "gate_on_manual_labels": gate,
        "pair_all": pair_all, "pair_explicit_single_issue": pair_explicit,
        "gold_positive_message_case_recall": round(
            sum(bool(case_ids[i]) for i in gold_positive) / len(gold_positive), 4)
            if gold_positive else None,
        "gold_context_message_case_recall": round(
            sum(bool(case_ids[i]) for i in context) / len(context), 4)
            if context else None,
        "negative_messages_assigned_case": sum(bool(case_ids[i]) for i in gold_negative),
        "cases_created": len(tracker.cases),
        "cases_with_distinct_single_issue_gold": sum(
            len({gold[i]["incident_ids"][0] for i in scorable
                 if case_ids[i] == case.case_id and len(gold[i]["incident_ids"]) == 1}) > 1
            for case in tracker.cases),
        "cases_with_negative_message": len(cases_to_negative),
        "gold_incidents_split_across_cases": sum(len(v) > 1 for v in incident_to_cases.values()),
        "gold_incidents_without_case": len(all_incidents - set(incident_to_cases)),
        "gold_resolutions": len(resolutions), "correct_unverified_closures": correct_closures,
        "false_unverified_closures": false_closures,
        "actions": dict(actions),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--scope", choices=["development", "heldout"], required=True)
    args = parser.parse_args()
    annotations = [json.loads(line) for line in
                   (HERE / "manual_gold_v1.jsonl").read_text(encoding="utf-8").splitlines()]
    spec = yaml.safe_load((HERE / "manual_incidents_v1.yaml").read_text(encoding="utf-8"))
    light = load_bundle(ROOT / "artifacts/light.joblib")
    mapping = load_mapping(ROOT / "configs/class_mapping.yaml")
    from domsignal_ml.heavy import HeavyEngine
    heavy = HeavyEngine(ROOT)
    report = {"annotation_version": spec["version"], "scope": args.scope,
              "independent_human_gold": False, "days": {}, "pooled": {}}
    sums = defaultdict(Counter)
    for day, config in spec["days"].items():
        if config["purpose"] != args.scope:
            continue
        rows = load_day(args.data_root, day)
        gold = [a for a in annotations if a["day"] == day]
        if len(rows) != len(gold) or any(
                a["message_key"] != message_key(source, row["id"])
                for (source, row), a in zip(rows, gold)):
            raise ValueError(f"annotation/source mismatch for {day}")
        texts = [row["text"] for _, row in rows]
        light_predictions = [classify_text(text, light, mapping) for text in texts]
        heavy_predictions = heavy.predict_batch(texts)
        variants = {
            "light": light_predictions,
            "heavy": heavy_predictions,
            "gate_union": combine_predictions(light_predictions, heavy_predictions, "union"),
            "gate_intersection": combine_predictions(light_predictions, heavy_predictions,
                                                       "intersection"),
            "oracle_labels": oracle_predictions(gold, rows,
                {name: details["class"] for name, details in config["incidents"].items()}),
        }
        report["days"][day] = {}
        for variant, predictions in variants.items():
            report["days"][day][variant] = {}
            for policy in ("conservative", "broad_6h", "broad_24h", "service_context_6h"):
                metrics = run_policy(rows, gold, predictions, policy)
                report["days"][day][variant][policy] = metrics
                count = sums[(variant, policy)]
                for prefix in ("pair_all", "pair_explicit_single_issue", "gate_on_manual_labels"):
                    for field in ("tp", "fp", "fn"):
                        count[prefix + "_" + field] += metrics[prefix][field]
                for field in ("messages", "scorable_messages", "uncertain_messages",
                              "gold_incidents", "cases_created", "negative_messages_assigned_case",
                              "cases_with_distinct_single_issue_gold", "gold_incidents_split_across_cases",
                              "gold_resolutions", "correct_unverified_closures", "false_unverified_closures"):
                    count[field] += metrics[field]
    for (variant, policy), values in sums.items():
        pooled = {prefix: prf(*(values[prefix + "_" + field] for field in ("tp", "fp", "fn")))
                  for prefix in ("pair_all", "pair_explicit_single_issue", "gate_on_manual_labels")}
        pooled.update({field: values[field] for field in
                       ("messages", "scorable_messages", "uncertain_messages",
                        "gold_incidents", "cases_created", "negative_messages_assigned_case",
                        "cases_with_distinct_single_issue_gold", "gold_incidents_split_across_cases",
                        "gold_resolutions", "correct_unverified_closures", "false_unverified_closures")})
        report["pooled"].setdefault(variant, {})[policy] = pooled
    output = HERE / f"manual_eval_{args.scope}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({variant: policies["conservative"] for variant, policies in report["pooled"].items()},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
