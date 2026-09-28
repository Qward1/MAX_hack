"""Compare class heads using the frozen selected gate; validation only."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil
from scipy.sparse import vstack
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main() -> None:
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
    labels = np.r_[y[pos], sy[syn_pos]]
    weights = np.r_[np.ones(len(pos)), np.full(len(syn_pos), 0.5)]
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    gate_score = bundle["gate"].predict_proba(bundle["gate_features"].transform(
        [row["text"] for row in val]))[:, 1]
    gate_pred = gate_score >= bundle["gate_threshold"]
    x_sparse = bundle["features"].transform([row["text"] for row in train])
    xv_sparse = bundle["features"].transform([row["text"] for row in val])
    xs_sparse = bundle["features"].transform([row["text"] for row in syn])
    sparse_train = vstack((x_sparse[pos], xs_sparse[syn_pos]), format="csr")
    cache = ROOT / "artifacts/embeddings_e5_base"
    e5_train, e5_val, e5_syn = [np.load(cache / f) for f in
                                ("real_train.npy", "real_val.npy", "synthetic_train.npy")]
    dense_train = np.vstack((e5_train[pos], e5_syn[syn_pos]))
    pca = PCA(n_components=64, random_state=42)
    pca_train = pca.fit_transform(dense_train)
    pca_val = pca.transform(e5_val)
    cut = len(va[SOURCES[0]])
    configs = []
    for c in (0.25, 1.0, 4.0):
        configs.append((f"sparse_svm_c{c}", LinearSVC(C=c, class_weight="balanced",
                                                     max_iter=3000, random_state=42),
                        sparse_train, xv_sparse))
    for c in (1.0, 10.0, 100.0):
        configs.append((f"e5_lr_c{c}", LogisticRegression(C=c, class_weight="balanced",
                                                          max_iter=1000, random_state=42),
                        dense_train, e5_val))
    from catboost import CatBoostClassifier
    configs.append(("e5_catboost_pca64", CatBoostClassifier(
        iterations=350, depth=6, learning_rate=0.05, loss_function="MultiClass",
        thread_count=6, random_seed=42, verbose=False, l2_leaf_reg=5,
        allow_writing_files=False), pca_train, pca_val))
    from lightgbm import LGBMClassifier
    configs.append(("e5_lightgbm_pca64", LGBMClassifier(
        n_estimators=250, num_leaves=15, max_depth=5, learning_rate=0.05,
        class_weight="balanced", random_state=42, verbosity=-1, n_jobs=6), pca_train, pca_val))
    results = []
    for name, model, xx, xv in configs:
        start = time.perf_counter()
        model.fit(xx, labels, sample_weight=weights)
        pred = model.predict(xv).ravel().astype(str)
        end_pred = pred.copy()
        end_pred[~gate_pred] = "not_a_problem"
        item = {"name": name, "seconds": round(time.perf_counter() - start, 2),
                "rss_mb": round(psutil.Process().memory_info().rss / 2**20, 1),
                "head_f1_wa": round(float(f1_score(vy[:cut][vy[:cut] != "not_a_problem"],
                                                   pred[:cut][vy[:cut] != "not_a_problem"],
                                                   labels=sorted(set(vy[:cut][vy[:cut] != "not_a_problem"])),
                                                   average="macro", zero_division=0)), 4),
                "head_f1_tg": round(float(f1_score(vy[cut:][vy[cut:] != "not_a_problem"],
                                                   pred[cut:][vy[cut:] != "not_a_problem"],
                                                   labels=sorted(set(vy[cut:][vy[cut:] != "not_a_problem"])),
                                                   average="macro", zero_division=0)), 4),
                "end_f1_wa": round(float(f1_score(vy[:cut], end_pred[:cut], labels=sorted(set(vy[:cut])), average="macro", zero_division=0)), 4),
                "end_f1_tg": round(float(f1_score(vy[cut:], end_pred[cut:], labels=sorted(set(vy[cut:])), average="macro", zero_division=0)), 4)}
        results.append(item)
        print(json.dumps(item), flush=True)
    report = {"split": "val", "gate": "best frozen; threshold from pooled real val",
              "train_real_positive": len(pos), "train_synthetic_positive": len(syn_pos),
              "pca_components": 64, "results": results}
    Path(__file__).with_name("conditional_heads_val.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
