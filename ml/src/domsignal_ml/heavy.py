"""Validation-selected E5 gate + ruBERT/sparse class ensemble.

All models run locally. Outputs are preliminary and contain no input text.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
import torch
from huggingface_hub import snapshot_download
from scipy.sparse import csr_matrix, hstack
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer

from .encoder import MultiHead
from .pipeline import load_bundle, load_mapping
from .safety import direct_rule
from .slots import slots
from .utterance import utterance_of


class HeavyEngine:
    def __init__(self, ml_root: Path, device: str | None = None):
        ml_root = ml_root.resolve()
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        torch.set_num_threads(4)
        self.light = load_bundle(ml_root / "artifacts/light.joblib")
        self.mapping = load_mapping(ml_root / "configs/class_mapping.yaml")
        self.gate = joblib.load(ml_root / "artifacts/hybrid_gate_scale100.joblib")
        e5_path = snapshot_download("intfloat/multilingual-e5-base", local_files_only=True)
        self.e5 = SentenceTransformer(e5_path, device=self.device, local_files_only=True)
        self.e5.max_seq_length = 128
        checkpoint = torch.load(ml_root / "artifacts/encoder_base_positive.pt",
                                map_location="cpu", weights_only=False)
        base_dir = ml_root / "artifacts/models/rubert-base"
        self.tokenizer = AutoTokenizer.from_pretrained(str(base_dir), local_files_only=True)
        self.bert = MultiHead(str(base_dir), len(checkpoint["classes"]),
                              len(checkpoint["utterances"]))
        self.bert.load_state_dict(checkpoint["model"])
        self.bert.to(self.device).eval()
        self.class_names = np.array(list(checkpoint["classes"]))
        self.negative_index = checkpoint["classes"]["not_a_problem"]
        self.max_length = checkpoint["max_length"]
        self.sparse_class_indices = np.array([
            checkpoint["classes"][name] for name in self.light["classes"].classes_
        ])

    @torch.no_grad()
    def _class_logits(self, texts: Sequence[str], batch_size: int = 32) -> np.ndarray:
        outputs = []
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start:start + batch_size])
            tokens = self.tokenizer(batch, padding="max_length", truncation=True,
                                    max_length=self.max_length, return_tensors="pt")
            tokens = {k: v.to(self.device) for k, v in tokens.items()}
            logits = self.bert(**tokens)[0]
            outputs.append(logits.float().cpu().numpy())
        return np.concatenate(outputs)

    def predict_batch(self, texts: Sequence[str],
                      include_internal: bool = False) -> list[dict[str, Any]]:
        if not texts or any(not text or not text.strip() for text in texts):
            raise ValueError("message text is empty")
        texts = list(texts)
        embeddings = self.e5.encode(["query: " + text for text in texts], batch_size=16,
                                    show_progress_bar=False, convert_to_numpy=True,
                                    normalize_embeddings=True).astype("float32")
        x_gate = hstack((self.gate["features"].transform(texts),
                         csr_matrix(embeddings * self.gate["scale"])), format="csr")
        gate_score = self.gate["model"].predict_proba(x_gate)[:, 1]
        x_light = self.light["features"].transform(texts)
        logits = self._class_logits(texts)
        logits[:, self.negative_index] = -1e9
        bert_prob = torch.softmax(torch.tensor(logits), dim=1).numpy()
        sparse_prob = np.zeros_like(bert_prob)
        sparse_prob[:, self.sparse_class_indices] = self.light["classes"].predict_proba(x_light)
        class_prob = 0.5 * bert_prob + 0.5 * sparse_prob
        class_index = class_prob.argmax(axis=1)
        class_score = class_prob[np.arange(len(texts)), class_index]
        safety_score = self.light["safety"].predict_proba(x_light)[:, 1]
        utterance_label = self.light["utterance"].predict(x_light)
        result = []
        for i, text in enumerate(texts):
            problem = bool(gate_score[i] >= self.gate["threshold"])
            emergency = bool(safety_score[i] >= self.light["safety_threshold"])
            direct = direct_rule(text)
            fine_class = str(self.class_names[class_index[i]]) if problem else None
            route = self.mapping[fine_class] if fine_class else self.mapping["not_a_problem"]
            item = {
                "model_variant": "hybrid_e5_rubert_sparse_ensemble",
                "is_problem": problem,
                "fine_class": fine_class,
                "dataset_code": route["dataset_code"],
                "product_category_suggestion": route["product_category"],
                "product_subtype_suggestion": route["product_subtype"],
                "candidate_subtypes": route.get("candidate_subtypes", []),
                "recipient_hint": route["recipient_hint"],
                "mapping_status": route["status"],
                "utterance": utterance_of(text, str(utterance_label[i])) if problem else None,
                "emergency": emergency,
                "emergency_source": "model" if emergency else "none",
                "urgent_human_review": bool(emergency or direct),
                "direct_risk_cue": direct,
                "confidence": {
                    "gate_score": round(float(gate_score[i]), 4),
                    "class_score_uncalibrated": round(float(class_score[i]), 4),
                    "emergency_score": round(float(safety_score[i]), 4),
                },
                "slots": slots(text),
                "requires_human_confirmation": bool(problem or emergency or direct),
            }
            if include_internal:
                item["_gate_score_full"] = float(gate_score[i])
                item["_emergency_score_full"] = float(safety_score[i])
                item["_raw_class"] = str(self.class_names[class_index[i]])
            result.append(item)
        return result

    def classify_text(self, text: str) -> dict[str, Any]:
        return self.predict_batch([text])[0]


def evaluate_heavy(engine: HeavyEngine, data_root: Path, split: str,
                   with_weak_pairs: bool = False) -> dict[str, Any]:
    """Aggregate held-out metrics; no message content enters the report."""
    from sklearn.metrics import f1_score

    from .data import SOURCES, label_of, load_real, load_safety
    from .metrics import binary_report, class_report, safety_report, weak_pair_report

    data = load_real(data_root, split)
    report: dict[str, Any] = {
        "artifact_variant": "hybrid_e5_rubert_sparse_ensemble", "split": split,
        "dataset_version": "v3.0", "thresholds_selected_on": "real val / safety val",
        "sources": {},
    }
    for source in SOURCES:
        rows = data[source]
        predictions = engine.predict_batch([r["text"] for r in rows], include_internal=True)
        gold_class = np.array([label_of(r, "class") for r in rows])
        y = gold_class != "not_a_problem"
        score = np.array([p["_gate_score_full"] for p in predictions])
        pred_class = np.array([p["fine_class"] or "not_a_problem" for p in predictions])
        raw_class = np.array([p["_raw_class"] for p in predictions])
        groups = [str(r.get("family_id") or r.get("thread_id") or r["id"]) for r in rows]
        utterance_gold = np.array([label_of(r, "utterance") for r in rows])
        utterance_pred = np.array([p["utterance"] or "offtopic" for p in predictions])
        report["sources"][source] = {
            "gate": binary_report(y, score, engine.gate["threshold"], groups),
            "end_to_end_classes_all_messages": class_report(gold_class, pred_class, groups),
            "classes_on_true_problems": class_report(
                gold_class[y], raw_class[y], [g for g, flag in zip(groups, y) if flag]),
            "utterance_macro_f1_on_true_problems": round(float(f1_score(
                utterance_gold[y], utterance_pred[y], average="macro", zero_division=0)), 4),
        }
    safety_rows = load_safety(data_root, split)
    if safety_rows:
        safety_score = engine.light["safety"].predict_proba(engine.light["features"].transform(
            [r["text"] for r in safety_rows]))[:, 1]
        safety_y = np.array([bool(r["emergency"]) for r in safety_rows])
        report["safety"] = safety_report(safety_y, safety_score,
                                         engine.light["safety_threshold"])
        report["safety"]["origin_counts"] = {
            "real": sum(r["origin"] == "real" for r in safety_rows),
            "synthetic": sum(r["origin"] == "synthetic" for r in safety_rows),
        }
    if with_weak_pairs:
        report["weak_pairs"] = weak_pair_report(data_root)
    return report
