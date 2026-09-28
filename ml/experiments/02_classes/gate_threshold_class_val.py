"""Choose class operating point on val, separate from product gate threshold."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main():
    va = load_real(Path(sys.argv[1]), "val")
    rows = [r for source in SOURCES for r in va[source]]
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    texts = [r["text"] for r in rows]
    score = bundle["gate"].predict_proba(bundle["gate_features"].transform(texts))[:, 1]
    class_pred = bundle["classes"].predict(bundle["features"].transform(texts))
    gold = np.array([label_of(r, "class") for r in rows])
    binary = gold != "not_a_problem"
    cut = len(va[SOURCES[0]])
    trials = []
    for threshold in np.linspace(0.10, 0.90, 81):
        pred = class_pred.copy()
        pred[score < threshold] = "not_a_problem"
        item = {"threshold": round(float(threshold), 3)}
        for source, sub in ((SOURCES[0], slice(0, cut)), (SOURCES[1], slice(cut, None))):
            mask = score[sub] >= threshold
            p, r, _, _ = precision_recall_fscore_support(binary[sub], mask,
                                                         average="binary", zero_division=0)
            item[source] = {"macro_f1": round(float(f1_score(
                gold[sub], pred[sub], labels=sorted(set(gold[sub])),
                average="macro", zero_division=0)), 4),
                            "gate_precision": round(float(p), 4),
                            "gate_recall": round(float(r), 4)}
        item["mean_f1"] = round(float(np.mean([item[source]["macro_f1"]
                                               for source in SOURCES])), 4)
        trials.append(item)
    best = max(trials, key=lambda r: r["mean_f1"])
    constrained = [r for r in trials if all(r[s]["gate_precision"] >= 0.70 for s in SOURCES)]
    best_constrained = max(constrained, key=lambda r: r["mean_f1"]) if constrained else None
    report = {"split": "val", "selection": "mean source macro-F1", "best": best,
              "best_precision_at_least_0_70_both": best_constrained,
              "current_threshold": bundle["gate_threshold"], "trials": trials}
    Path(__file__).with_name("gate_threshold_class_val.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"best": best, "best_constrained": best_constrained,
                      "current": bundle["gate_threshold"]}))


if __name__ == "__main__":
    main()
