"""Estimate review load for a possible future LLM cascade; no API calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, load_real  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def main() -> None:
    rows = load_real(Path(sys.argv[1]), "val")
    bundle = load_bundle(ROOT / "artifacts" / "light.joblib")
    result = {"split": "real val", "gate_threshold": bundle["gate_threshold"],
              "bands": {}, "note": "Review-load estimate only, no LLM accuracy or cost measured."}
    for source in SOURCES:
        texts = [row["text"] for row in rows[source]]
        x = bundle["gate_features"].transform(texts)
        score = bundle["gate"].predict_proba(x)[:, 1]
        result["bands"][source] = {
            "n": len(score),
            "score_0_35_to_0_70_count": int(((score >= 0.35) & (score <= 0.70)).sum()),
            "score_0_35_to_0_70_share": round(float(((score >= 0.35) & (score <= 0.70)).mean()), 4),
            "score_0_20_to_0_80_share": round(float(((score >= 0.20) & (score <= 0.80)).mean()), 4),
        }
    Path(__file__).with_name("estimate_val.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
