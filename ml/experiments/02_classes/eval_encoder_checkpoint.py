"""Evaluate a frozen encoder checkpoint with the fixed observed-label metric."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real  # noqa: E402
from domsignal_ml.encoder import MultiHead  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402
from train_encoder import EncodedRows, predict, score_val  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--frozen-gate", action="store_true")
    parser.add_argument("--save-predictions", action="store_true",
                        help="save numeric logits in ignored artifacts, no text")
    args = parser.parse_args()
    torch.set_num_threads(4)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    pretrained = checkpoint["pretrained"]
    tokenizer = AutoTokenizer.from_pretrained(pretrained)
    model = MultiHead(pretrained, len(checkpoint["classes"]),
                      len(checkpoint["utterances"]))
    model.load_state_dict(checkpoint["model"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    data = load_real(args.data_root, args.split)
    rows = [{"text": r["text"], "class": label_of(r, "class")}
            for source in SOURCES for r in data[source]]
    dataset = EncodedRows(tokenizer, rows, checkpoint["max_length"],
                          checkpoint["classes"], checkpoint["utterances"])
    loader = DataLoader(dataset, batch_size=32)
    frozen_gate = None
    if args.frozen_gate:
        bundle = load_bundle(ROOT / "artifacts/light.joblib")
        scores = bundle["gate"].predict_proba(bundle["gate_features"].transform(
            [r["text"] for r in rows]))[:, 1]
        frozen_gate = (scores, bundle["gate_threshold"])
    logits = predict(model, loader, device)
    if args.save_predictions:
        np.savez_compressed(ROOT / "artifacts" / f"{args.checkpoint.stem}_{args.split}_logits.npz",
                            class_logits=logits[0], gate_logits=logits[1])
    result = score_val(logits, rows, checkpoint["classes"],
                       [len(data[s]) for s in SOURCES], frozen_gate)
    report = {"checkpoint": str(args.checkpoint), "epoch": checkpoint["epoch"],
              "split": args.split, "frozen_gate": args.frozen_gate, **result}
    name = args.checkpoint.stem.replace("encoder_", "")
    out = Path(__file__).with_name(f"encoder_{name}_{args.split}_fixedmetric.json")
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
