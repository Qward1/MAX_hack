"""Preselect uncertain synthetic validation messages before any LLM answer.

The ignored input file remains disabled until a person reviews shuffled word
hints and explicitly marks privacy_reviewed=true. Raw text is never printed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from domsignal_ml.data import load_synthetic  # noqa: E402
from domsignal_ml.heavy import HeavyEngine  # noqa: E402
from polza_pilot import UNSAFE  # noqa: E402


def bag(text: str) -> str:
    """Show shuffled word hints, not the message or its original word order."""
    words = re.findall(r"[а-яёА-ЯЁ]+", text)
    safe = {w for w in words if w.islower() and 3 <= len(w) <= 13
            and w not in {"тарасовская", "королев", "королёв", "квартира"}}
    return " ".join(sorted(safe)[:22])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    rows = load_synthetic(args.data_root, "val")
    eligible = [(i, row) for i, row in enumerate(rows)
                if 20 <= len(row["text"]) <= 160
                and not UNSAFE.search(row["text"])
                and not re.search(r"[\[\]<>#]|(?:ул|кв|тел|корп)\.", row["text"],
                                  flags=re.IGNORECASE)]
    engine = HeavyEngine(ROOT)
    texts = [row["text"] for _, row in eligible]
    pred = engine.predict_batch(texts)
    logits = engine._class_logits(texts)
    logits[:, engine.negative_index] = -1e9
    bert = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse = np.zeros_like(bert)
    sparse[:, engine.sparse_class_indices] = engine.light["classes"].predict_proba(
        engine.light["features"].transform(texts))
    probs = (bert + sparse) / 2
    top5 = np.argsort(-probs, axis=1)[:, :5]
    threshold = engine.gate["threshold"]
    gate_rank = sorted(range(len(eligible)), key=lambda i:
                       abs(pred[i]["confidence"]["gate_score"] - threshold))
    class_rank = sorted(range(len(eligible)), key=lambda i:
                        pred[i]["confidence"]["class_score_uncalibrated"]
                        if pred[i]["is_problem"] else 100.0)
    selected = []
    for route, ordering in (("gate", gate_rank), ("class", class_rank)):
        count = 0
        for pos in ordering:
            if count >= 8:
                break
            if pos in {p for _, p in selected}:
                continue
            hint = bag(texts[pos])
            if len(hint.split()) < 4:
                continue
            selected.append((route, pos))
            count += 1
    records = []
    for route, pos in selected:
        original_index, row = eligible[pos]
        classes = [str(engine.class_names[i]) for i in top5[pos]]
        gold = row["label"]["class"]
        item = {"id": f"synthetic-uncertain-{original_index}", "task": "classify",
                "message": row["text"], "allowed_classes": classes,
                "gold": gold, "privacy_reviewed": False}
        records.append(item)
        local = pred[pos]["fine_class"] or "not_a_problem"
        print(json.dumps({"id": item["id"], "route": route, "gold": gold,
                          "local": local, "gate_score": pred[pos]["confidence"]["gate_score"],
                          "class_score": pred[pos]["confidence"]["class_score_uncalibrated"],
                          "gold_in_top5": gold in classes or gold == "not_a_problem",
                          "shuffled_word_hint": bag(row["text"])}, ensure_ascii=False))
    output = ROOT / "artifacts/polza_synthetic_uncertain_review.jsonl"
    output.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                      encoding="utf-8")
    print(json.dumps({"selected": len(records), "saved_for_review": str(output),
                      "api_calls": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
