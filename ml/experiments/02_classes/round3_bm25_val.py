"""Compare BM25 retrieval with TF-IDF retrieval and trained class heads on val.

Only train documents are indexed. Output contains aggregate metrics, no text.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import scipy.sparse as sp
import torch
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from domsignal_ml.data import SOURCES, label_of, load_real, load_synthetic  # noqa: E402
from domsignal_ml.pipeline import load_bundle  # noqa: E402


def bm25_weight(counts: sp.csr_matrix, idf: np.ndarray, average: float,
                k1: float = 1.2, b: float = 0.75) -> sp.csr_matrix:
    """BM25 document weights with IDF and average length fitted on train."""
    weights = counts.astype(np.float32).copy()
    length = np.asarray(counts.sum(axis=1)).ravel()
    row = np.repeat(np.arange(counts.shape[0]), np.diff(weights.indptr))
    tf = weights.data
    weights.data = (idf[weights.indices] * tf * (k1 + 1)
                    / (tf + k1 * (1 - b + b * length[row] / average)))
    return weights


def neighbors(query: sp.csr_matrix, index: sp.csr_matrix, y_index: np.ndarray,
              row_weights: np.ndarray, n_classes: int, ks=(1, 3, 5, 11)) -> dict:
    probabilities = {k: np.zeros((query.shape[0], n_classes), dtype=np.float32)
                     for k in ks}
    zero = 0
    maximum_k = max(ks)
    for start in range(0, query.shape[0], 256):
        score_block = (query[start:start + 256] @ index.T).tocsr()
        for local in range(score_block.shape[0]):
            begin, end = score_block.indptr[local:local + 2]
            candidates = score_block.indices[begin:end]
            values = score_block.data[begin:end]
            if not len(candidates):
                zero += 1
                continue
            top = np.argsort(values)[-maximum_k:][::-1]
            for k in ks:
                chosen = top[:k]
                vote = np.zeros(n_classes, dtype=np.float32)
                np.add.at(vote, y_index[candidates[chosen]],
                          np.sqrt(np.maximum(values[chosen], 0))
                          * row_weights[candidates[chosen]])
                if vote.sum():
                    probabilities[k][start + local] = vote / vote.sum()
    return {"probabilities": probabilities, "zero_neighbor_queries": zero}


def metric(gold: np.ndarray, predicted: np.ndarray, raw: np.ndarray,
           cut: int) -> dict:
    output = {}
    for source, sl in ((SOURCES[0], slice(0, cut)),
                       (SOURCES[1], slice(cut, None))):
        y = gold[sl]
        mask = y != "not_a_problem"
        output[source] = {
            "end_macro_f1": round(float(f1_score(y, predicted[sl], labels=sorted(set(y)),
                                                  average="macro", zero_division=0)), 4),
            "positive_head_macro_f1": round(float(f1_score(
                y[mask], raw[sl][mask], labels=sorted(set(y[mask])),
                average="macro", zero_division=0)), 4),
        }
    output["mean_end_f1"] = round(float(np.mean([
        output[s]["end_macro_f1"] for s in SOURCES])), 4)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    start_time = time.perf_counter()
    train = load_real(args.data_root, "train")
    val = load_real(args.data_root, "val")
    synthetic = load_synthetic(args.data_root)
    train_rows = [r for source in SOURCES for r in train[source]]
    val_rows = [r for source in SOURCES for r in val[source]]
    positives = [r for r in train_rows if label_of(r, "class") != "not_a_problem"]
    positives += [r for r in synthetic if label_of(r, "class") != "not_a_problem"]
    train_text = [r["text"] for r in positives]
    val_text = [r["text"] for r in val_rows]
    gold = np.array([label_of(r, "class") for r in val_rows])
    cut = len(val[SOURCES[0]])
    names = np.array(sorted({label_of(r, "class") for r in positives}))
    name_index = {name: i for i, name in enumerate(names)}
    y_index = np.array([name_index[label_of(r, "class")] for r in positives])
    row_weights = np.ones(len(positives), dtype=np.float32)
    # Synthetic rows are appended after real positives. Use their known boundary,
    # independent of optional metadata in the source file.
    row_weights[len(positives) - sum(label_of(r, "class") != "not_a_problem"
                                     for r in synthetic):] = 0.5

    light = load_bundle(ROOT / "artifacts/light.joblib")
    hybrid = joblib.load(ROOT / "artifacts/hybrid_gate_scale100.joblib")
    embedding = np.load(ROOT / "artifacts/embeddings_e5_base/real_val.npy")
    gate_x = sp.hstack((hybrid["features"].transform(val_text),
                        sp.csr_matrix(embedding * hybrid["scale"])), format="csr")
    gate_score = hybrid["model"].predict_proba(gate_x)[:, 1]
    accepted = gate_score >= hybrid["threshold"]

    checkpoint = torch.load(ROOT / "artifacts/encoder_base_positive.pt",
                            map_location="cpu", weights_only=False)
    logits = np.load(ROOT / "artifacts/encoder_base_positive_val_logits.npz")[
        "class_logits"].copy()
    logits[:, checkpoint["classes"]["not_a_problem"]] = -1e9
    bert_prob_full = torch.softmax(torch.tensor(logits), dim=1).numpy()
    bert_prob = np.stack([bert_prob_full[:, checkpoint["classes"][name]]
                          for name in names], axis=1)

    def evaluate(name: str, prob: np.ndarray, details: dict) -> dict:
        raw = names[prob.argmax(axis=1)]
        predicted = raw.copy()
        predicted[~accepted] = "not_a_problem"
        return {"method": name, **details, **metric(gold, predicted, raw, cut)}

    results = [evaluate("bert_only", bert_prob, {})]
    sparse_prob = light["classes"].predict_proba(light["features"].transform(val_text))
    sparse_aligned = np.zeros_like(bert_prob)
    for i, name in enumerate(light["classes"].classes_):
        sparse_aligned[:, name_index[name]] = sparse_prob[:, i]
    results.append(evaluate("trained_tfidf_head", sparse_aligned, {}))
    results.append(evaluate("existing_50_50", 0.5 * bert_prob + 0.5 * sparse_aligned, {}))

    count_vectorizer = CountVectorizer(ngram_range=(1, 2), min_df=2,
                                       max_features=150000, dtype=np.float32)
    counts = count_vectorizer.fit_transform(train_text).tocsr()
    val_counts = count_vectorizer.transform(val_text).tocsr()
    n_docs = counts.shape[0]
    df = np.diff(counts.tocsc().indptr)
    idf = np.log1p((n_docs - df + 0.5) / (df + 0.5)).astype(np.float32)
    average = float(np.asarray(counts.sum(axis=1)).ravel().mean())
    bm25 = bm25_weight(counts, idf, average)
    val_bm25 = bm25_weight(val_counts, idf, average)
    for normalization, train_x, val_x in (
            ("none", bm25, val_bm25),
            ("l2", normalize(bm25), normalize(val_bm25))):
        for c in (1.0, 16.0):
            t0 = time.perf_counter()
            clf = LogisticRegression(C=c, solver="liblinear", max_iter=1000,
                                     class_weight="balanced", random_state=42)
            clf.fit(train_x, names[y_index], sample_weight=row_weights)
            predicted_prob = clf.predict_proba(val_x)
            aligned = np.zeros((len(val_text), len(names)), dtype=np.float32)
            for column, class_name in enumerate(clf.classes_):
                aligned[:, name_index[class_name]] = predicted_prob[:, column]
            results.append(evaluate("bm25_linear", aligned,
                {"normalization": normalization, "C": c,
                 "train_seconds": round(time.perf_counter() - t0, 2)}))
    for name, query, index in (
        ("word_bm25", val_counts, bm25),
        ("word_tfidf", None, None),
        ("char_tfidf", None, None),
    ):
        t0 = time.perf_counter()
        if name == "word_tfidf":
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2,
                                         max_features=150000, dtype=np.float32)
            index = vectorizer.fit_transform(train_text).tocsr()
            query = vectorizer.transform(val_text).tocsr()
            for c in (1.0, 16.0):
                fitted = LogisticRegression(C=c, solver="liblinear", max_iter=1000,
                                            class_weight="balanced", random_state=42)
                fitted.fit(index, names[y_index], sample_weight=row_weights)
                prediction = fitted.predict_proba(query)
                aligned = np.zeros((len(val_text), len(names)), dtype=np.float32)
                for column, class_name in enumerate(fitted.classes_):
                    aligned[:, name_index[class_name]] = prediction[:, column]
                results.append(evaluate("word_tfidf_linear", aligned, {"C": c}))
        elif name == "char_tfidf":
            vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5),
                                         min_df=2, max_features=180000,
                                         dtype=np.float32)
            index = vectorizer.fit_transform(train_text).tocsr()
            query = vectorizer.transform(val_text).tocsr()
        found = neighbors(query, index, y_index, row_weights, len(names))
        elapsed = round(time.perf_counter() - t0, 2)
        for k, prob in found["probabilities"].items():
            item = evaluate(name, prob, {"k": k, "elapsed_seconds": elapsed,
                                         "zero_neighbor_queries": found[
                                             "zero_neighbor_queries"]})
            results.append(item)
            if name == "word_bm25" and k in (3, 5, 11):
                for weight in (0.1, 0.25, 0.5):
                    results.append(evaluate("bert_plus_bm25",
                        (1 - weight) * bert_prob + weight * prob,
                        {"k": k, "bm25_weight": weight}))
        print(json.dumps({"retriever": name, "seconds": elapsed,
                          "zero_neighbor_queries": found["zero_neighbor_queries"]}),
              flush=True)

    report = {"split": "val", "seed": 42, "train_real_positive": sum(
              label_of(r, "class") != "not_a_problem" for r in train_rows),
              "train_synthetic_positive": len(positives) - sum(
                  label_of(r, "class") != "not_a_problem" for r in train_rows),
              "gate": "frozen hybrid_gate_scale100", "bm25_k1": 1.2,
              "bm25_b": 0.75, "total_seconds": round(time.perf_counter() - start_time, 2),
              "best": max(results, key=lambda r: r["mean_end_f1"]),
              "results": results}
    output = Path(__file__).with_name("round3_bm25_val.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"best": report["best"], "total_seconds": report["total_seconds"]}))


if __name__ == "__main__":
    main()
