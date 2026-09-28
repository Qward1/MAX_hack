"""Validation-only probability ensembles for a stronger class head."""
from __future__ import annotations

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


def main() -> None:
    root = Path(sys.argv[1])
    data = load_real(root, "val")
    rows = [row for source in SOURCES for row in data[source]]
    texts = [row["text"] for row in rows]
    gold = np.array([label_of(row, "class") for row in rows])
    cut = len(data[SOURCES[0]])
    bundle = load_bundle(ROOT / "artifacts/light.joblib")
    sparse = bundle["classes"]
    sparse_prob = sparse.predict_proba(bundle["features"].transform(texts))
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    names = list(checkpoint["classes"])
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")["class_logits"]
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse_aligned = np.zeros_like(bert_prob)
    for i, name in enumerate(sparse.classes_):
        sparse_aligned[:, names.index(name)] = sparse_prob[:, i]
    gates = []
    embedding = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    for scale in (0.5, 1.0):
        gate = joblib.load(ROOT / "artifacts" / f"hybrid_gate_scale{int(scale*100):03d}.joblib")
        features = hstack((gate["features"].transform(texts),
                           csr_matrix(embedding * gate["scale"])), format="csr")
        gate_score = gate["model"].predict_proba(features)[:, 1]
        gates.append((scale, gate_score, gate["threshold"]))
    results = []
    for scale, gate_score, threshold in gates:
        for weight in (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0):
            prob = (1 - weight) * bert_prob + weight * sparse_aligned
            classes = np.array(names)[prob.argmax(axis=1)]
            classes[gate_score < threshold] = "not_a_problem"
            scores = {}
            for source, sl in ((SOURCES[0], slice(0, cut)),
                               (SOURCES[1], slice(cut, None))):
                scores[source] = round(float(f1_score(gold[sl], classes[sl],
                    labels=sorted(set(gold[sl])), average="macro", zero_division=0)), 4)
            results.append({"gate_scale": scale, "sparse_weight": weight,
                            "end_macro_f1": scores,
                            "mean": round(float(np.mean(list(scores.values()))), 4)})
    report = {"split": "val", "selection": "mean source macro-F1", "results": results,
              "best": max(results, key=lambda r: r["mean"])}
    output = Path(__file__).with_name("ensemble_val.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"best": report["best"], "base": results[7]}))


if __name__ == "__main__":
    main()
