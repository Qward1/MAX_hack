"""Offline readiness check for the standalone command-line ML block."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGES = {
    "light": ("numpy", "scipy", "sklearn", "joblib", "yaml"),
    "heavy": ("torch", "transformers", "sentence_transformers", "huggingface_hub"),
}
FILES = {
    "light": ("artifacts/light.joblib", "configs/class_mapping.yaml"),
    "heavy": ("artifacts/hybrid_gate_scale100.joblib",
              "artifacts/encoder_base_positive.pt", "artifacts/models/rubert-base/config.json"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local ML readiness without network calls")
    parser.add_argument("--engine", choices=("light", "heavy"), default="heavy")
    parser.add_argument("--data-root", type=Path,
                        help="Optional v3.0 datasets folder; needed only for train/eval")
    args = parser.parse_args()
    required_packages = list(PACKAGES["light"])
    required_files = list(FILES["light"])
    if args.engine == "heavy":
        required_packages.extend(PACKAGES["heavy"])
        required_files.extend(FILES["heavy"])
    missing_packages = [name for name in required_packages
                        if importlib.util.find_spec(name) is None]
    missing_files = [name for name in required_files if not (ROOT / name).is_file()]
    e5_cached = None
    if args.engine == "heavy" and "huggingface_hub" not in missing_packages:
        from huggingface_hub import snapshot_download
        try:
            snapshot_download("intfloat/multilingual-e5-base", local_files_only=True)
            e5_cached = True
        except (OSError, ValueError):
            e5_cached = False
    data_ready = None
    if args.data_root is not None:
        root = args.data_root.expanduser().resolve()
        data_ready = (root / "README.md").is_file() and (
            root / "labels_taxonomy.yaml").is_file()
    ready = (sys.version_info >= (3, 10) and not missing_packages and
             not missing_files and e5_cached is not False and data_ready is not False)
    print(json.dumps({"ready": ready, "engine": args.engine,
                      "python_ok": sys.version_info >= (3, 10),
                      "missing_packages": missing_packages,
                      "missing_files": missing_files,
                      "e5_cached": e5_cached, "data_ready": data_ready},
                     ensure_ascii=False))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
