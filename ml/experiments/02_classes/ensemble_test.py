"""Held-out evaluation of validation-selected 50/50 class ensemble."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import torch
from scipy.sparse import csr_matrix, hstack
from sklearn.metrics import average_precision_score, f1_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.metrics import binary_report, class_report  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main() -> None:
    data = load_real(Path(sys.argv[1]), "test")
    rows = [row for source in SOURCES for row in data[source]]
    texts = [row["text"] for row in rows]
    gold = np.array([label_of(row, "class") for row in rows])
    e5 = np.load(ROOT / "artifacts/embeddings_e5_base/real_test.npy")
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    names = list(checkpoint["classes"])
    logits = np.load(ROOT / "artifacts/encoder_base_positive_test_logits.npz")["class_logits"]
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    sparse = bundle["classes"]
    sparse_prob = sparse.predict_proba(bundle["features"].transform(texts))
    sparse_aligned = np.zeros_like(bert_prob)
    for i, name in enumerate(sparse.classes_):
        sparse_aligned[:, names.index(name)] = sparse_prob[:, i]
    class_pred = np.array(names)[(0.5 * bert_prob + 0.5 * sparse_aligned).argmax(axis=1)]
    hybrid = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    x = hstack((hybrid["features"].transform(texts),
                csr_matrix(e5 * hybrid["scale"])), format="csr")
    gate_score = hybrid["model"].predict_proba(x)[:, 1]
    pred = class_pred.copy()
    pred[gate_score < hybrid["threshold"]] = "not_a_problem"
    light_score = bundle["gate"].predict_proba(
        bundle["gate_features"].transform(texts))[:, 1]
    light_pred = sparse.predict(bundle["features"].transform(texts))
    light_pred[light_score < bundle["gate_threshold"]] = "not_a_problem"
    report = {"split": "test", "selected_on": "real val", "class_sparse_weight": 0.5,
              "gate_scale": 1.0, "sources": {}}
    cursor = 0
    compact = {}
    for source in SOURCES:
        end = cursor + len(data[source])
        sl = slice(cursor, end)
        labels = gold[sl]
        positives = labels != "not_a_problem"
        groups = [str(r.get("family_id") or r.get("thread_id") or r["id"])
                  for r in data[source]]
        gate = binary_report(positives, gate_score[sl], hybrid["threshold"], groups)
        classes = class_report(labels, pred[sl], groups)
        head = class_report(labels[positives], class_pred[sl][positives],
                            [g for g, flag in zip(groups, positives) if flag])
        group_rows = {}
        for i, group in enumerate(groups):
            group_rows.setdefault(group, []).append(i)
        units = list(group_rows.values())
        rng = np.random.default_rng(42)
        ap_differences = []
        f1_differences = []
        observed_labels = sorted(set(labels))
        for _ in range(300):
            sampled = rng.integers(0, len(units), len(units))
            idx = np.array([i for unit in sampled for i in units[unit]], dtype=int)
            yy = positives[idx]
            if yy.any():
                ap_differences.append(average_precision_score(yy, gate_score[sl][idx])
                                      - average_precision_score(yy, light_score[sl][idx]))
            f1_differences.append(f1_score(labels[idx], pred[sl][idx],
                labels=observed_labels, average="macro", zero_division=0)
                - f1_score(labels[idx], light_pred[sl][idx],
                labels=observed_labels, average="macro", zero_division=0))
        paired = {"gate_ap_delta": round(float(average_precision_score(positives, gate_score[sl])
                       - average_precision_score(positives, light_score[sl])), 4),
                  "gate_ap_delta_ci95": [round(float(x), 4) for x in
                                          np.quantile(ap_differences, [0.025, 0.975])],
                  "end_macro_f1_delta": round(float(classes["macro_f1"]
                       - f1_score(labels, light_pred[sl], labels=observed_labels,
                                  average="macro", zero_division=0)), 4),
                  "end_macro_f1_delta_ci95": [round(float(x), 4) for x in
                                              np.quantile(f1_differences, [0.025, 0.975])]}
        report["sources"][source] = {"gate": gate,
            "end_to_end_classes_all_messages": classes,
            "classes_on_true_problems": head,
            "paired_difference_from_light": paired}
        compact[source] = {"end_macro_f1": classes["macro_f1"],
                           "end_macro_f1_ci95": classes["macro_f1_ci95_group_bootstrap"],
                           "head_macro_f1": head["macro_f1"], "paired": paired}
        cursor = end
    output = Path(__file__).with_name("ensemble_test.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(compact))


if __name__ == "__main__":
    main()
