"""Retrospective error decomposition; oracle rows are ceilings, not models.

The test was already viewed in prior rounds. Nothing is tuned here and no
message text is written to the report.
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
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data = load_real(args.data_root, "test")
    rows = [r for source in SOURCES for r in data[source]]
    texts = [r["text"] for r in rows]
    gold = np.array([label_of(r, "class") for r in rows])
    gate = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    e5 = np.load(ROOT / "artifacts/embeddings_e5_base/real_test.npy")
    gx = hstack((gate["features"].transform(texts),
                 csr_matrix(e5 * gate["scale"])), format="csr")
    accepted = gate["model"].predict_proba(gx)[:, 1] >= gate["threshold"]
    light = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_prob = light["classes"].predict_proba(light["features"].transform(texts))
    ckpt = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                      map_location="cpu", weights_only=False)
    names = np.array(list(ckpt["classes"]))
    logits = np.load(ROOT / "artifacts/encoder_base_positive_test_logits.npz")[
        "class_logits"].copy()
    logits[:, ckpt["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse = np.zeros_like(bert_prob)
    for col, name in enumerate(light["classes"].classes_):
        sparse[:, ckpt["classes"][name]] = sparse_prob[:, col]
    raw = names[((bert_prob + sparse) / 2).argmax(axis=1)]
    positive = gold != "not_a_problem"
    variants = {}
    baseline = raw.copy()
    baseline[~accepted] = "not_a_problem"
    variants["working_pipeline"] = baseline
    perfect_gate = raw.copy()
    perfect_gate[~positive] = "not_a_problem"
    variants["oracle_gate_same_class_head"] = perfect_gate
    perfect_positive_class = baseline.copy()
    perfect_positive_class[positive & accepted] = gold[positive & accepted]
    variants["same_gate_oracle_class_on_accepted_true_problems"] = perfect_positive_class
    variants["oracle_both"] = gold.copy()
    cut = len(data[SOURCES[0]])
    output = {"split": "reused_test", "kind": "diagnostic_oracle_ceilings",
              "warning": "Oracle labels are used to correct predictions; these are not achievable model metrics or forecasts.",
              "sources": {}}
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        labels = sorted(set(gold[sl]))
        output["sources"][source] = {
            "n": int(len(gold[sl])), "positive": int(positive[sl].sum()),
            "missed_positive_by_gate": int(np.sum(positive[sl] & ~accepted[sl])),
            "false_positive_by_gate": int(np.sum(~positive[sl] & accepted[sl])),
            "macro_f1": {name: round(float(f1_score(gold[sl], pred[sl], labels=labels,
                                                       average="macro", zero_division=0)), 4)
                         for name, pred in variants.items()},
        }
    path = Path(__file__).with_name("diagnostic_oracle_test.json")
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
