"""Aggregate the locked uncertainty sample without emitting any message text."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.heavy import HeavyEngine  # noqa: E402


def load_outcomes(stem: str) -> tuple[dict, float, int]:
    outcomes = {}
    cost = 0.0
    invalid = 0
    for suffix in ("", "_tail"):
        path = ROOT / "artifacts" / f"polza_pilot_{stem}_selective_synthetic{suffix}.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        cost += report["billed_or_estimated_rub"]
        for item in report["outcomes"]:
            if item["id"] in outcomes:
                raise ValueError("duplicate LLM outcome")
            outcomes[item["id"]] = item
            invalid += item["decision"].startswith("invalid")
    return outcomes, cost, invalid


def main() -> None:
    path = ROOT / "artifacts/polza_synthetic_uncertain_10.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != 10 or len({x["id"] for x in rows}) != 10:
        raise ValueError("locked pilot sample must have 10 unique rows")
    engine = HeavyEngine(ROOT)
    local_pred = engine.predict_batch([x["message"] for x in rows])
    local = {row["id"]: pred["fine_class"] or "not_a_problem"
             for row, pred in zip(rows, local_pred)}
    models = {}
    for name, stem in (("qwen35b_yandex", "qwen_qwen3.6-35b-a3b_800"),
                       ("gpt_oss_120b_yandex", "openai_gpt-oss-120b_300")):
        outcomes, cost, invalid = load_outcomes(stem)
        if set(outcomes) != {x["id"] for x in rows}:
            raise ValueError("missing LLM outcome")
        models[name] = {
            "correct": sum(outcomes[x["id"]]["decision"] == x["gold"] for x in rows),
            "rescued_local_errors": sum(local[x["id"]] != x["gold"] and
                                        outcomes[x["id"]]["decision"] == x["gold"]
                                        for x in rows),
            "spoiled_local_correct": sum(local[x["id"]] == x["gold"] and
                                         outcomes[x["id"]]["decision"] != x["gold"]
                                         for x in rows),
            "invalid_responses": invalid,
            "actual_billed_rub": round(cost, 4),
            "median_latency_seconds": round(sorted(x["latency_seconds"] for x in
                                                   outcomes.values())[5], 3),
        }
    report = {"split": "synthetic_val_selected_before_api",
              "selection": "5 near local gate threshold plus 5 low local class scores; strict privacy screen",
              "gold_origin": "synthetic labels generated/checked by LLM, not independent humans",
              "n": 10,
              "gold_in_local_top5": sum(x["gold"] in x["allowed_classes"] or
                                        x["gold"] == "not_a_problem" for x in rows),
              "local_correct": sum(local[x["id"]] == x["gold"] for x in rows),
              "models": models,
              "caution": "Tiny selected synthetic sample; no production performance claim."}
    output = Path(__file__).with_name("selective_synthetic_results.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
