"""Measure which uncertainty rules could benefit from a selective oracle.

This is an optimistic offline diagnostic on reused validation data. It makes no
claim about LLM quality and never sends or saves message text.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def macro(gold, pred) -> float:
    return float(f1_score(gold, pred, labels=sorted(set(gold)),
                          average="macro", zero_division=0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    data = load_real(args.data_root, "val")
    rows = [row for source in SOURCES for row in data[source]]
    texts = [row["text"] for row in rows]
    gold = np.array([label_of(row, "class") for row in rows])
    cut = len(data[SOURCES[0]])
    light = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_prob = light["classes"].predict_proba(light["features"].transform(texts))
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    names = np.array(list(checkpoint["classes"]))
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")["class_logits"].copy()
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse = np.zeros_like(bert)
    for col, name in enumerate(light["classes"].classes_):
        sparse[:, checkpoint["classes"][name]] = sparse_prob[:, col]
    prob = (bert + sparse) / 2
    top2 = np.sort(prob, axis=1)[:, -2:]
    class_margin = top2[:, 1] - top2[:, 0]
    disagreement = names[bert.argmax(axis=1)] != names[sparse.argmax(axis=1)]
    gate = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    embedding = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    x = hstack((gate["features"].transform(texts),
                csr_matrix(embedding * gate["scale"])), format="csr")
    score = gate["model"].predict_proba(x)[:, 1]
    accepted = score >= gate["threshold"]
    predicted = names[prob.argmax(axis=1)]
    predicted[~accepted] = "not_a_problem"
    gate_unc = -np.abs(score - gate["threshold"])
    class_unc = np.where(accepted, -class_margin, -100.0)
    disagree_unc = np.where(accepted & disagreement, -class_margin,
                             -100.0)
    # Allocate half the budget to borderline gate decisions, half to uncertain
    # accepted classes. This policy is fixed before inspecting the table below.
    report = {"split": "reused_val", "api_calls": 0,
              "note": "Oracle replacement is an upper bound, not measured LLM gain.",
              "sources": {}}
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        actual, base = gold[sl], predicted[sl]
        n = len(actual)
        local = {"n": n, "errors": int((actual != base).sum()),
                 "baseline_f1": round(macro(actual, base), 4), "routes": {}}
        policies = {"gate_border": gate_unc[sl],
                    "class_margin": class_unc[sl],
                    "head_disagreement": disagree_unc[sl]}
        for fraction in (0.05, 0.10, 0.20):
            budget = max(1, round(fraction * n))
            for name, uncertainty in policies.items():
                selected = np.argsort(-uncertainty, kind="stable")[:budget]
                corrected = base.copy()
                corrected[selected] = actual[selected]
                key = f"{name}_{fraction:.2f}"
                local["routes"][key] = {
                    "routed": budget,
                    "error_capture": round(float(np.mean(actual[selected] != base[selected])), 4),
                    "oracle_f1": round(macro(actual, corrected), 4),
                    "missed_positive_captured": int(np.sum(
                        (actual[selected] != "not_a_problem") &
                        (base[selected] == "not_a_problem"))),
                }
            gate_indices = np.argsort(-gate_unc[sl], kind="stable")[:budget // 2]
            remaining = np.setdiff1d(np.arange(n), gate_indices, assume_unique=False)
            other = remaining[np.argsort(-class_unc[sl][remaining], kind="stable")
                              [:budget - len(gate_indices)]]
            selected = np.r_[gate_indices, other]
            corrected = base.copy()
            corrected[selected] = actual[selected]
            local["routes"][f"gate_plus_class_{fraction:.2f}"] = {
                "routed": budget,
                "error_capture": round(float(np.mean(actual[selected] != base[selected])), 4),
                "oracle_f1": round(macro(actual, corrected), 4),
                "missed_positive_captured": int(np.sum(
                    (actual[selected] != "not_a_problem") &
                    (base[selected] == "not_a_problem"))),
            }
        report["sources"][source] = local
    output = Path(__file__).with_name("route_val_oracle.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
