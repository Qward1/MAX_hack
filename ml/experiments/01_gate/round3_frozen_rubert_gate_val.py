"""Frozen task-adapted ruBERT embeddings for the binary gate; val only.

Embeddings are cached under ignored artifacts. Reports contain aggregates only.
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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_recall_fscore_support
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.encoder import MultiHead  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402
from domsignal_ml.train import gate_threshold  # noqa: E402


@torch.no_grad()
def encode(texts: list[str], tokenizer, model, device: str,
           max_length: int, batch_size: int = 32) -> np.ndarray:
    outputs = []
    model.eval()
    for start in range(0, len(texts), batch_size):
        batch = tokenizer(texts[start:start + batch_size], padding="max_length",
                          truncation=True, max_length=max_length,
                          return_tensors="pt")
        batch = {key: tensor.to(device) for key, tensor in batch.items()}
        pooled = model.encoder(**batch).last_hidden_state[:, 0, :]
        outputs.append(pooled.float().cpu().numpy().astype("float32"))
    return np.concatenate(outputs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    start = time.perf_counter()
    torch.set_num_threads(4)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    train = load_real(args.data_root, "train")
    val = load_real(args.data_root, "val")
    synthetic = load_synthetic(args.data_root)
    train_rows = [row for source in SOURCES for row in train[source]]
    val_rows = [row for source in SOURCES for row in val[source]]
    eligible = [row for row in synthetic if "gate" in row["annotation"].get("use", [])]
    y_train = np.array([label_of(row, "class") != "not_a_problem" for row in train_rows])
    y_syn = np.array([label_of(row, "class") != "not_a_problem" for row in eligible])
    y_val = np.array([label_of(row, "class") != "not_a_problem" for row in val_rows])
    gold = np.array([label_of(row, "class") for row in val_rows])
    cut = len(val[SOURCES[0]])
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    model_dir = ROOT / "artifacts/models/rubert-base"
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    model = MultiHead(str(model_dir), len(checkpoint["classes"]),
                      len(checkpoint["utterances"]))
    model.load_state_dict(checkpoint["model"])
    model.to(device)
    cache = ROOT / "artifacts/round3_frozen_rubert"
    cache.mkdir(parents=True, exist_ok=True)
    encoded = {}
    for name, rows in (("train", train_rows), ("synthetic_gate", eligible),
                       ("val", val_rows)):
        path = cache / f"{name}.npy"
        if path.is_file():
            values = np.load(path)
            if values.shape != (len(rows), model.encoder.config.hidden_size):
                raise ValueError(f"unexpected cached embedding shape for {name}")
        else:
            values = encode([row["text"] for row in rows], tokenizer, model,
                            device, checkpoint["max_length"])
            np.save(path, values)
        encoded[name] = values
        print(json.dumps({"encoded": name, "rows": len(rows),
                          "seconds_so_far": round(time.perf_counter() - start, 1)}),
              flush=True)
    del model
    torch.cuda.empty_cache()
    x_train = np.vstack((encoded["train"], encoded["synthetic_gate"]))
    labels = np.r_[y_train, y_syn]
    weights = np.r_[np.ones(len(y_train)), np.full(len(y_syn), 0.5)]

    light = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_prob = light["classes"].predict_proba(light["features"].transform(
        [row["text"] for row in val_rows]))
    names = np.array(list(checkpoint["classes"]))
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")[
        "class_logits"].copy()
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    aligned = np.zeros_like(bert_prob)
    for col, name in enumerate(light["classes"].classes_):
        aligned[:, checkpoint["classes"][name]] = sparse_prob[:, col]
    raw_class = light["classes"].classes_[sparse_prob.argmax(axis=1)]
    blend_class = names[((bert_prob + aligned) / 2).argmax(axis=1)]
    hybrid = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    e5 = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    val_x = hstack((hybrid["features"].transform([row["text"] for row in val_rows]),
                    csr_matrix(e5 * hybrid["scale"])), format="csr")
    hybrid_score = hybrid["model"].predict_proba(val_x)[:, 1]

    def evaluate(name: str, score: np.ndarray, details: dict) -> dict:
        op = gate_threshold(y_val, score)
        final = raw_class.copy()
        final[score < op["threshold"]] = "not_a_problem"
        blend_final = blend_class.copy()
        blend_final[score < op["threshold"]] = "not_a_problem"
        item = {"name": name, **details,
                "threshold": round(op["threshold"], 6),
                "val_pooled_precision": round(op["val_precision"], 4),
                "val_pooled_recall": round(op["val_recall"], 4), "sources": {}}
        for source, sl in ((SOURCES[0], slice(0, cut)),
                           (SOURCES[1], slice(cut, None))):
            pred_binary = score[sl] >= op["threshold"]
            p, r, _, _ = precision_recall_fscore_support(
                y_val[sl], pred_binary, average="binary", zero_division=0)
            item["sources"][source] = {
                "gate_ap": round(float(average_precision_score(y_val[sl], score[sl])), 4),
                "gate_precision": round(float(p), 4),
                "gate_recall": round(float(r), 4),
                "end_f1_sparse_class": round(float(f1_score(
                    gold[sl], final[sl], labels=sorted(set(gold[sl])),
                    average="macro", zero_division=0)), 4),
                "end_f1_blended_class": round(float(f1_score(
                    gold[sl], blend_final[sl], labels=sorted(set(gold[sl])),
                    average="macro", zero_division=0)), 4),
            }
        item["mean_ap"] = round(float(np.mean([
            item["sources"][s]["gate_ap"] for s in SOURCES])), 4)
        item["mean_f1_blended_class"] = round(float(np.mean([
            item["sources"][s]["end_f1_blended_class"] for s in SOURCES])), 4)
        return item

    results = [evaluate("existing_hybrid_gate", hybrid_score, {})]
    selected_score = None
    for c in (0.01, 0.1, 1.0, 10.0):
        t0 = time.perf_counter()
        clf = LogisticRegression(C=c, max_iter=1000, class_weight="balanced",
                                 random_state=42)
        clf.fit(x_train, labels, sample_weight=weights)
        score = clf.predict_proba(encoded["val"])[:, 1]
        if c == 10.0:
            selected_score = 0.25 * score + 0.75 * hybrid_score
        results.append(evaluate("frozen_rubert_lr", score,
                                {"C": c, "fit_seconds": round(time.perf_counter() - t0, 2)}))
        for alpha in (0.25, 0.5, 0.75):
            results.append(evaluate("hybrid_plus_rubert", alpha * score
                                    + (1 - alpha) * hybrid_score,
                                    {"C": c, "rubert_weight": alpha}))
    selected = next(row for row in results if row.get("C") == 10.0
                    and row.get("rubert_weight") == 0.25)
    baseline = results[0]
    baseline_final = blend_class.copy()
    baseline_final[hybrid_score < baseline["threshold"]] = "not_a_problem"
    selected_final = blend_class.copy()
    selected_final[selected_score < selected["threshold"]] = "not_a_problem"
    rng = np.random.default_rng(42)
    bootstrap = {}
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        local_rows = val[source]
        groups: dict[str, list[int]] = {}
        for i, row in enumerate(local_rows):
            groups.setdefault(str(row["family_id"]), []).append(i)
        group_indices = list(groups.values())
        actual = gold[sl]
        old = baseline_final[sl]
        new = selected_final[sl]
        labels_fixed = sorted(set(actual))
        differences = []
        for _ in range(500):
            choice = rng.integers(0, len(group_indices), len(group_indices))
            sample = np.array([i for k in choice for i in group_indices[k]], dtype=int)
            old_f1 = f1_score(actual[sample], old[sample], labels=labels_fixed,
                              average="macro", zero_division=0)
            new_f1 = f1_score(actual[sample], new[sample], labels=labels_fixed,
                              average="macro", zero_division=0)
            differences.append(float(new_f1 - old_f1))
        bootstrap[source] = {
            "families": len(group_indices),
            "delta_f1_point": round(selected["sources"][source]["end_f1_blended_class"]
                                    - baseline["sources"][source]["end_f1_blended_class"], 4),
            "delta_f1_group_bootstrap_p025_p975": [round(float(x), 4) for x in
                                                    np.quantile(differences, [0.025, 0.975])],
            "bootstrap_probability_nonpositive": round(float(np.mean(np.array(differences) <= 0)), 4),
        }
    report = {"split": "val", "encoder": "fine-tuned positive ruBERT-base frozen",
              "device": device, "train_rows": len(x_train),
              "total_seconds": round(time.perf_counter() - start, 2),
              "best_ap": max(results, key=lambda r: r["mean_ap"]),
              "selected_f1_diagnostic": selected,
              "paired_family_bootstrap_selected_vs_baseline": bootstrap,
              "selection_warning": "All configurations and thresholds inspected on reused val; intervals are exploratory, not independent confirmation.",
              "results": results}
    path = Path(__file__).with_name("round3_frozen_rubert_gate_val.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"best_ap": report["best_ap"],
                      "total_seconds": report["total_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
