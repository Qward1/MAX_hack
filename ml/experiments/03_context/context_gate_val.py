"""Ablate reply/short previous context for gate on real validation only."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import vstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.features import TextFeatures  # noqa: E402


def with_context(rows, kind):
    if kind == "none":
        return [r["text"] for r in rows], [False] * len(rows)
    by_id = {r["id"]: r for r in rows}
    previous = {}
    result = []
    has_context = []
    for row in rows:
        family = row.get("family_id") or row.get("thread_id")
        original = row["text"]
        context = []
        if kind == "reply":
            reply = by_id.get(row.get("reply_to"))
            if reply and (reply.get("family_id") or reply.get("thread_id")) == family:
                context = [reply["text"]]
        elif kind == "prev2":
            context = previous.get(family, [])[-2:]
        result.append(original + (" [КОНТЕКСТ] " + " [СООБЩЕНИЕ] ".join(context)
                                  if context else ""))
        has_context.append(bool(context))
        previous.setdefault(family, []).append(original)
    return result, has_context


def main():
    data = Path(sys.argv[1])
    tr = load_real(data, "train")
    va = load_real(data, "val")
    syn = [r for r in load_synthetic(data) if "gate" in r["annotation"].get("use", [])]
    train = [r for source in SOURCES for r in tr[source]]
    val = [r for source in SOURCES for r in va[source]]
    y = np.array([label_of(r, "class") != "not_a_problem" for r in train])
    vy = np.array([label_of(r, "class") != "not_a_problem" for r in val])
    sy = np.array([label_of(r, "class") != "not_a_problem" for r in syn])
    results = []
    for kind in ("none", "reply", "prev2"):
        start = time.perf_counter()
        train_text, train_context = with_context(train, kind)
        val_text, val_context = with_context(val, kind)
        features = TextFeatures.baseline()
        x = features.fit_transform(train_text)
        xv = features.transform(val_text)
        xs = features.transform([r["text"] for r in syn])
        xx = vstack((x, xs), format="csr")
        yy = np.r_[y, sy]
        model = LogisticRegression(C=16, solver="liblinear", max_iter=1000,
                                   class_weight="balanced", random_state=42).fit(xx, yy)
        score = model.predict_proba(xv)[:, 1]
        cursor = 0
        report = {"kind": kind, "train_context_count": int(sum(train_context)),
                  "val_context_count": int(sum(val_context)), "sources": {},
                  "seconds": round(time.perf_counter() - start, 2)}
        for source in SOURCES:
            stop = cursor + len(va[source])
            target = vy[cursor:stop]
            sub_score = score[cursor:stop]
            mask = np.array(val_context[cursor:stop])
            item = {"ap_all": round(float(average_precision_score(target, sub_score)), 4),
                    "n_with_context": int(mask.sum())}
            if mask.sum() and target[mask].any():
                item["ap_with_context_subset"] = round(float(average_precision_score(
                    target[mask], sub_score[mask])), 4)
            report["sources"][source] = item
            cursor = stop
        results.append(report)
        print(json.dumps(report), flush=True)
    Path(__file__).with_name("context_gate_val.json").write_text(
        json.dumps({"split": "val", "results": results}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
