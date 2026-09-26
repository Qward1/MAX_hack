"""Compare grouping heuristics on weak silver pairs; not incident accuracy."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import read_jsonl  # noqa: E402
from domsignal_ml.grouping import _tokens  # noqa: E402


def main() -> None:
    rows = read_jsonl(Path(sys.argv[1]) / "pairs/dev_pairs.jsonl")
    start = time.perf_counter()
    texts = list(dict.fromkeys(text for row in rows for text in (row["a_text"], row["b_text"])))
    lookup = {text: i for i, text in enumerate(texts)}
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5),
                                  min_df=2, sublinear_tf=True, max_features=100_000)
    x = vectorizer.fit_transform(texts)
    ai = np.array([lookup[row["a_text"]] for row in rows])
    bi = np.array([lookup[row["b_text"]] for row in rows])
    cosine = np.asarray(x[ai].multiply(x[bi]).sum(axis=1)).ravel()
    y = np.array([bool(row["label"]) for row in rows])
    same = np.array([row["a_class"] == row["b_class"] != "not_a_problem" for row in rows])
    conflict = np.array([row["a_entrance"] is not None and row["b_entrance"] is not None
                         and row["a_entrance"] != row["b_entrance"] for row in rows])
    same_entrance = np.array([row["a_entrance"] is not None
                              and row["a_entrance"] == row["b_entrance"] for row in rows])
    gap = np.array([row["gap_hours"] for row in rows])
    lexical = np.array([len(_tokens(row["a_text"]) & _tokens(row["b_text"])) /
                        max(1, len(_tokens(row["a_text"]) | _tokens(row["b_text"])))
                        for row in rows])
    options = {
        "current_conservative": same & ~conflict & (gap <= 24) &
        (same_entrance | ((gap <= 2) & (lexical >= 0.34))),
        "same_class_entrance_24h": same & ~conflict & (gap <= 24),
        "same_class_entrance_6h": same & ~conflict & (gap <= 6),
        "same_class_entrance_2h": same & ~conflict & (gap <= 2),
    }
    for hours in (6, 24):
        for sim in (0.25, 0.4, 0.6):
            options[f"class_{hours}h_cosine_{sim}"] = same & ~conflict & (gap <= hours) & (cosine >= sim)
    results = []
    for name, pred in options.items():
        p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
        results.append({"name": name, "precision": round(float(p), 4),
                        "recall": round(float(r), 4), "f1": round(float(f), 4),
                        "predicted_pairs": int(pred.sum())})
    report = {"kind": "weak_heuristic_pairs", "n": len(rows), "positive": int(y.sum()),
              "unique_texts": len(texts), "seconds": round(time.perf_counter() - start, 1),
              "warning": "Labels use class, day and entrance. These are not human incident labels.",
              "results": results}
    Path(__file__).with_name("compare_pairs.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
