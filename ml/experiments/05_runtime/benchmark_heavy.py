"""Measure local heavy inference; writes aggregate timings only."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, load_real  # noqa: E402
from domsignal_ml.heavy import HeavyEngine  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    args = parser.parse_args()
    data = load_real(args.data_root, "val")
    texts = [row["text"] for source in SOURCES for row in data[source]][:args.count]
    process = psutil.Process()
    start = time.perf_counter()
    engine = HeavyEngine(ROOT)
    load_seconds = time.perf_counter() - start
    engine.classify_text(texts[0])
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    latencies = []
    for text in texts:
        start = time.perf_counter()
        engine.classify_text(text)
        latencies.append((time.perf_counter() - start) * 1000)
    start = time.perf_counter()
    engine.predict_batch(texts)
    batch_seconds = time.perf_counter() - start
    report = {
        "n": len(texts), "device": engine.device,
        "load_seconds": round(load_seconds, 3),
        "single_warm_p50_ms": round(float(np.quantile(latencies, 0.5)), 3),
        "single_warm_p95_ms": round(float(np.quantile(latencies, 0.95)), 3),
        "batch_messages_per_second": round(len(texts) / batch_seconds, 2),
        "rss_mb": round(process.memory_info().rss / 2**20, 1),
        "gpu_peak_allocated_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1)
        if torch.cuda.is_available() else None,
    }
    output = Path(__file__).with_name("benchmark_heavy.json")
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
