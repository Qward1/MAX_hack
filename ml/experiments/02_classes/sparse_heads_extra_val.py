"""Additional sparse heads for positive messages, frozen gate, val only."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import vstack
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.metrics import f1_score
from sklearn.naive_bayes import ComplementNB
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main():
    data = Path(sys.argv[1])
    tr = load_real(data, "train")
    va = load_real(data, "val")
    train = [row for source in SOURCES for row in tr[source]]
    val = [row for source in SOURCES for row in va[source]]
    syn = load_synthetic(data)
    y = np.array([label_of(row, "class") for row in train])
    vy = np.array([label_of(row, "class") for row in val])
    sy = np.array([label_of(row, "class") for row in syn])
    pos = np.where(y != "not_a_problem")[0]
    syn_pos = np.where(sy != "not_a_problem")[0]
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    gate_score = bundle["gate"].predict_proba(bundle["gate_features"].transform(
        [row["text"] for row in val]))[:, 1]
    gate_pred = gate_score >= bundle["gate_threshold"]
    x = bundle["features"].transform([row["text"] for row in train])
    xv = bundle["features"].transform([row["text"] for row in val])
    xs = bundle["features"].transform([row["text"] for row in syn])
    xx = vstack((x[pos], xs[syn_pos]), format="csr")
    yy = np.r_[y[pos], sy[syn_pos]]
    cut = len(va[SOURCES[0]])
    configurations = [
        ("lr", c, balance, weight)
        for c in (0.5, 4.0, 16.0)
        for balance, weight in (("balanced", 0.5), (None, 0.5))
    ] + [("svm", 0.25, None, 0.5), ("svm", 1.0, None, 0.5),
         ("ridge", 1.0, "balanced", 0.5),
         ("cnb", 0.1, None, 0.5), ("cnb", 1.0, None, 0.5)]
    results = []
    for name, strength, balance, syn_weight in configurations:
        start = time.perf_counter()
        if name == "lr":
            model = LogisticRegression(solver="liblinear", C=strength,
                                       class_weight=balance, max_iter=1000, random_state=42)
        elif name == "svm":
            model = LinearSVC(C=strength, class_weight=balance, random_state=42)
        elif name == "ridge":
            model = RidgeClassifier(alpha=strength, class_weight=balance)
        else:
            model = ComplementNB(alpha=strength)
        weight = np.r_[np.ones(len(pos)), np.full(len(syn_pos), syn_weight)]
        model.fit(xx, yy, sample_weight=weight)
        pred = model.predict(xv)
        pred[~gate_pred] = "not_a_problem"
        item = {"name": name, "strength": strength, "class_weight": balance,
                "synthetic_weight": syn_weight,
                "seconds": round(time.perf_counter() - start, 2),
                "macro_f1_wa": round(float(f1_score(vy[:cut], pred[:cut], labels=sorted(set(vy[:cut])), average="macro", zero_division=0)), 4),
                "macro_f1_tg": round(float(f1_score(vy[cut:], pred[cut:], labels=sorted(set(vy[cut:])), average="macro", zero_division=0)), 4)}
        results.append(item)
        print(json.dumps(item), flush=True)
    Path(__file__).with_name("sparse_heads_extra_val.json").write_text(
        json.dumps({"split": "val", "results": results}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
