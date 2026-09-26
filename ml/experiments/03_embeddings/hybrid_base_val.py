"""Combine validation-selected hybrid gate with ruBERT class checkpoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import torch
from scipy.sparse import csr_matrix, hstack
from sklearn.metrics import average_precision_score, f1_score, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main():
    data = Path(sys.argv[1])
    va = load_real(data, "val")
    rows = [r for source in SOURCES for r in va[source]]
    texts = [r["text"] for r in rows]
    gold = np.array([label_of(r, "class") for r in rows])
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    names = np.array(list(checkpoint["classes"]))
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")["class_logits"]
    class_pred = names[logits.argmax(axis=1)]
    cache = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_score = bundle["gate"].predict_proba(bundle["gate_features"].transform(texts))[:, 1]
    cut = len(va[SOURCES[0]])
    results = []
    for name, score, threshold in (("sparse", sparse_score, bundle["gate_threshold"]),):
        results.append(evaluate(name, score, threshold, class_pred, gold, cut))
    for scale in (0.5, 1.0):
        hybrid = joblib.load(ROOT / "artifacts" / f"hybrid_gate_scale{int(scale*100):03d}.joblib")
        x = hstack((hybrid["features"].transform(texts), csr_matrix(cache * scale)), format="csr")
        score = hybrid["model"].predict_proba(x)[:, 1]
        results.append(evaluate(f"hybrid_{scale}", score, hybrid["threshold"],
                                class_pred, gold, cut))
    report = {"split": "val", "class_checkpoint_epoch": checkpoint["epoch"],
              "results": results}
    Path(__file__).with_name("hybrid_base_val.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


def evaluate(name, score, threshold, class_pred, gold, cut):
    pred = class_pred.copy()
    pred[score < threshold] = "not_a_problem"
    result = {"name": name, "threshold": float(threshold), "sources": {}}
    for source, sub in ((SOURCES[0], slice(0, cut)), (SOURCES[1], slice(cut, None))):
        y = gold[sub] != "not_a_problem"
        binary_pred = score[sub] >= threshold
        p, r, _, _ = precision_recall_fscore_support(y, binary_pred, average="binary",
                                                     zero_division=0)
        result["sources"][source] = {
            "gate_ap": round(float(average_precision_score(y, score[sub])), 4),
            "gate_precision": round(float(p), 4), "gate_recall": round(float(r), 4),
            "end_macro_f1": round(float(f1_score(gold[sub], pred[sub],
                                                 labels=sorted(set(gold[sub])),
                                                 average="macro", zero_division=0)), 4),
        }
    return result


if __name__ == "__main__":
    main()
