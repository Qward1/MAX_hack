"""Fine-tune a Russian encoder with flat or masked multitask heads.

Select checkpoint on real validation only. No test data or external API calls.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import torch
from sklearn.metrics import average_precision_score, f1_score
from torch import nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_safety, load_synthetic  # noqa: E402
from domsignal_ml.encoder import MultiHead  # noqa: E402


class EncodedRows(Dataset):
    def __init__(self, tokenizer, rows, max_length, classes, utterances):
        tokens = tokenizer([r["text"] for r in rows], truncation=True,
                           padding="max_length", max_length=max_length,
                           return_tensors="pt")
        self.tokens = tokens
        self.class_y = torch.tensor([classes.get(r.get("class"), -100) for r in rows])
        self.gate_y = torch.tensor([int(r["class"] != "not_a_problem")
                                    if r.get("class") else -100 for r in rows])
        self.utt_y = torch.tensor([utterances.get(r.get("utterance"), -100) for r in rows])
        self.safety_y = torch.tensor([int(r["emergency"]) if r.get("emergency") is not None
                                      else -100 for r in rows])
        self.weight = torch.tensor([r.get("weight", 1.0) for r in rows], dtype=torch.float32)

    def __len__(self):
        return len(self.class_y)

    def __getitem__(self, index):
        return {**{key: value[index] for key, value in self.tokens.items()},
                "class_y": self.class_y[index], "gate_y": self.gate_y[index],
                "utt_y": self.utt_y[index], "safety_y": self.safety_y[index],
                "weight": self.weight[index]}


def rows_for_train(data: Path, include_safety: bool):
    real = load_real(data, "train")
    syn = load_synthetic(data)
    rows = []
    for source in SOURCES:
        for r in real[source]:
            rows.append({"text": r["text"], "class": label_of(r, "class"),
                         "utterance": label_of(r, "utterance"),
                         "emergency": label_of(r, "emergency"), "weight": 1.0})
    for r in syn:
        rows.append({"text": r["text"], "class": label_of(r, "class"),
                     "utterance": label_of(r, "utterance"),
                     "emergency": label_of(r, "emergency"), "weight": 0.5})
    if include_safety:
        for r in load_safety(data, "train"):
            rows.append({"text": r["text"], "emergency": bool(r["emergency"]),
                         "weight": 1.0})
    return rows, real, syn


@torch.no_grad()
def predict(model, loader, device):
    model.eval()
    collected = [[], [], [], []]
    for batch in loader:
        logits = model(batch["input_ids"].to(device), batch["attention_mask"].to(device),
                       batch.get("token_type_ids", None).to(device)
                       if "token_type_ids" in batch else None)
        for bucket, tensor in zip(collected, logits):
            bucket.append(tensor.float().cpu().numpy())
    return [np.concatenate(bucket) for bucket in collected]


def score_val(logits, val_rows, classes, source_lengths, frozen_gate=None):
    label_names = np.array(list(classes))
    class_logits, gate_logits = logits[0], logits[1]
    class_prob = torch.softmax(torch.tensor(class_logits), dim=1).numpy()
    gate_prob = torch.softmax(torch.tensor(gate_logits), dim=1).numpy()[:, 1]
    class_pred = label_names[class_prob.argmax(axis=1)]
    flat_gate = 1 - class_prob[:, classes["not_a_problem"]]
    result = {"sources": {}}
    start = 0
    for source, length in zip(SOURCES, source_lengths):
        stop = start + length
        gold = np.array([row["class"] for row in val_rows[start:stop]])
        pos = gold != "not_a_problem"
        sl = slice(start, stop)
        item = {
            "macro_f1": round(float(f1_score(gold, class_pred[sl], labels=sorted(set(gold)),
                                               average="macro", zero_division=0)), 4),
            "gate_ap_flat": round(float(average_precision_score(pos, flat_gate[sl])), 4),
            "gate_ap_head": round(float(average_precision_score(pos, gate_prob[sl])), 4),
            "class_f1_true_positives": round(float(f1_score(
                gold[pos], class_pred[sl][pos], labels=sorted(set(gold[pos])),
                average="macro", zero_division=0)), 4),
        }
        if frozen_gate is not None:
            frozen_score, frozen_threshold = frozen_gate
            combined = class_pred[sl].copy()
            combined[frozen_score[sl] < frozen_threshold] = "not_a_problem"
            item["end_f1_with_frozen_gate"] = round(float(f1_score(
                gold, combined, labels=sorted(set(gold)), average="macro", zero_division=0)), 4)
        result["sources"][source] = item
        start = stop
    result["mean_macro_f1"] = round(float(np.mean([
        item["macro_f1"] for item in result["sources"].values()])), 4)
    if frozen_gate is not None:
        result["mean_end_f1_with_frozen_gate"] = round(float(np.mean([
            item["end_f1_with_frozen_gate"] for item in result["sources"].values()])), 4)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--mode", choices=["flat", "multi"], required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=96)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--class-weights", choices=["none", "moderate"], default="moderate")
    parser.add_argument("--positive-only", action="store_true")
    parser.add_argument("--negative-ratio", type=float, default=0.0,
                        help="if >0, keep this many real negatives per real positive")
    parser.add_argument("--limit", type=int, default=0, help="debug only; must not report metrics")
    args = parser.parse_args()
    torch.manual_seed(42)
    np.random.seed(42)
    torch.set_num_threads(4)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    start = time.perf_counter()
    rows, real, syn = rows_for_train(args.data_root, args.mode == "multi")
    if args.positive_only:
        rows = [r for r in rows if r.get("class") and r["class"] != "not_a_problem"]
    elif args.negative_ratio > 0:
        real_positive = [r for r in rows if r.get("class") not in (None, "not_a_problem")
                         and r["weight"] == 1.0]
        real_negative = [r for r in rows if r.get("class") == "not_a_problem"
                         and r["weight"] == 1.0]
        other = [r for r in rows if r["weight"] != 1.0 or r.get("class") is None]
        rng = np.random.default_rng(42)
        keep = rng.choice(len(real_negative), size=min(len(real_negative),
                          round(len(real_positive) * args.negative_ratio)), replace=False)
        rows = real_positive + [real_negative[i] for i in keep] + other
    if args.limit:
        rows = rows[:args.limit]
    val = load_real(args.data_root, "val")
    val_rows = [{"text": r["text"], "class": label_of(r, "class")}
                for source in SOURCES for r in val[source]]
    frozen_gate = None
    if args.positive_only:
        from domsignal_ml.pipeline import load_bundle
        bundle = load_bundle(ROOT / "artifacts/light.joblib")
        gate_score = bundle["gate"].predict_proba(bundle["gate_features"].transform(
            [r["text"] for r in val_rows]))[:, 1]
        frozen_gate = (gate_score, bundle["gate_threshold"])
    class_names = sorted({label_of(r, "class") for source in SOURCES for r in real[source]}
                         | {label_of(r, "class") for r in syn})
    utt_names = sorted({label_of(r, "utterance") for source in SOURCES for r in real[source]})
    classes = {name: i for i, name in enumerate(class_names)}
    utterances = {name: i for i, name in enumerate(utt_names)}
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    train_set = EncodedRows(tokenizer, rows, args.max_length, classes, utterances)
    val_set = EncodedRows(tokenizer, val_rows, args.max_length, classes, utterances)
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=args.batch_size * 2)
    model = MultiHead(str(args.model), len(classes), len(utterances)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    total_steps = args.epochs * len(train_loader)
    warmup = max(1, round(total_steps * 0.08))
    def lr_factor(step):
        return min((step + 1) / warmup, max(0.0, (total_steps - step) / max(1, total_steps - warmup)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_factor)
    scaler = torch.amp.GradScaler("cuda", enabled=device == "cuda")
    counts = np.bincount(train_set.class_y[train_set.class_y >= 0].numpy(), minlength=len(classes))
    weight = np.ones(len(classes), dtype=np.float32)
    if args.class_weights == "moderate":
        weight[classes["not_a_problem"]] = 0.25
        for name, index in classes.items():
            if name != "not_a_problem":
                weight[index] = min(3.0, math.sqrt(100.0 / max(1, counts[index])))
    class_weight = torch.tensor(weight, device=device)
    history = []
    best = -1.0
    checkpoint = ROOT / "artifacts" / f"encoder_{args.name}.pt"
    for epoch in range(args.epochs):
        model.train()
        total_loss = 0.0
        for batch in train_loader:
            optimizer.zero_grad(set_to_none=True)
            input_ids = batch["input_ids"].to(device)
            attention = batch["attention_mask"].to(device)
            token_types = batch["token_type_ids"].to(device) if "token_type_ids" in batch else None
            cy = batch["class_y"].to(device)
            gy = batch["gate_y"].to(device)
            uy = batch["utt_y"].to(device)
            sy = batch["safety_y"].to(device)
            sw = batch["weight"].to(device)
            with torch.amp.autocast("cuda", dtype=torch.float16, enabled=device == "cuda"):
                cl, gl, ul, sl = model(input_ids, attention, token_types)
                loss = torch.zeros((), device=device)
                if (cy >= 0).any():
                    active = cy >= 0
                    ce = nn.functional.cross_entropy(cl[active], cy[active],
                                                     weight=class_weight, reduction="none")
                    loss = loss + (ce * sw[active]).sum() / sw[active].sum()
                if args.mode == "multi":
                    for labels, predictions, factor in ((gy, gl, 0.35),
                                                         (uy, ul, 0.20),
                                                         (sy, sl, 0.20)):
                        active = labels >= 0
                        if active.any():
                            ce = nn.functional.cross_entropy(predictions[active], labels[active],
                                                             reduction="none")
                            loss = loss + factor * (ce * sw[active]).sum() / sw[active].sum()
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            previous_scale = scaler.get_scale()
            scaler.step(optimizer)
            scaler.update()
            if scaler.get_scale() >= previous_scale:
                scheduler.step()
            total_loss += float(loss.detach().cpu())
        predictions = predict(model, val_loader, device)
        metrics = score_val(predictions, val_rows, classes,
                            [len(val[source]) for source in SOURCES], frozen_gate)
        item = {"epoch": epoch + 1, "loss": round(total_loss / len(train_loader), 4),
                "seconds_so_far": round(time.perf_counter() - start, 1), **metrics}
        history.append(item)
        print(json.dumps(item), flush=True)
        target = item.get("mean_end_f1_with_frozen_gate", item["mean_macro_f1"])
        if not args.limit and target > best:
            best = target
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"model": {key: value.detach().cpu() for key, value in model.state_dict().items()}, "classes": classes,
                        "utterances": utterances, "pretrained": str(args.model),
                        "mode": args.mode, "max_length": args.max_length,
                        "epoch": epoch + 1}, checkpoint)
    result = {"name": args.name, "mode": args.mode, "model": str(args.model),
              "seed": 42, "epochs": args.epochs, "batch_size": args.batch_size,
              "max_length": args.max_length, "lr": args.lr,
              "class_weights": args.class_weights, "train_rows": len(rows),
              "positive_only": args.positive_only, "negative_ratio": args.negative_ratio,
              "real_train": sum(len(real[s]) for s in SOURCES), "synthetic_train": len(syn),
              "device": device, "gpu_peak_mb": round(torch.cuda.max_memory_allocated() / 2**20, 1)
              if device == "cuda" else None,
              "rss_mb": round(psutil.Process().memory_info().rss / 2**20, 1),
              "total_seconds": round(time.perf_counter() - start, 1),
              "best_val_mean_macro_f1": best, "history": history,
              "checkpoint_bytes": checkpoint.stat().st_size if checkpoint.is_file() else None}
    out = Path(__file__).with_name(f"encoder_{args.name}_val.json")
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result_file": str(out), "best": best, "seconds": result["total_seconds"]}))


if __name__ == "__main__":
    main()
