"""Final held-out test for the validation-selected E5 gate + ruBERT class model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np
import torch
from scipy.sparse import csr_matrix, hstack

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.metrics import binary_report, class_report  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main():
    data = Path(sys.argv[1])
    test = load_real(data, "test")
    rows = [r for source in SOURCES for r in test[source]]
    texts = [r["text"] for r in rows]
    gold = np.array([label_of(r, "class") for r in rows])
    e5 = np.load(ROOT / "artifacts/embeddings_e5_base/real_test.npy")
    logits = np.load(ROOT / "artifacts/encoder_base_positive_test_logits.npz")["class_logits"]
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    names = np.array(list(checkpoint["classes"]))
    class_pred = names[logits.argmax(axis=1)]
    hybrid = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    x = hstack((hybrid["features"].transform(texts), csr_matrix(e5 * hybrid["scale"])),
               format="csr")
    score = hybrid["model"].predict_proba(x)[:, 1]
    pred = class_pred.copy()
    pred[score < hybrid["threshold"]] = "not_a_problem"
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_score = bundle["gate"].predict_proba(bundle["gate_features"].transform(texts))[:, 1]
    sparse_class = bundle["classes"].predict(bundle["features"].transform(texts))
    alternatives = {}
    for name, s, threshold, cls in (
        ("sparse_gate_bert_class", sparse_score, bundle["gate_threshold"], class_pred),
        ("hybrid_gate_sparse_class", score, hybrid["threshold"], sparse_class),
    ):
        p = cls.copy()
        p[s < threshold] = "not_a_problem"
        alternatives[name] = p
    report = {"split": "test", "selected_on": "real val", "gate_scale": hybrid["scale"],
              "threshold": hybrid["threshold"], "class_checkpoint_epoch": checkpoint["epoch"],
              "sources": {}}
    cursor = 0
    compact = {}
    for source in SOURCES:
        stop = cursor + len(test[source])
        sub = slice(cursor, stop)
        rows_sub = test[source]
        labels = gold[sub]
        groups = [str(r.get("family_id") or r.get("thread_id") or r["id"]) for r in rows_sub]
        is_problem = labels != "not_a_problem"
        gate = binary_report(is_problem, score[sub], hybrid["threshold"], groups)
        classes = class_report(labels, pred[sub], groups)
        head = class_report(labels[is_problem], class_pred[sub][is_problem],
                            [g for g, flag in zip(groups, is_problem) if flag])
        report["sources"][source] = {
            "gate": gate, "end_to_end_classes": classes,
            "class_head_on_gold_problems": head,
            "exploratory_alternatives_end_macro_f1": {
                name: class_report(labels, p[sub], groups)["macro_f1"]
                for name, p in alternatives.items()},
        }
        compact[source] = {"n": len(rows_sub), "gold_problems": int(is_problem.sum()),
                           "gate_ap": gate["ap"], "gate_ap_ci95": gate["ap_ci95_group_bootstrap"],
                           "gate_precision": gate["precision_at_val_threshold"],
                           "gate_recall": gate["recall_at_val_threshold"],
                           "end_macro_f1": classes["macro_f1"],
                           "end_macro_f1_ci95": classes["macro_f1_ci95_group_bootstrap"],
                           "head_macro_f1": head["macro_f1"]}
        cursor = stop
    out = Path(__file__).with_name("hybrid_base_test.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sources": compact, "result_file": str(out)}))


if __name__ == "__main__":
    main()
