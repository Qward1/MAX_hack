"""Learning curve for real data only, using validation; test is never read."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.features import TextFeatures  # noqa: E402


def main() -> None:
    data = Path(sys.argv[1])
    train = load_real(data, "train")
    val = load_real(data, "val")
    real = [row for source in SOURCES for row in train[source]]
    validation = [row for source in SOURCES for row in val[source]]
    vy = np.array([label_of(row, "class") != "not_a_problem" for row in validation])
    families: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(real):
        families[str(row.get("family_id") or row.get("thread_id") or row["id"])].append(i)
    keys = np.array(list(families))
    result = []
    for fraction in (0.10, 0.25, 0.50, 1.0):
        for seed in (13, 29, 42) if fraction < 1 else (42,):
            rng = np.random.default_rng(seed)
            selected = rng.choice(keys, size=max(2, round(len(keys) * fraction)), replace=False)
            subset = [real[i] for key in selected for i in families[str(key)]]
            y = np.array([label_of(row, "class") != "not_a_problem" for row in subset])
            features = TextFeatures.baseline()
            x = features.fit_transform([row["text"] for row in subset])
            xv = features.transform([row["text"] for row in validation])
            model = LogisticRegression(C=16, solver="liblinear", max_iter=1000,
                                       class_weight="balanced", random_state=42).fit(x, y)
            score = model.predict_proba(xv)[:, 1]
            cut = len(val[SOURCES[0]])
            item = {
                "fraction_families": fraction, "seed": seed, "n_train": len(subset),
                "n_train_positives": int(y.sum()),
                "ap_wa_val": round(float(average_precision_score(vy[:cut], score[:cut])), 4),
                "ap_tg_val": round(float(average_precision_score(vy[cut:], score[cut:])), 4),
            }
            result.append(item)
            print(json.dumps(item), flush=True)
    Path(__file__).with_name("learning_curve.json").write_text(
        json.dumps({"split": "val", "training": "real only", "results": result}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
