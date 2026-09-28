"""Validation-only ablations of class-head weights and fusion rules.

Only aggregate metrics and decisions enter the JSON output; no raw text is saved.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
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


def normalize(prob: np.ndarray, temperature: float) -> np.ndarray:
    adjusted = np.maximum(prob, 1e-12) ** (1 / temperature)
    return adjusted / adjusted.sum(axis=1, keepdims=True)


def scores(gold: np.ndarray, predicted: np.ndarray, cut: int) -> dict:
    result = {}
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        actual, guess = gold[sl], predicted[sl]
        labels = sorted(set(actual))
        positive = actual != "not_a_problem"
        result[source] = {
            "end_macro_f1": round(float(f1_score(actual, guess, labels=labels,
                                                  average="macro", zero_division=0)), 4),
            "changed_from_gold": int(np.sum(actual != guess)),
            "support": int(len(actual)),
            "positive_support": int(positive.sum()),
        }
    result["mean_f1"] = round(float(np.mean([result[s]["end_macro_f1"]
                                             for s in SOURCES])), 4)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    start = time.perf_counter()
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
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")[
        "class_logits"].copy()
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse_aligned = np.zeros_like(bert_prob)
    for column, name in enumerate(light["classes"].classes_):
        sparse_aligned[:, checkpoint["classes"][name]] = sparse_prob[:, column]

    gate = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    embeddings = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    gate_x = hstack((gate["features"].transform(texts),
                     csr_matrix(embeddings * gate["scale"])), format="csr")
    gate_score = gate["model"].predict_proba(gate_x)[:, 1]
    accepted = gate_score >= gate["threshold"]

    def evaluate(prob: np.ndarray, method: str, weight: float,
                 temperature: float = 1.0) -> dict:
        raw = names[prob.argmax(axis=1)]
        final = raw.copy()
        final[~accepted] = "not_a_problem"
        item = {"method": method, "sparse_weight": weight,
                "bert_temperature": temperature, **scores(gold, final, cut)}
        for source, sl in ((SOURCES[0], slice(0, cut)),
                           (SOURCES[1], slice(cut, None))):
            mask = gold[sl] != "not_a_problem"
            item[source]["conditional_macro_f1"] = round(float(f1_score(
                gold[sl][mask], raw[sl][mask], labels=sorted(set(gold[sl][mask])),
                average="macro", zero_division=0)), 4)
        return item

    results = []
    for temperature in (0.7, 1.0, 1.5):
        b = normalize(bert_prob, temperature)
        for step in range(21):
            weight = step / 20
            results.append(evaluate((1 - weight) * b + weight * sparse_aligned,
                                    "arithmetic", weight, temperature))
    for weight in (0.1, 0.25, 0.5, 0.75):
        log_prob = ((1 - weight) * np.log(np.maximum(bert_prob, 1e-12))
                    + weight * np.log(np.maximum(sparse_aligned, 1e-12)))
        results.append(evaluate(log_prob, "geometric_log", weight))
    baseline = next(item for item in results if item["method"] == "arithmetic"
                    and item["sparse_weight"] == 0.5
                    and item["bert_temperature"] == 1.0)
    best = max(results, key=lambda item: item["mean_f1"])
    if best["method"] != "geometric_log" or best["sparse_weight"] != 0.25:
        raise ValueError("Bootstrap candidate changed; update the fixed comparison")
    base_raw = names[((bert_prob + sparse_aligned) / 2).argmax(axis=1)]
    best_log = (0.75 * np.log(np.maximum(bert_prob, 1e-12))
                + 0.25 * np.log(np.maximum(sparse_aligned, 1e-12)))
    best_raw = names[best_log.argmax(axis=1)]
    base_final = np.where(accepted, base_raw, "not_a_problem")
    best_final = np.where(accepted, best_raw, "not_a_problem")
    rng = np.random.default_rng(42)
    bootstrap = {}
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        groups: dict[str, list[int]] = {}
        for i, row in enumerate(data[source]):
            groups.setdefault(str(row["family_id"]), []).append(i)
        blocks = list(groups.values())
        actual = gold[sl]
        base = base_final[sl]
        candidate = best_final[sl]
        labels_fixed = sorted(set(actual))
        deltas = []
        for _ in range(500):
            choice = rng.integers(0, len(blocks), len(blocks))
            sample = np.array([i for k in choice for i in blocks[k]], dtype=int)
            deltas.append(float(f1_score(actual[sample], candidate[sample],
                                         labels=labels_fixed, average="macro", zero_division=0)
                                - f1_score(actual[sample], base[sample],
                                           labels=labels_fixed, average="macro", zero_division=0)))
        bootstrap[source] = {
            "families": len(blocks),
            "delta_f1_p025_p975": [round(float(x), 4) for x in
                                    np.quantile(deltas, [0.025, 0.975])],
            "bootstrap_probability_nonpositive": round(float(np.mean(np.array(deltas) <= 0)), 4),
        }
    complementarity = {}
    class_head_counts = {}
    bert_class = names[bert_prob.argmax(axis=1)]
    sparse_class = names[sparse_aligned.argmax(axis=1)]
    blend_class = names[((bert_prob + sparse_aligned) / 2).argmax(axis=1)]
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        positive = gold[sl] != "not_a_problem"
        actual = gold[sl][positive]
        b = bert_class[sl][positive] == actual
        s = sparse_class[sl][positive] == actual
        ensemble = blend_class[sl][positive] == actual
        complementarity[source] = {
            "true_positive_messages": int(len(actual)),
            "both_heads_correct": int(np.sum(b & s)),
            "bert_only_correct": int(np.sum(b & ~s)),
            "sparse_only_correct": int(np.sum(~b & s)),
            "both_heads_wrong": int(np.sum(~b & ~s)),
            "ensemble_correct_among_bert_only": int(np.sum(b & ~s & ensemble)),
            "ensemble_correct_among_sparse_only": int(np.sum(~b & s & ensemble)),
            "ensemble_correct_among_both_wrong": int(np.sum(~b & ~s & ensemble)),
            "ensemble_wrong_among_both_correct": int(np.sum(b & s & ~ensemble)),
        }
        class_head_counts[source] = {}
        for label in sorted(set(actual)):
            mask = actual == label
            class_head_counts[source][label] = {
                "support": int(mask.sum()),
                "bert_correct": int(np.sum(b & mask)),
                "sparse_correct": int(np.sum(s & mask)),
                "ensemble_correct": int(np.sum(ensemble & mask)),
                "sparse_only_correct": int(np.sum(~b & s & mask)),
                "bert_only_correct": int(np.sum(b & ~s & mask)),
            }
    report = {"split": "val", "data_version": "v3.0", "seed": 42,
              "gate": "hybrid_gate_scale100 at frozen val threshold",
              "selection_warning": "Dense sweep on reused val is exploratory; no new test claim.",
              "elapsed_seconds": round(time.perf_counter() - start, 2),
              "baseline": baseline, "best": best,
              "head_error_complementarity": complementarity,
              "head_by_class": class_head_counts,
              "paired_family_bootstrap_best_vs_baseline": bootstrap,
              "results": results}
    path = Path(__file__).with_name("round3_ensemble_val.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"baseline": baseline, "best": best,
                      "elapsed_seconds": report["elapsed_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
