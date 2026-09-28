"""Reusable standalone inference. Product values are suggestions for human review."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import yaml

from .slots import slots
from .utterance import utterance_of
from .safety import direct_rule


def load_bundle(path: Path) -> dict[str, Any]:
    bundle = joblib.load(path)
    if bundle.get("data_version") != "v3.0":
        raise ValueError("unsupported model artifact")
    return bundle


def load_mapping(path: Path) -> dict[str, dict[str, Any]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["classes"]


def classify_text(text: str, bundle: dict[str, Any],
                  mapping: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not text or not text.strip():
        raise ValueError("message text is empty")
    x = bundle["features"].transform([text])
    gx = bundle.get("gate_features", bundle["features"]).transform([text])
    gate_score = float(bundle["gate"].predict_proba(gx)[0, 1])
    safety_score = float(bundle["safety"].predict_proba(x)[0, 1])
    emergency = safety_score >= bundle["safety_threshold"]
    direct_risk = direct_rule(text)
    problem = gate_score >= bundle["gate_threshold"]
    class_scores = bundle["classes"].predict_proba(x)[0]
    best = int(class_scores.argmax())
    fine_class = str(bundle["classes"].classes_[best]) if problem else None
    utterance = utterance_of(text, str(bundle["utterance"].predict(x)[0])) if problem else None
    route = mapping[fine_class] if fine_class else mapping["not_a_problem"]
    return {
        "is_problem": bool(problem),
        "fine_class": fine_class,
        "dataset_code": route["dataset_code"],
        "product_category_suggestion": route["product_category"],
        "product_subtype_suggestion": route["product_subtype"],
        "candidate_subtypes": route.get("candidate_subtypes", []),
        "recipient_hint": route["recipient_hint"],
        "mapping_status": route["status"],
        "utterance": utterance,
        "emergency": bool(emergency),
        "emergency_source": "model" if emergency else "none",
        "urgent_human_review": bool(emergency or direct_risk),
        "direct_risk_cue": direct_risk,
        "confidence": {
            "gate_score": round(gate_score, 4),
            "class_score_uncalibrated": round(float(class_scores[best]), 4),
            "emergency_score": round(safety_score, 4),
        },
        "slots": slots(text),
        "requires_human_confirmation": bool(problem or emergency or direct_risk),
    }
