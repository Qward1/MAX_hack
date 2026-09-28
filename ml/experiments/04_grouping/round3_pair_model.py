"""Train a local incident-pair model on one assistant-annotated chat day.

The two later days are an exploratory audit because they were viewed in earlier
experiments. No raw messages are written to the report.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml
from huggingface_hub import snapshot_download
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.grouping import _tokens  # noqa: E402
from domsignal_ml.pipeline import classify_text, load_bundle, load_mapping  # noqa: E402
from domsignal_ml.slots import slots  # noqa: E402
from manual_review import message_key  # noqa: E402
from replay_real import load_day  # noqa: E402


def moment(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def prf(y, pred) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y, pred, average="binary",
                                                 zero_division=0)
    return {"precision": round(float(p), 4), "recall": round(float(r), 4),
            "f1": round(float(f), 4), "tp": int(np.sum(y & pred)),
            "fp": int(np.sum(~y & pred)), "fn": int(np.sum(y & ~pred))}


def day_features(rows: list[tuple], gold: list[dict], e5, light, mapping) -> dict:
    texts = [r["text"] for _, r in rows]
    vectors = e5.encode(["query: " + t for t in texts], batch_size=16,
                        normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False)
    preds = [classify_text(t, light, mapping) for t in texts]
    tokens = [_tokens(t) for t in texts]
    locations = [slots(t) for t in texts]
    times = [moment(r["ts"]) for _, r in rows]
    scorable = [i for i, g in enumerate(gold) if g["role"] != "uncertain"]
    all_pairs = []
    candidates = []
    features = []
    labels = []
    for pos, i in enumerate(scorable):
        for j in scorable[pos + 1:]:
            same = bool(set(gold[i]["incident_ids"]) & set(gold[j]["incident_ids"]))
            all_pairs.append((i, j, same))
            hours = (times[j] - times[i]).total_seconds() / 3600
            if not 0 <= hours <= 24:
                continue
            union = len(tokens[i] | tokens[j])
            lexical = len(tokens[i] & tokens[j]) / union if union else 0
            ci, cj = preds[i]["fine_class"], preds[j]["fine_class"]
            ent_i, ent_j = locations[i].get("entrance"), locations[j].get("entrance")
            reply = rows[j][1].get("reply_to") == rows[i][1]["id"]
            vector = [float(np.dot(vectors[i], vectors[j])), lexical,
                      np.log1p(hours), float(reply), float(ci == cj and ci is not None),
                      float(ci is not None), float(cj is not None),
                      float(ent_i is not None and ent_i == ent_j),
                      float(ent_i is not None and ent_j is not None and ent_i != ent_j)]
            candidates.append((i, j))
            features.append(vector)
            labels.append(same)
    return {"rows": rows, "gold": gold, "scorable": scorable,
            "all_pairs": all_pairs, "candidates": candidates,
            "features": np.asarray(features, dtype="float32"),
            "labels": np.asarray(labels, dtype=bool), "predictions": preds}


def cluster_score(day: dict, edges: set[tuple[int, int]]) -> dict:
    parent = list(range(len(day["rows"])))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in edges:
        a, b = find(i), find(j)
        parent[b] = a
    linked = {i for edge in edges for i in edge}
    ids = {i: find(i) for i in linked}
    actual, predicted = [], []
    for i, j, same in day["all_pairs"]:
        actual.append(same)
        predicted.append(i in ids and j in ids and ids[i] == ids[j])
    return prf(np.array(actual, dtype=bool), np.array(predicted, dtype=bool))


def constrained_edges(day: dict, scores: np.ndarray, threshold: float,
                      top_k: int, class_guard: bool) -> set[tuple[int, int]]:
    """Use reciprocal high-scoring neighbours; prevent bridging by arbitrary chains."""
    candidates = day["candidates"]
    features = day["features"]
    neighbours: dict[int, list[tuple[float, int]]] = {}
    eligible = []
    for pos, ((i, j), score) in enumerate(zip(candidates, scores)):
        if score < threshold:
            continue
        if class_guard and not (features[pos, 4] > 0.5 or features[pos, 3] > 0.5):
            continue
        eligible.append(pos)
        neighbours.setdefault(i, []).append((float(score), j))
        neighbours.setdefault(j, []).append((float(score), i))
    top = {i: {other for _, other in sorted(links, reverse=True)[:top_k]}
           for i, links in neighbours.items()}
    return {(candidates[pos][0], candidates[pos][1]) for pos in eligible
            if candidates[pos][1] in top[candidates[pos][0]]
            and candidates[pos][0] in top[candidates[pos][1]]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    annotations = [json.loads(line) for line in
                   (HERE / "manual_gold_v1.jsonl").read_text(encoding="utf-8").splitlines()]
    spec = yaml.safe_load((HERE / "manual_incidents_v1.yaml").read_text(encoding="utf-8"))
    path = snapshot_download("intfloat/multilingual-e5-base", local_files_only=True)
    e5 = SentenceTransformer(path, device="cpu", local_files_only=True)
    e5.max_seq_length = 128
    light = load_bundle(ROOT / "artifacts/light.joblib")
    mapping = load_mapping(ROOT / "configs/class_mapping.yaml")
    days = {}
    for day, config in spec["days"].items():
        rows = load_day(args.data_root, day)
        gold = [g for g in annotations if g["day"] == day]
        if len(rows) != len(gold) or any(g["message_key"] != message_key(s, r["id"])
                                             for (s, r), g in zip(rows, gold)):
            raise ValueError("annotation/source mismatch")
        days[day] = (config["purpose"], day_features(rows, gold, e5, light, mapping))
    dev_days = [d for purpose, d in days.values() if purpose == "development"]
    audit_days = [d for purpose, d in days.values() if purpose == "heldout"]
    train_x = np.vstack([d["features"] for d in dev_days])
    train_y = np.concatenate([d["labels"] for d in dev_days])
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1, class_weight="balanced",
                                                                max_iter=1000, random_state=42))
    model.fit(train_x, train_y)
    train_score = model.predict_proba(train_x)[:, 1]
    thresholds = np.arange(0.05, 0.951, 0.025)
    threshold = max(thresholds, key=lambda t: prf(train_y, train_score >= t)["f1"])
    strict_candidates = []
    for t in np.r_[thresholds, 0.975, 0.99, 0.995]:
        metrics = []
        for day in dev_days:
            scores = model.predict_proba(day["features"])[:, 1]
            edges = {edge for edge, yes in zip(day["candidates"], scores >= t) if yes}
            metrics.append(cluster_score(day, edges))
        tp = sum(m["tp"] for m in metrics)
        fp = sum(m["fp"] for m in metrics)
        fn = sum(m["fn"] for m in metrics)
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        if precision >= 0.9:
            strict_candidates.append((f1, float(t)))
    strict_threshold = max(strict_candidates)[1] if strict_candidates else None
    constrained = []
    for top_k in (1, 2, 3):
        for class_guard in (False, True):
            for t in np.r_[thresholds, 0.975, 0.99, 0.995]:
                metrics = []
                for day in dev_days:
                    scores = model.predict_proba(day["features"])[:, 1]
                    edges = constrained_edges(day, scores, float(t), top_k, class_guard)
                    metrics.append(cluster_score(day, edges))
                tp = sum(m["tp"] for m in metrics)
                fp = sum(m["fp"] for m in metrics)
                fn = sum(m["fn"] for m in metrics)
                p = tp / (tp + fp) if tp + fp else 0
                r = tp / (tp + fn) if tp + fn else 0
                f1 = 2 * p * r / (p + r) if p + r else 0
                if p >= 0.9:
                    constrained.append((f1, r, -float(t), top_k, class_guard))
    best_constrained = max(constrained) if constrained else None
    report = {"threshold_selected_on": "development_day_pair_f1",
              "independent_human_gold": False,
              "caveat": "Assistant annotations and previously viewed audit days.",
              "threshold": round(float(threshold), 4),
              "strict_cluster_threshold_precision_090_on_development": strict_threshold,
              "constrained_selected_on_development": (
                  {"threshold": -best_constrained[2], "top_k": best_constrained[3],
                   "class_guard": best_constrained[4],
                   "development_f1": round(best_constrained[0], 4)}
                  if best_constrained else None),
              "days": {}}
    for name, (_, day) in days.items():
        scores = model.predict_proba(day["features"])[:, 1]
        pair_pred = scores >= threshold
        edges = {edge for edge, yes in zip(day["candidates"], pair_pred) if yes}
        report["days"][name] = {
            "purpose": spec["days"][name]["purpose"],
            "messages": len(day["rows"]),
            "all_positive_pairs": sum(same for _, _, same in day["all_pairs"]),
            "candidate_pairs": len(day["candidates"]),
            "candidate_positive_pairs": int(day["labels"].sum()),
            "candidate_pair_score": prf(day["labels"], pair_pred),
            "cluster_all_pair_score": cluster_score(day, edges),
        }
        if strict_threshold is not None:
            strict_edges = {edge for edge, yes in zip(day["candidates"],
                                scores >= strict_threshold) if yes}
            report["days"][name]["strict_cluster_all_pair_score"] = cluster_score(
                day, strict_edges)
        if best_constrained is not None:
            constrained_links = constrained_edges(day, scores, -best_constrained[2],
                                                  best_constrained[3], best_constrained[4])
            report["days"][name]["constrained_cluster_all_pair_score"] = cluster_score(
                day, constrained_links)
    output = HERE / "round3_pair_model.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
