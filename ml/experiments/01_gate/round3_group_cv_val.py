"""Group-fold threshold calibration for frozen ruBERT gate, on reused val.

This checks threshold stability. Model checkpoints were already selected with val,
so the folds are not an independent test of model quality.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import torch
from scipy.sparse import csr_matrix, hstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedGroupKFold

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402
from domsignal_ml.train import gate_threshold  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    train = load_real(args.data_root, "train")
    val = load_real(args.data_root, "val")
    syn = [r for r in load_synthetic(args.data_root)
           if "gate" in r["annotation"].get("use", [])]
    train_rows = [r for s in SOURCES for r in train[s]]
    val_rows = [r for s in SOURCES for r in val[s]]
    x_train = np.vstack((np.load(ROOT / "artifacts/round3_frozen_rubert/train.npy"),
                         np.load(ROOT / "artifacts/round3_frozen_rubert/synthetic_gate.npy")))
    x_val = np.load(ROOT / "artifacts/round3_frozen_rubert/val.npy")
    y_train = np.array([label_of(r, "class") != "not_a_problem" for r in train_rows + syn])
    weights = np.r_[np.ones(len(train_rows)), np.full(len(syn), 0.5)]
    bert_gate = LogisticRegression(C=10, max_iter=1000, class_weight="balanced",
                                   random_state=42).fit(x_train, y_train,
                                                        sample_weight=weights)
    bert_score = bert_gate.predict_proba(x_val)[:, 1]
    texts = [r["text"] for r in val_rows]
    hybrid = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    embeddings = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    x_hybrid = hstack((hybrid["features"].transform(texts),
                       csr_matrix(embeddings * hybrid["scale"])), format="csr")
    old_score = hybrid["model"].predict_proba(x_hybrid)[:, 1]
    new_score = 0.75 * old_score + 0.25 * bert_score
    light = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_prob = light["classes"].predict_proba(light["features"].transform(texts))
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")["class_logits"].copy()
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_class = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse = np.zeros_like(bert_class)
    for col, name in enumerate(light["classes"].classes_):
        sparse[:, checkpoint["classes"][name]] = sparse_prob[:, col]
    names = np.array(list(checkpoint["classes"]))
    raw_class = names[((bert_class + sparse) / 2).argmax(axis=1)]
    gold = np.array([label_of(r, "class") for r in val_rows])
    positive = gold != "not_a_problem"
    groups = np.array([f"{r['source']}:{r['family_id']}" for r in val_rows])
    folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    report = {"split": "reused_val_group_5fold", "results": {}}
    cut = len(val[SOURCES[0]])
    for name, score in (("existing_hybrid", old_score),
                        ("hybrid_plus_frozen_rubert_c10_w025", new_score)):
        final = np.full(len(gold), "not_a_problem", dtype=object)
        thresholds = []
        for calibration, audit in folds.split(np.zeros(len(gold)), positive, groups):
            op = gate_threshold(positive[calibration], score[calibration])
            thresholds.append(round(op["threshold"], 4))
            accepted = score[audit] >= op["threshold"]
            final[audit] = np.where(accepted, raw_class[audit], "not_a_problem")
        source_results = {}
        for source, sl in ((SOURCES[0], slice(0, cut)),
                           (SOURCES[1], slice(cut, None))):
            pred_pos = final[sl] != "not_a_problem"
            p, r, _, _ = precision_recall_fscore_support(
                positive[sl], pred_pos, average="binary", zero_division=0)
            source_results[source] = {
                "macro_f1": round(float(f1_score(gold[sl], final[sl],
                                                 labels=sorted(set(gold[sl])),
                                                 average="macro", zero_division=0)), 4),
                "gate_precision": round(float(p), 4),
                "gate_recall": round(float(r), 4),
            }
        report["results"][name] = {"thresholds": thresholds, "sources": source_results,
                                   "mean_macro_f1": round(float(np.mean([
                                       source_results[s]["macro_f1"] for s in SOURCES])), 4)}
    output = Path(__file__).with_name("round3_group_cv_val.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
