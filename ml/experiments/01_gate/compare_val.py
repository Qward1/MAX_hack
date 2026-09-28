"""Compare gate configurations on real validation only; do not inspect test."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import hstack, vstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402


def main() -> None:
    data = Path(sys.argv[1])
    train = load_real(data, "train")
    val = load_real(data, "val")
    real = [row for source in SOURCES for row in train[source]]
    validation = [row for source in SOURCES for row in val[source]]
    texts = [row["text"].lower().replace("ё", "е") for row in real]
    val_texts = [row["text"].lower().replace("ё", "е") for row in validation]
    syn = [row for row in load_synthetic(data) if "gate" in row["annotation"].get("use", [])]
    syn_texts = [row["text"].lower().replace("ё", "е") for row in syn]
    y = np.array([label_of(row, "class") != "not_a_problem" for row in real])
    vy = np.array([label_of(row, "class") != "not_a_problem" for row in validation])
    sy = np.array([label_of(row, "class") != "not_a_problem" for row in syn])
    config = [
        ("baseline", (2, 5), (1, 2)),
        ("char_3_5", (3, 5), (1, 2)),
        ("char_2_6", (2, 6), (1, 2)),
    ]
    results = []
    for name, char_range, word_range in config:
        start = time.perf_counter()
        char = TfidfVectorizer(analyzer="char_wb", ngram_range=char_range,
                               min_df=2, sublinear_tf=True, dtype=np.float32)
        word = TfidfVectorizer(ngram_range=word_range,
                               min_df=2, sublinear_tf=True, dtype=np.float32)
        x = hstack((char.fit_transform(texts), word.fit_transform(texts)), format="csr")
        xv = hstack((char.transform(val_texts), word.transform(val_texts)), format="csr")
        xs = hstack((char.transform(syn_texts), word.transform(syn_texts)), format="csr")
        for c in (0.5, 1.0, 4.0, 16.0):
            for include_syn in (False, True):
                xx = vstack((x, xs), format="csr") if include_syn else x
                yy = np.concatenate((y, sy)) if include_syn else y
                model = LogisticRegression(C=c, max_iter=1000, solver="liblinear",
                                           class_weight="balanced", random_state=42).fit(xx, yy)
                score = model.predict_proba(xv)[:, 1]
                result = {"features": name, "c": c, "synthetic_gate": include_syn,
                          "n_features": x.shape[1], "n_train": len(yy),
                          "val_ap_pooled": round(float(average_precision_score(vy, score)), 4),
                          "val_ap_wa": round(float(average_precision_score(
                              vy[:len(val[SOURCES[0]])], score[:len(val[SOURCES[0]])])), 4),
                          "val_ap_tg": round(float(average_precision_score(
                              vy[len(val[SOURCES[0]]):], score[len(val[SOURCES[0]]):])), 4),
                          "elapsed_seconds": round(time.perf_counter() - start, 2)}
                results.append(result)
                print(json.dumps(result), flush=True)
    out = Path(__file__).with_name("compare_val.json")
    out.write_text(json.dumps({"seed": 42, "split": "val", "results": results}, indent=2) + "\n",
                   encoding="utf-8")


if __name__ == "__main__":
    main()
