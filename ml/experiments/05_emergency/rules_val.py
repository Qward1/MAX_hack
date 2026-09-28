"""Validation-only comparison of safety rules with model score."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import load_safety  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402
from domsignal_ml.safety import direct_rule, risk_cue  # noqa: E402


def main() -> None:
    rows = load_safety(Path(sys.argv[1]), "val")
    bundle = load_bundle(ROOT / "artifacts" / "light.joblib")
    y = np.array([bool(row["emergency"]) for row in rows])
    score = bundle["safety"].predict_proba(
        bundle["features"].transform([row["text"] for row in rows]))[:, 1]
    direct = np.array([direct_rule(row["text"]) is not None for row in rows])
    cue = np.array([risk_cue(row["text"]) for row in rows])
    result = []
    for name, fixed in (("model", np.zeros(len(rows), bool)),
                        ("direct_or_model", direct),
                        ("direct_or_cued_model", direct)):
        best = None
        for threshold in np.r_[np.unique(score), 1.0]:
            model_pred = score >= threshold
            if name == "direct_or_cued_model":
                model_pred &= cue
            pred = fixed | model_pred
            fp = int((pred & ~y).sum())
            if fp / int((~y).sum()) > 0.05:
                continue
            tp = int((pred & y).sum())
            candidate = (tp, -fp, float(threshold), fp)
            if best is None or candidate > best:
                best = candidate
        if best is None:
            result.append({"name": name, "feasible": False})
            continue
        tp, _, threshold, fp = best
        result.append({"name": name, "threshold": round(threshold, 6),
                       "val_recall": round(tp / int(y.sum()), 4),
                       "val_fpr": round(fp / int((~y).sum()), 4),
                       "direct_tp": int((direct & y).sum()),
                       "direct_fp": int((direct & ~y).sum())})
    output = {"split": "val", "n": len(rows), "emergencies": int(y.sum()),
              "model_ap": round(float(average_precision_score(y, score)), 4),
              "results": result}
    Path(__file__).with_name("rules_val.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
