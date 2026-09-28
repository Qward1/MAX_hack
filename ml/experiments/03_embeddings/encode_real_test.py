"""Encode held-out real test once with the frozen local E5 model."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, load_real  # noqa: E402


def main():
    data = Path(sys.argv[1])
    rows = load_real(data, "test")
    texts = ["query: " + r["text"] for source in SOURCES for r in rows[source]]
    model_path = snapshot_download("intfloat/multilingual-e5-base", local_files_only=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(model_path, device=device, local_files_only=True)
    model.max_seq_length = 128
    start = time.perf_counter()
    embeddings = model.encode(texts, batch_size=16, show_progress_bar=False,
                              convert_to_numpy=True, normalize_embeddings=True).astype("float32")
    output = ROOT / "artifacts/embeddings_e5_base/real_test.npy"
    np.save(output, embeddings)
    report = {"split": "test", "n": len(texts), "device": device,
              "seconds": round(time.perf_counter() - start, 2),
              "gpu_peak_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1)
              if device == "cuda" else None,
              "cache_bytes": output.stat().st_size}
    Path(__file__).with_name("encode_real_test.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
