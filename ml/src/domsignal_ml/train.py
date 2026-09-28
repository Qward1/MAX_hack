"""Train local classifiers on train; choose operating points on val only."""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import psutil
import sklearn
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve

from .data import SOURCES, label_of, load_real, load_safety, load_synthetic, positives
from .features import TextFeatures

SEED = 42


def gate_threshold(y: np.ndarray, score: np.ndarray, target_precision: float = 0.80) -> dict[str, float]:
    precision, recall, thresholds = precision_recall_curve(y, score)
    support = np.array([(score >= t).sum() for t in thresholds])
    valid = np.where((precision[:-1] >= target_precision) & (support >= 20))[0]
    if not len(valid):
        return {"threshold": 1.0, "val_precision": 1.0, "val_recall": 0.0}
    index = int(valid[np.argmax(recall[valid])])
    return {
        "threshold": float(thresholds[index]),
        "val_precision": float(precision[index]),
        "val_recall": float(recall[index]),
    }


def safety_threshold(y: np.ndarray, score: np.ndarray, max_fpr: float = 0.05) -> dict[str, float]:
    thresholds = np.unique(score)
    best = (1.0, 0.0, 0.0)
    for threshold in thresholds:
        pred = score >= threshold
        fpr = float(pred[~y].mean())
        recall = float(pred[y].mean())
        if fpr <= max_fpr and recall >= best[1]:
            best = (float(threshold), recall, fpr)
    return {"threshold": best[0], "val_recall": best[1], "val_fpr": best[2]}


def train(data_root: Path, artifact: Path, variant: str = "real") -> dict[str, Any]:
    if variant not in {"real", "synthetic_classes", "synthetic_gate_classes", "best"}:
        raise ValueError("unknown variant")
    start = time.perf_counter()
    real_train = load_real(data_root, "train")
    real_val = load_real(data_root, "val")
    train_rows = [row for source in SOURCES for row in real_train[source]]
    val_rows = [row for source in SOURCES for row in real_val[source]]
    features = TextFeatures.create()
    x_real = features.fit_transform([row["text"] for row in train_rows])
    gate_features = TextFeatures.baseline() if variant == "best" else features
    x_gate_real = gate_features.fit_transform([row["text"] for row in train_rows]) if variant == "best" else x_real
    y_gate = np.array([label_of(row, "class") != "not_a_problem" for row in train_rows])
    x_gate, gate_y = x_gate_real, y_gate
    synthetic_count = 0
    synthetic_gate_count = 0
    if variant != "real":
        synthetic = load_synthetic(data_root)
        synthetic_count = len(synthetic)
        from scipy.sparse import vstack
        syn_x = features.transform([row["text"] for row in synthetic])
        if variant in {"synthetic_gate_classes", "best"}:
            accepted = [i for i, row in enumerate(synthetic) if "gate" in row["annotation"].get("use", [])]
            gate_syn_x = gate_features.transform([synthetic[i]["text"] for i in accepted]) if variant == "best" else syn_x[accepted]
            x_gate = vstack((x_gate, gate_syn_x), format="csr")
            gate_y = np.concatenate((
                gate_y,
                np.array([label_of(synthetic[i], "class") != "not_a_problem" for i in accepted]),
            ))
            synthetic_gate_count = len(accepted)
    gate = LogisticRegression(solver="liblinear", C=16.0 if variant == "best" else 1.0, max_iter=1000,
                              class_weight="balanced", random_state=SEED)
    gate.fit(x_gate, gate_y)
    x_class = x_real[y_gate]
    class_rows = positives(train_rows)
    if variant != "real":
        from scipy.sparse import vstack
        syn_positive = [i for i, row in enumerate(synthetic) if label_of(row, "class") != "not_a_problem"]
        x_class = vstack((x_class, syn_x[syn_positive]), format="csr")
        class_rows += [synthetic[i] for i in syn_positive]
    class_y = np.array([label_of(row, "class") for row in class_rows])
    classes = SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=1000, tol=1e-3,
                            class_weight="balanced", average=True, random_state=SEED)
    class_weights = np.ones(len(class_y))
    if variant != "real":
        class_weights[len(positives(train_rows)):] = 0.5
    classes.fit(x_class, class_y, sample_weight=class_weights)
    utterance = SGDClassifier(loss="log_loss", alpha=1e-5, max_iter=1000, tol=1e-3,
                              class_weight="balanced", average=True, random_state=SEED)
    utterance.fit(x_real[y_gate], np.array([label_of(row, "utterance") for row in positives(train_rows)]))

    safety_train = load_safety(data_root, "train")
    safety_val = load_safety(data_root, "val")
    safety = LogisticRegression(solver="liblinear", C=1.0, max_iter=250,
                                class_weight="balanced", random_state=SEED)
    safety.fit(features.transform([row["text"] for row in safety_train]),
               np.array([bool(row["emergency"]) for row in safety_train]))

    x_val = gate_features.transform([row["text"] for row in val_rows])
    val_gate_y = np.array([label_of(row, "class") != "not_a_problem" for row in val_rows])
    gate_op = gate_threshold(val_gate_y, gate.predict_proba(x_val)[:, 1])
    val_safety_y = np.array([bool(row["emergency"]) for row in safety_val])
    safety_op = safety_threshold(
        val_safety_y,
        safety.predict_proba(features.transform([row["text"] for row in safety_val]))[:, 1],
    )
    bundle = {
        "version": "v1", "variant": variant, "seed": SEED, "features": features,
        "gate_features": gate_features,
        "gate": gate, "classes": classes, "utterance": utterance, "safety": safety,
        "gate_threshold": gate_op["threshold"], "safety_threshold": safety_op["threshold"],
        "data_version": "v3.0", "class_labels": list(classes.classes_),
    }
    artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, artifact, compress=3)
    result = {
        "variant": variant, "seed": SEED, "data_version": "v3.0",
        "real_train": {source: len(real_train[source]) for source in SOURCES},
        "real_val": {source: len(real_val[source]) for source in SOURCES},
        "synthetic_train": synthetic_count, "synthetic_gate_eligible": synthetic_gate_count,
        "gate_val_ap_pooled": float(average_precision_score(val_gate_y, gate.predict_proba(x_val)[:, 1])),
        "gate_operating_point": gate_op, "safety_operating_point": safety_op,
        "train_seconds": round(time.perf_counter() - start, 2),
        "artifact_bytes": artifact.stat().st_size,
        "rss_mb_after": round(psutil.Process().memory_info().rss / 2**20, 1),
        "cpu": platform.processor(), "logical_cores": psutil.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 2),
        "python": platform.python_version(), "sklearn": sklearn.__version__,
        "feature_count": x_real.shape[1], "gate_feature_count": x_gate_real.shape[1],
    }
    return result


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
