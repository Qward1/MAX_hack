"""Validation comparison of flat 34-label sparse classifiers; no test reads."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil
from scipy.sparse import vstack
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import average_precision_score, f1_score
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.features import TextFeatures  # noqa: E402


def main() -> None:
    data = Path(sys.argv[1])
    tr = load_real(data, "train")
    va = load_real(data, "val")
    train = [row for source in SOURCES for row in tr[source]]
    val = [row for source in SOURCES for row in va[source]]
    syn = load_synthetic(data)
    yy = np.array([label_of(row, "class") for row in train])
    vy = np.array([label_of(row, "class") for row in val])
    sy = np.array([label_of(row, "class") for row in syn])
    feat = TextFeatures.baseline()
    start = time.perf_counter()
    x = feat.fit_transform([row["text"] for row in train])
    xv = feat.transform([row["text"] for row in val])
    xs = feat.transform([row["text"] for row in syn])
    xx = vstack((x, xs), format="csr")
    y_all = np.concatenate((yy, sy))
    cut = len(va[SOURCES[0]])
    configs = [
        ("lr", 0.5, "balanced", 0.0),
        ("lr", 4.0, "balanced", 0.0),
        ("lr", 16.0, "balanced", 0.0),
        ("lr", 4.0, "balanced", 0.5),
        ("lr", 4.0, "balanced", 1.0),
        ("lr", 16.0, "balanced", 0.5),
        ("svm", 0.25, "balanced", 0.0),
        ("svm", 1.0, "balanced", 0.0),
        ("svm", 4.0, "balanced", 0.0),
        ("svm", 1.0, "balanced", 0.5),
        ("svm", 4.0, "balanced", 0.5),
        ("svm", 1.0, None, 0.5),
        ("sgd", 1e-5, "balanced", 0.5),
        ("sgd", 1e-6, "balanced", 0.5),
    ]
    results = []
    for family, strength, balance, syn_weight in configs:
        t0 = time.perf_counter()
        if family == "lr":
            model = LogisticRegression(C=strength, solver="liblinear", max_iter=1000,
                                       class_weight=balance, random_state=42)
        elif family == "svm":
            model = LinearSVC(C=strength, class_weight=balance, max_iter=3000,
                              random_state=42)
        else:
            model = SGDClassifier(loss="modified_huber", alpha=strength,
                                  class_weight=balance, max_iter=1000,
                                  random_state=42)
        if syn_weight:
            weights = np.r_[np.ones(len(yy)), np.full(len(sy), syn_weight)]
            model.fit(xx, y_all, sample_weight=weights)
        else:
            model.fit(x, yy)
        pred = model.predict(xv)
        if family == "lr":
            score = 1 - model.predict_proba(xv)[:, list(model.classes_).index("not_a_problem")]
        else:
            decision = model.decision_function(xv)
            negative_index = list(model.classes_).index("not_a_problem")
            score = np.max(np.delete(decision, negative_index, axis=1), axis=1) - decision[:, negative_index]
        item = {"model": family, "strength": strength, "class_weight": balance,
                "synthetic_weight": syn_weight, "seconds": round(time.perf_counter() - t0, 2),
                "rss_mb": round(psutil.Process().memory_info().rss / 2**20, 1),
                "macro_f1_wa": round(float(f1_score(vy[:cut], pred[:cut], labels=sorted(set(vy[:cut])), average="macro", zero_division=0)), 4),
                "macro_f1_tg": round(float(f1_score(vy[cut:], pred[cut:], labels=sorted(set(vy[cut:])), average="macro", zero_division=0)), 4),
                "gate_ap_wa": round(float(average_precision_score(vy[:cut] != "not_a_problem", score[:cut])), 4),
                "gate_ap_tg": round(float(average_precision_score(vy[cut:] != "not_a_problem", score[cut:])), 4)}
        results.append(item)
        print(json.dumps(item), flush=True)
    report = {"split": "val", "train_real": len(train), "train_synthetic": len(syn),
              "features": x.shape[1], "vectorizer_seconds": round(time.perf_counter() - start, 2),
              "results": results}
    Path(__file__).with_name("flat_sparse_val.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
