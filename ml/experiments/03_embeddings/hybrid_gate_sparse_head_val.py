"""Fuse sparse and E5 features for gate, retain validated sparse class head."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import csr_matrix, hstack, vstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402
from domsignal_ml.train import gate_threshold  # noqa: E402


def main():
    data = Path(sys.argv[1])
    tr = load_real(data, "train")
    va = load_real(data, "val")
    train = [r for source in SOURCES for r in tr[source]]
    val = [r for source in SOURCES for r in va[source]]
    syn = load_synthetic(data)
    e_cache = ROOT / "artifacts/embeddings_e5_base"
    e_tr, e_va, e_sy = [np.load(e_cache / f) for f in
                         ("real_train.npy", "real_val.npy", "synthetic_train.npy")]
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    feature = bundle["gate_features"]
    x = feature.transform([r["text"] for r in train])
    xv = feature.transform([r["text"] for r in val])
    eligible = [i for i, r in enumerate(syn) if "gate" in r["annotation"].get("use", [])]
    xs = feature.transform([syn[i]["text"] for i in eligible])
    y = np.array([label_of(r, "class") != "not_a_problem" for r in train])
    sy = np.array([label_of(syn[i], "class") != "not_a_problem" for i in eligible])
    vy = np.array([label_of(r, "class") != "not_a_problem" for r in val])
    gold = np.array([label_of(r, "class") for r in val])
    sparse_class = bundle["classes"].predict(bundle["features"].transform([r["text"] for r in val]))
    cut = len(va[SOURCES[0]])
    results = []
    for scale in (0.5, 1.0):
        start = time.perf_counter()
        train_x = vstack((hstack((x, csr_matrix(e_tr * scale)), format="csr"),
                          hstack((xs, csr_matrix(e_sy[eligible] * scale)), format="csr")), format="csr")
        val_x = hstack((xv, csr_matrix(e_va * scale)), format="csr")
        model = LogisticRegression(C=16, solver="liblinear", max_iter=1000,
                                   class_weight="balanced", random_state=42).fit(train_x, np.r_[y, sy])
        score = model.predict_proba(val_x)[:, 1]
        op = gate_threshold(vy, score)
        pred = sparse_class.copy()
        pred[score < op["threshold"]] = "not_a_problem"
        item = {"scale": scale, "threshold": op["threshold"],
                "seconds": round(time.perf_counter() - start, 2), "sources": {}}
        for source, sub in ((SOURCES[0], slice(0, cut)), (SOURCES[1], slice(cut, None))):
            binary_pred = score[sub] >= op["threshold"]
            p, r, _, _ = precision_recall_fscore_support(vy[sub], binary_pred,
                                                         average="binary", zero_division=0)
            item["sources"][source] = {
                "gate_ap": round(float(average_precision_score(vy[sub], score[sub])), 4),
                "gate_precision": round(float(p), 4), "gate_recall": round(float(r), 4),
                "end_f1_sparse_class": round(float(f1_score(
                    gold[sub], pred[sub], labels=sorted(set(gold[sub])),
                    average="macro", zero_division=0)), 4),
            }
        results.append(item)
        artifact = ROOT / "artifacts" / f"hybrid_gate_scale{int(scale * 100):03d}.joblib"
        joblib.dump({"model": model, "scale": scale, "threshold": op["threshold"],
                     "features": feature, "encoder": "intfloat/multilingual-e5-base"},
                    artifact, compress=3)
        print(json.dumps(item), flush=True)
    Path(__file__).with_name("hybrid_gate_sparse_head_val.json").write_text(
        json.dumps({"split": "val", "results": results}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
