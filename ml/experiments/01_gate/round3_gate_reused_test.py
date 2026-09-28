"""Retrospective test check of the val-selected frozen-ruBERT gate.

The test split was already viewed in prior rounds. This is an exploratory
generalization check, not a new independent test. No test tuning occurs.
"""
from __future__ import annotations

import argparse
import json
import sys
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


@torch.no_grad()
def encode(texts, tokenizer, model, device, max_length):
    out = []
    model.eval()
    for start in range(0, len(texts), 32):
        batch = tokenizer(texts[start:start + 32], padding="max_length", truncation=True,
                          max_length=max_length, return_tensors="pt")
        batch = {key: tensor.to(device) for key, tensor in batch.items()}
        out.append(model.encoder(**batch).last_hidden_state[:, 0, :]
                   .float().cpu().numpy().astype("float32"))
    return np.concatenate(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    data = load_real(args.data_root, "test")
    train = load_real(args.data_root, "train")
    synthetic = [r for r in load_synthetic(args.data_root)
                 if "gate" in r["annotation"].get("use", [])]
    test_rows = [r for source in SOURCES for r in data[source]]
    train_rows = [r for source in SOURCES for r in train[source]]
    texts = [r["text"] for r in test_rows]
    gold = np.array([label_of(r, "class") for r in test_rows])
    positive = gold != "not_a_problem"
    x_train = np.vstack((np.load(ROOT / "artifacts/round3_frozen_rubert/train.npy"),
                         np.load(ROOT / "artifacts/round3_frozen_rubert/synthetic_gate.npy")))
    y_train = np.array([label_of(r, "class") != "not_a_problem"
                        for r in train_rows + synthetic])
    weights = np.r_[np.ones(len(train_rows)), np.full(len(synthetic), 0.5)]
    clf = LogisticRegression(C=10, max_iter=1000, class_weight="balanced",
                             random_state=42).fit(x_train, y_train, sample_weight=weights)
    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    cache = ROOT / "artifacts/round3_frozen_rubert/test.npy"
    if cache.is_file():
        x_test = np.load(cache)
        if x_test.shape[0] != len(test_rows):
            raise ValueError("test embedding count mismatch")
    else:
        base_dir = ROOT / "artifacts/models/rubert-base"
        tokenizer = AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True)
        model = MultiHead(str(base_dir), len(checkpoint["classes"]),
                          len(checkpoint["utterances"]))
        model.load_state_dict(checkpoint["model"])
        model.to(device)
        x_test = encode(texts, tokenizer, model, device, checkpoint["max_length"])
        np.save(cache, x_test)
    bert_gate_score = clf.predict_proba(x_test)[:, 1]
    hybrid = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    e5 = np.load(ROOT / "artifacts/embeddings_e5_base/real_test.npy")
    x = hstack((hybrid["features"].transform(texts),
                csr_matrix(e5 * hybrid["scale"])), format="csr")
    old_gate_score = hybrid["model"].predict_proba(x)[:, 1]
    new_gate_score = 0.75 * old_gate_score + 0.25 * bert_gate_score
    light = load_bundle(ROOT / "artifacts/light.joblib")
    sparse_prob = light["classes"].predict_proba(light["features"].transform(texts))
    names = np.array(list(checkpoint["classes"]))
    logits = np.load(ROOT / "artifacts/encoder_base_positive_test_logits.npz")["class_logits"].copy()
    if len(logits) != len(test_rows):
        raise ValueError("test logits count mismatch")
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
    sparse = np.zeros_like(bert_prob)
    for col, name in enumerate(light["classes"].classes_):
        sparse[:, checkpoint["classes"][name]] = sparse_prob[:, col]
    raw_class = names[((bert_prob + sparse) / 2).argmax(axis=1)]
    val_report = json.loads((Path(__file__).with_name(
        "round3_frozen_rubert_gate_val.json")).read_text(encoding="utf-8"))
    selected = val_report["selected_f1_diagnostic"]
    old_threshold = hybrid["threshold"]
    new_threshold = selected["threshold"]
    cut = len(data[SOURCES[0]])
    report = {"split": "reused_test", "tuning_on_test": False,
              "warning": "Test was viewed in earlier rounds; this is retrospective exploratory evidence.",
              "models": {}}
    for name, score, threshold in (("existing_heavy", old_gate_score, old_threshold),
                                   ("val_selected_new_gate", new_gate_score, new_threshold)):
        final = raw_class.copy()
        final[score < threshold] = "not_a_problem"
        metrics = {}
        for source, sl in ((SOURCES[0], slice(0, cut)),
                           (SOURCES[1], slice(cut, None))):
            pred_pos = score[sl] >= threshold
            p, r, _, _ = precision_recall_fscore_support(
                positive[sl], pred_pos, average="binary", zero_division=0)
            metrics[source] = {
                "n": len(gold[sl]),
                "gate_ap": round(float(average_precision_score(positive[sl], score[sl])), 4),
                "gate_precision": round(float(p), 4),
                "gate_recall": round(float(r), 4),
                "end_macro_f1": round(float(f1_score(gold[sl], final[sl],
                                                      labels=sorted(set(gold[sl])),
                                                      average="macro", zero_division=0)), 4),
            }
        report["models"][name] = {"threshold": round(float(threshold), 6),
                                  "sources": metrics,
                                  "mean_f1": round(float(np.mean([
                                      metrics[s]["end_macro_f1"] for s in SOURCES])), 4)}
    output = Path(__file__).with_name("round3_gate_reused_test.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
