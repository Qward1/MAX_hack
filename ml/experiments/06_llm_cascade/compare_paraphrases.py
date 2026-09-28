"""Compare local and budgeted LLM decisions on privacy reviewed paraphrases."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.heavy import HeavyEngine  # noqa: E402


def main() -> None:
    items = [json.loads(line) for line in
             (ROOT / "examples/polza_pilot_paraphrased.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    class_items = [x for x in items if x["task"] == "classify"]
    engine = HeavyEngine(ROOT)
    local = engine.predict_batch([x["message"] for x in class_items])
    threshold = engine.gate["threshold"]
    reports = {}
    decisions_by_model = {}
    for model, limit in (("sber_gigachat-2", 300),
                         ("qwen_qwen3.6-35b-a3b", 800),
                         ("openai_gpt-oss-120b", 800)):
        path = ROOT / "artifacts" / f"polza_pilot_{model}_{limit}.json"
        if not path.is_file():
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        decisions_by_model[model] = {x["id"]: x["decision"] for x in result["outcomes"]}
        reports[model] = {"calls": result["calls"],
                          "billed_or_estimated_rub": result["billed_or_estimated_rub"],
                          "classify_correct": 0, "link_correct": 0,
                          "invalid": sum(x["decision"].startswith("invalid")
                                         for x in result["outcomes"])}
    rows = []
    for item, pred in zip(class_items, local):
        guess = pred["fine_class"] or "not_a_problem"
        gate = pred["confidence"]["gate_score"]
        # Fixed exploratory route: near the gate threshold or a low class score.
        routed = abs(gate - threshold) <= 0.15 or (
            pred["is_problem"] and pred["confidence"]["class_score_uncalibrated"] <= 0.2)
        row = {"id": item["id"], "gold": item["gold"],
               "local": guess, "local_correct": guess == item["gold"],
               "gate_score": gate,
               "class_score_uncalibrated": pred["confidence"]["class_score_uncalibrated"],
               "routed": routed}
        for model, choices in decisions_by_model.items():
            decision = choices.get(item["id"])
            if decision is not None:
                row[model] = decision
                reports[model]["classify_correct"] += int(decision == item["gold"])
        rows.append(row)
    for item in items:
        if item["task"] == "link":
            for model, choices in decisions_by_model.items():
                reports[model]["link_correct"] += int(choices.get(item["id"]) == item["gold"])
    cascades = {}
    for model in decisions_by_model:
        correct = sum((row[model] if row["routed"] else row["local"]) == row["gold"]
                      for row in rows if model in row)
        cascades[model] = {"routed": sum(row["routed"] for row in rows),
                           "correct": correct, "total": len(rows)}
    report = {"sample": "handwritten privacy reviewed paraphrases inspired by uncertain real messages",
              "independent_human_gold": False,
              "local_classify_correct": sum(x["local_correct"] for x in rows),
              "classify_total": len(rows), "llm": reports, "cascade": cascades,
              "rows_without_text": rows}
    output = ROOT / "artifacts/polza_paraphrase_compare.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows_without_text"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
