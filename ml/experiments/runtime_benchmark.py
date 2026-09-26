"""Measure warm single-message inference; no message content is printed."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import load_real  # noqa: E402
from domsignal_ml.pipeline import classify_text, load_bundle, load_mapping  # noqa: E402


def main() -> None:
    data = Path(sys.argv[1])
    artifact = ROOT / "artifacts" / "light.joblib"
    start = time.perf_counter()
    bundle = load_bundle(artifact)
    load_ms = (time.perf_counter() - start) * 1000
    mapping = load_mapping(ROOT / "configs" / "class_mapping.yaml")
    rows = load_real(data, "val")["real_telegram"][:510]
    for row in rows[:10]:
        classify_text(row["text"], bundle, mapping)
    elapsed = []
    for row in rows[10:]:
        start = time.perf_counter()
        classify_text(row["text"], bundle, mapping)
        elapsed.append((time.perf_counter() - start) * 1000)
    result = {
        "n": len(elapsed), "split": "telegram val", "load_ms": round(load_ms, 1),
        "warm_single_p50_ms": round(float(np.quantile(elapsed, 0.5)), 2),
        "warm_single_p95_ms": round(float(np.quantile(elapsed, 0.95)), 2),
        "warm_single_mean_ms": round(float(np.mean(elapsed)), 2),
        "rss_mb": round(psutil.Process().memory_info().rss / 2**20, 1),
    }
    Path(__file__).with_name("runtime_benchmark.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
