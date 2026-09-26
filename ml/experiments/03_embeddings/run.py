"""Frozen multilingual-e5-base + linear heads. Local model, no external requests."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import average_precision_score, f1_score

ML_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML_ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic, positives
from domsignal_ml.train import gate_threshold

SEED = 42


def encode(model: SentenceTransformer, rows: list[dict], batch_size: int) -> np.ndarray:
    texts = ["query: " + row["text"] for row in rows]
    return model.encode(texts, batch_size=batch_size, show_progress_bar=False,
                        convert_to_numpy=True, normalize_embeddings=True).astype("float32")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ML_ROOT / "experiments/03_embeddings/results_val.json")
    parser.add_argument("--cache-dir", type=Path, default=ML_ROOT / "artifacts/embeddings_e5_base")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--force-reencode", action="store_true",
                        help="measure cold encoding and refresh ignored embedding cache")
    args = parser.parse_args()
    start = time.perf_counter()
    real_train = load_real(args.data_root, "train")
    real_val = load_real(args.data_root, "val")
    train_rows = [row for source in SOURCES for row in real_train[source]]
    val_rows = [row for source in SOURCES for row in real_val[source]]
    synthetic = load_synthetic(args.data_root)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    cache_files = {
        "train": args.cache_dir / "real_train.npy",
        "val": args.cache_dir / "real_val.npy",
        "synthetic": args.cache_dir / "synthetic_train.npy",
    }
    if not args.force_reencode and all(path.is_file() for path in cache_files.values()):
        x_train, x_val, x_syn = (np.load(cache_files[key]) for key in ("train", "val", "synthetic"))
        encode_seconds = 0.0
        cache_hit = True
    else:
        snapshot = snapshot_download("intfloat/multilingual-e5-base", local_files_only=True)
        model = SentenceTransformer(snapshot, device=args.device, local_files_only=True)
        model.max_seq_length = 128
        enc_start = time.perf_counter()
        x_train = encode(model, train_rows, args.batch_size)
        x_val = encode(model, val_rows, args.batch_size)
        x_syn = encode(model, synthetic, args.batch_size)
        encode_seconds = time.perf_counter() - enc_start
        np.save(cache_files["train"], x_train)
        np.save(cache_files["val"], x_val)
        np.save(cache_files["synthetic"], x_syn)
        cache_hit = False
        del model
    y_train = np.array([label_of(row, "class") != "not_a_problem" for row in train_rows])
    y_val = np.array([label_of(row, "class") != "not_a_problem" for row in val_rows])
    eligible = np.array([i for i, row in enumerate(synthetic)
                         if "gate" in row["annotation"].get("use", [])])
    gate_x = np.vstack((x_train, x_syn[eligible]))
    gate_y = np.concatenate((
        y_train,
        np.array([label_of(synthetic[i], "class") != "not_a_problem" for i in eligible]),
    ))
    gate = LogisticRegression(C=1.0, max_iter=400, class_weight="balanced", random_state=SEED)
    gate.fit(gate_x, gate_y)
    score_val = gate.predict_proba(x_val)[:, 1]
    gate_op = gate_threshold(y_val, score_val)
    syn_pos = np.array([i for i, row in enumerate(synthetic)
                        if label_of(row, "class") != "not_a_problem"])
    x_class = np.vstack((x_train[y_train], x_syn[syn_pos]))
    class_y = np.array(
        [label_of(row, "class") for row in positives(train_rows)]
        + [label_of(synthetic[i], "class") for i in syn_pos]
    )
    class_model = SGDClassifier(loss="log_loss", alpha=1e-4, max_iter=2000, tol=1e-4,
                                class_weight="balanced", average=True, random_state=SEED)
    weights = np.ones(len(class_y))
    weights[int(y_train.sum()):] = 0.5
    class_model.fit(x_class, class_y, sample_weight=weights)
    report = {
        "model": "intfloat/multilingual-e5-base", "frozen": True,
        "prefix": "query: ", "max_seq_length": 128, "device": args.device,
        "batch_size": args.batch_size, "seed": SEED, "train_real": len(train_rows),
        "train_synthetic_class": len(syn_pos), "train_synthetic_gate": len(eligible),
        "cache_hit": cache_hit, "encode_seconds": round(encode_seconds, 2),
        "total_seconds": round(time.perf_counter() - start, 2),
        "gpu_peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1)
                                 if args.device == "cuda" else None,
        "python": platform.python_version(), "val_gate_ap_pooled": round(
            float(average_precision_score(y_val, score_val)), 4),
        "gate_op": gate_op, "sources": {},
    }
    cursor = 0
    for source in SOURCES:
        rows = real_val[source]
        stop = cursor + len(rows)
        sub_y, sub_score = y_val[cursor:stop], score_val[cursor:stop]
        pos = np.where(sub_y)[0]
        gold = [label_of(rows[i], "class") for i in pos]
        predicted = class_model.predict(x_val[cursor:stop][pos])
        report["sources"][source] = {
            "n": len(rows), "problems": int(sub_y.sum()),
            "gate_ap": round(float(average_precision_score(sub_y, sub_score)), 4),
            "gate_precision": round(float((sub_y & (sub_score >= gate_op["threshold"])).sum()
                                   / max(1, (sub_score >= gate_op["threshold"]).sum())), 4),
            "gate_recall": round(float((sub_y & (sub_score >= gate_op["threshold"])).sum()
                                / max(1, sub_y.sum())), 4),
            "class_macro_f1": round(float(f1_score(gold, predicted,
                                                   labels=sorted(set(gold)), average="macro",
                                                   zero_division=0)), 4),
        }
        cursor = stop
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
