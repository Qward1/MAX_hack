"""Check whether the frozen E5 representation helps emergency detection on val."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

ML_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML_ROOT / "src"))
from domsignal_ml.data import load_safety
from domsignal_ml.train import safety_threshold


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    train = load_safety(args.data_root, "train")
    val = load_safety(args.data_root, "val")
    snapshot = snapshot_download("intfloat/multilingual-e5-base", local_files_only=True)
    model = SentenceTransformer(snapshot, device="cuda" if torch.cuda.is_available() else "cpu",
                                local_files_only=True)
    model.max_seq_length = 128
    start = time.perf_counter()
    def embed(rows):
        return model.encode(["query: " + row["text"] for row in rows], batch_size=16,
                            show_progress_bar=False, normalize_embeddings=True)
    x_train, x_val = embed(train), embed(val)
    classifier = LogisticRegression(C=1.0, class_weight="balanced", max_iter=400,
                                    random_state=42)
    y_train = np.array([row["emergency"] for row in train])
    y_val = np.array([row["emergency"] for row in val])
    classifier.fit(x_train, y_train)
    score = classifier.predict_proba(x_val)[:, 1]
    result = {
        "model": "intfloat/multilingual-e5-base",
        "split": "val", "train_n": len(train), "val_n": len(val),
        "ap": round(float(average_precision_score(y_val, score)), 4),
        "fpr_05_operating": safety_threshold(y_val, score),
        "seconds": round(time.perf_counter() - start, 2),
        "gpu_peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1)
                                 if torch.cuda.is_available() else None,
    }
    output = ML_ROOT / "experiments/05_emergency/e5_val.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
