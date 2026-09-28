"""Aggregate evaluation with group bootstrap; no message text in reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sklearn.metrics import (
    average_precision_score, f1_score, precision_recall_curve,
    precision_recall_fscore_support,
)

from .data import SOURCES, label_of, load_real, load_safety, read_jsonl
from .grouping import _tokens
from .utterance import utterance_of
from .safety import emergency_from_score


def _ci(values: list[float]) -> list[float] | None:
    if not values:
        return None
    return [round(float(np.quantile(values, 0.025)), 4),
            round(float(np.quantile(values, 0.975)), 4)]


def _bootstrap(y: np.ndarray, pred: np.ndarray, groups: list[str],
               metric: Callable[[np.ndarray, np.ndarray], float],
               repeats: int = 300, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    by_group: dict[str, list[int]] = {}
    for i, group in enumerate(groups):
        by_group.setdefault(group, []).append(i)
    units = list(by_group.values())
    values: list[float] = []
    for _ in range(repeats):
        sampled = rng.integers(0, len(units), len(units))
        index = np.array([i for k in sampled for i in units[k]], dtype=int)
        try:
            values.append(float(metric(y[index], pred[index])))
        except ValueError:
            continue
    return values


def binary_report(y: np.ndarray, score: np.ndarray, threshold: float,
                  groups: list[str]) -> dict[str, Any]:
    pred = score >= threshold
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
    precision, recall, thresholds = precision_recall_curve(y, score)
    valid = np.where(precision[:-1] >= 0.9)[0]
    curve_recall_at_p90 = float(np.max(recall[valid])) if len(valid) else 0.0
    ap = float(average_precision_score(y, score))
    return {
        "n": len(y), "positives": int(y.sum()), "prevalence": round(float(y.mean()), 4),
        "ap": round(ap, 4),
        "ap_ci95_group_bootstrap": _ci(_bootstrap(
            y, score, groups, lambda yy, ss: average_precision_score(yy, ss))),
        "threshold_from_val": round(float(threshold), 4),
        "precision_at_val_threshold": round(float(p), 4),
        "recall_at_val_threshold": round(float(r), 4),
        "f1_at_val_threshold": round(float(f), 4),
        "curve_max_recall_at_precision_0_90": round(curve_recall_at_p90, 4),
        "false_positives": int(((~y) & pred).sum()),
        "false_negatives": int((y & (~pred)).sum()),
        "pr_curve": {
            "precision": [round(float(v), 5) for v in precision],
            "recall": [round(float(v), 5) for v in recall],
            "thresholds": [round(float(v), 5) for v in thresholds],
        },
    }


def class_report(y: np.ndarray, pred: np.ndarray, groups: list[str]) -> dict[str, Any]:
    labels = sorted(set(y.tolist()))
    p, r, f, n = precision_recall_fscore_support(
        y, pred, labels=labels, zero_division=0)
    macro = float(f1_score(y, pred, labels=labels, average="macro", zero_division=0))
    boot = _bootstrap(
        y, pred, groups,
        lambda yy, pp: f1_score(yy, pp, labels=labels, average="macro", zero_division=0),
        repeats=200,
    )
    return {
        "n": len(y), "labels_in_test": len(labels), "macro_f1": round(macro, 4),
        "macro_f1_ci95_group_bootstrap": _ci(boot),
        "per_class": {
            label: {"support": int(n[i]), "precision": round(float(p[i]), 4),
                    "recall": round(float(r[i]), 4), "f1": round(float(f[i]), 4)}
            for i, label in enumerate(labels)
        },
    }


def safety_report(y: np.ndarray, score: np.ndarray, threshold: float) -> dict[str, Any]:
    pred = score >= threshold
    tp = int((y & pred).sum())
    fp = int(((~y) & pred).sum())
    positives = int(y.sum())
    negatives = int((~y).sum())
    rng = np.random.default_rng(42)
    recalls = []
    for _ in range(300):
        index = rng.integers(0, len(y), len(y))
        if y[index].any():
            recalls.append(float(pred[index][y[index]].mean()))
    return {
        "n": len(y), "emergencies": positives,
        "ap": round(float(average_precision_score(y, score)), 4),
        "threshold_from_val": round(float(threshold), 4),
        "recall": round(tp / positives, 4) if positives else None,
        "recall_ci95_bootstrap": _ci(recalls),
        "false_alarm_rate": round(fp / negatives, 4) if negatives else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "false_negatives": positives - tp, "false_positives": fp,
    }


def evaluate(bundle: dict[str, Any], data_root: Path, split: str = "test") -> dict[str, Any]:
    real = load_real(data_root, split)
    results: dict[str, Any] = {
        "artifact_variant": bundle["variant"], "dataset_version": "v3.0",
        "split": split, "thresholds_selected_on": "pooled real val / safety val",
        "sources": {},
    }
    for source in SOURCES:
        rows = real[source]
        x = bundle["features"].transform([row["text"] for row in rows])
        gx = bundle.get("gate_features", bundle["features"]).transform([row["text"] for row in rows])
        y = np.array([label_of(row, "class") != "not_a_problem" for row in rows])
        score = bundle["gate"].predict_proba(gx)[:, 1]
        emergency_score = bundle["safety"].predict_proba(x)[:, 1]
        final_pred = (score >= bundle["gate_threshold"]) | (
            emergency_score >= bundle["safety_threshold"])
        final_p, final_r, final_f, _ = precision_recall_fscore_support(
            y, final_pred, average="binary", zero_division=0)
        groups = [str(row.get("family_id") or row.get("thread_id") or row["id"]) for row in rows]
        positive_index = np.where(y)[0]
        all_class_pred = bundle["classes"].predict(x)
        all_class_pred[score < bundle["gate_threshold"]] = "not_a_problem"
        all_class_gold = np.array([label_of(row, "class") for row in rows])
        class_y = np.array([label_of(rows[i], "class") for i in positive_index])
        class_pred = bundle["classes"].predict(x[positive_index])
        utterance_y = np.array([label_of(rows[i], "utterance") for i in positive_index])
        utterance_pred = np.array([utterance_of(rows[i]["text"], str(model_label))
                                   for i, model_label in zip(positive_index, bundle["utterance"].predict(x[positive_index]))])
        results["sources"][source] = {
            "gate": binary_report(y, score, bundle["gate_threshold"], groups),
            "alternative_problem_with_emergency_override": {
                "precision": round(float(final_p), 4),
                "recall": round(float(final_r), 4),
                "f1": round(float(final_f), 4),
                "false_positives": int(((~y) & final_pred).sum()),
                "false_negatives": int((y & (~final_pred)).sum()),
            },
            "classes_on_true_problems": class_report(
                class_y, class_pred, [groups[i] for i in positive_index]),
            "end_to_end_classes_all_messages": class_report(
                all_class_gold, all_class_pred, groups),
            "utterance_macro_f1_on_true_problems": round(float(f1_score(
                utterance_y, utterance_pred, average="macro", zero_division=0)), 4),
        }
    safety_rows = load_safety(data_root, split)
    if safety_rows:
        safety_score = bundle["safety"].predict_proba(
            bundle["features"].transform([row["text"] for row in safety_rows]))[:, 1]
        safety_y = np.array([bool(row["emergency"]) for row in safety_rows])
        results["safety"] = safety_report(safety_y, safety_score,
                                           bundle["safety_threshold"])
        results["safety"]["origin_counts"] = {
            "real": sum(row["origin"] == "real" for row in safety_rows),
            "synthetic": sum(row["origin"] == "synthetic" for row in safety_rows),
        }
    return results


def weak_pair_report(data_root: Path) -> dict[str, Any]:
    rows = read_jsonl(data_root / "pairs" / "dev_pairs.jsonl")
    y = np.array([bool(row["label"]) for row in rows])
    pred = []
    for row in rows:
        same_class = row["a_class"] == row["b_class"] != "not_a_problem"
        conflict = (row["a_entrance"] is not None and row["b_entrance"] is not None
                    and row["a_entrance"] != row["b_entrance"])
        a, b = _tokens(row["a_text"]), _tokens(row["b_text"])
        sim = len(a & b) / len(a | b) if a | b else 0.0
        same_entrance = (row["a_entrance"] is not None
                         and row["a_entrance"] == row["b_entrance"])
        pred.append(bool(same_class and not conflict and row["gap_hours"] <= 24
                         and (same_entrance or
                              (row["gap_hours"] <= 2 and sim >= 0.34))))
    p, r, f, _ = precision_recall_fscore_support(
        y, np.array(pred), average="binary", zero_division=0)
    return {
        "n": len(y), "positives": int(y.sum()), "precision": round(float(p), 4),
        "recall": round(float(r), 4), "f1": round(float(f), 4),
        "warning": "Weak heuristic pairs, partly defined by gold class/time. "
                   "This is not incident-level accuracy; no human incident gold exists.",
    }


def save_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
