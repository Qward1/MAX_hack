"""Validation-only review-load/quality tradeoff for the new two-stage gate."""
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
    syn = [r for r in load_synthetic(args.data_root) if "gate" in r["annotation"].get("use", [])]
    train_rows = [r for s in SOURCES for r in train[s]]
    val_rows = [r for s in SOURCES for r in val[s]]
    x_train = np.vstack((np.load(ROOT / "artifacts/round3_frozen_rubert/train.npy"),
                         np.load(ROOT / "artifacts/round3_frozen_rubert/synthetic_gate.npy")))
    y_train = np.array([label_of(r, "class") != "not_a_problem" for r in train_rows + syn])
    weights = np.r_[np.ones(len(train_rows)), np.full(len(syn), 0.5)]
    clf = LogisticRegression(C=10, class_weight="balanced", max_iter=1000,
                             random_state=42).fit(x_train, y_train, sample_weight=weights)
    bert_score = clf.predict_proba(np.load(ROOT / "artifacts/round3_frozen_rubert/val.npy"))[:, 1]
    texts = [r["text"] for r in val_rows]
    gate = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    e5 = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    x_gate = hstack((gate["features"].transform(texts), csr_matrix(e5 * gate["scale"])),
                    format="csr")
    old_score = gate["model"].predict_proba(x_gate)[:, 1]
    new_score = 0.75 * old_score + 0.25 * bert_score
    light = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_prob = light["classes"].predict_proba(light["features"].transform(texts))
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")["class_logits"].copy()
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse = np.zeros_like(bert_prob)
    for col, name in enumerate(light["classes"].classes_):
        sparse[:, checkpoint["classes"][name]] = sparse_prob[:, col]
    names = np.array(list(checkpoint["classes"]))
    raw_class = names[((bert_prob + sparse) / 2).argmax(axis=1)]
    gold = np.array([label_of(r, "class") for r in val_rows])
    positive = gold != "not_a_problem"
    cut = len(val[SOURCES[0]])
    report = {"split": "reused_val", "warning": "Thresholds selected on the same val; exploratory only.",
              "policies": {}}
    for name, score in (("old_gate", old_score), ("new_gate", new_score)):
        variants = {}
        for target in (0.70, 0.80, 0.90):
            threshold = gate_threshold(positive, score, target)["threshold"]
            final = raw_class.copy()
            accepted = score >= threshold
            final[~accepted] = "not_a_problem"
            p, r, _, _ = precision_recall_fscore_support(positive, accepted,
                                                         average="binary", zero_division=0)
            source = {}
            for source_name, sl in ((SOURCES[0], slice(0, cut)),
                                    (SOURCES[1], slice(cut, None))):
                source[source_name] = round(float(f1_score(gold[sl], final[sl],
                                                          labels=sorted(set(gold[sl])),
                                                          average="macro", zero_division=0)), 4)
            variants[str(target)] = {"threshold": round(float(threshold), 4),
                                     "routed_to_review": int(accepted.sum()),
                                     "review_share": round(float(accepted.mean()), 4),
                                     "gate_precision": round(float(p), 4),
                                     "gate_recall": round(float(r), 4),
                                     "source_macro_f1": source,
                                     "mean_macro_f1": round(float(np.mean(list(source.values()))), 4)}
        report["policies"][name] = variants
    output = Path(__file__).with_name("round3_threshold_tradeoff.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
