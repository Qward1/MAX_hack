"""Late feature fusion: sparse n-grams + cached E5; validation only."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack, vstack
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import average_precision_score, f1_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.features import TextFeatures  # noqa: E402
from domsignal_ml.train import gate_threshold  # noqa: E402


def main():
    data = Path(sys.argv[1])
    tr = load_real(data, "train")
    va = load_real(data, "val")
    train = [r for source in SOURCES for r in tr[source]]
    val = [r for source in SOURCES for r in va[source]]
    syn = load_synthetic(data)
    cache = ROOT / "artifacts/embeddings_e5_base"
    e_tr, e_va, e_sy = [np.load(cache / name) for name in
                         ("real_train.npy", "real_val.npy", "synthetic_train.npy")]
    assert len(e_tr) == len(train) and len(e_va) == len(val) and len(e_sy) == len(syn)
    real_y = np.array([label_of(r, "class") for r in train])
    val_y = np.array([label_of(r, "class") for r in val])
    syn_y = np.array([label_of(r, "class") for r in syn])
    pos = np.where(real_y != "not_a_problem")[0]
    syn_pos = np.where(syn_y != "not_a_problem")[0]
    eligible = np.array([i for i, r in enumerate(syn) if "gate" in r["annotation"].get("use", [])])
    gate_features = TextFeatures.baseline()
    g_tr = gate_features.fit_transform([r["text"] for r in train])
    g_va = gate_features.transform([r["text"] for r in val])
    g_sy = gate_features.transform([r["text"] for r in syn])
    class_features = TextFeatures.create()
    c_tr = class_features.fit_transform([r["text"] for r in train])
    c_va = class_features.transform([r["text"] for r in val])
    c_sy = class_features.transform([r["text"] for r in syn])
    cut = len(va[SOURCES[0]])
    results = []
    for scale in (0.25, 0.5, 1.0, 2.0):
        start = time.perf_counter()
        gg = vstack((hstack((g_tr, csr_matrix(e_tr * scale)), format="csr"),
                     hstack((g_sy[eligible], csr_matrix(e_sy[eligible] * scale)), format="csr")), format="csr")
        gval = hstack((g_va, csr_matrix(e_va * scale)), format="csr")
        gate_y = np.r_[real_y != "not_a_problem", syn_y[eligible] != "not_a_problem"]
        gate = LogisticRegression(C=16, solver="liblinear", max_iter=1000,
                                  class_weight="balanced", random_state=42).fit(gg, gate_y)
        gate_score = gate.predict_proba(gval)[:, 1]
        threshold = gate_threshold(val_y != "not_a_problem", gate_score)["threshold"]
        cc = vstack((hstack((c_tr[pos], csr_matrix(e_tr[pos] * scale)), format="csr"),
                     hstack((c_sy[syn_pos], csr_matrix(e_sy[syn_pos] * scale)), format="csr")), format="csr")
        cval = hstack((c_va, csr_matrix(e_va * scale)), format="csr")
        class_y = np.r_[real_y[pos], syn_y[syn_pos]]
        class_weights = np.r_[np.ones(len(pos)), np.full(len(syn_pos), 0.5)]
        classifier = SGDClassifier(loss="log_loss", alpha=1e-5, class_weight="balanced",
                                   max_iter=1000, average=True, random_state=42).fit(
                                       cc, class_y, sample_weight=class_weights)
        pred = classifier.predict(cval)
        pred[gate_score < threshold] = "not_a_problem"
        item = {"scale": scale, "seconds": round(time.perf_counter() - start, 2),
                "gate_val_ap_wa": round(float(average_precision_score(val_y[:cut] != "not_a_problem",
                                                                       gate_score[:cut])), 4),
                "gate_val_ap_tg": round(float(average_precision_score(val_y[cut:] != "not_a_problem",
                                                                       gate_score[cut:])), 4),
                "end_macro_f1_wa": round(float(f1_score(val_y[:cut], pred[:cut], labels=sorted(set(val_y[:cut])), average="macro", zero_division=0)), 4),
                "end_macro_f1_tg": round(float(f1_score(val_y[cut:], pred[cut:], labels=sorted(set(val_y[cut:])), average="macro", zero_division=0)), 4)}
        results.append(item)
        print(json.dumps(item), flush=True)
    Path(__file__).with_name("hybrid_val.json").write_text(
        json.dumps({"split": "val", "results": results}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
