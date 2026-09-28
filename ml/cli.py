"""Console entry point: train, single, chat, replay, eval."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ML_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ML_ROOT / "src"))

from domsignal_ml.data import ensure_v3  # noqa: E402
from domsignal_ml.grouping import ChatTracker  # noqa: E402
from domsignal_ml.metrics import evaluate, save_report, weak_pair_report  # noqa: E402
from domsignal_ml.pipeline import classify_text, load_bundle, load_mapping  # noqa: E402
from domsignal_ml.train import save_result, train  # noqa: E402

DEFAULT_ARTIFACT = ML_ROOT / "artifacts" / "light.joblib"
DEFAULT_MAPPING = ML_ROOT / "configs" / "class_mapping.yaml"


def data_root(value: str | None) -> Path:
    candidates = [
        value, os.environ.get("DOMSIGNAL_DATASETS_ROOT"),
        str(ML_ROOT.parent / "datasets"),
        str(ML_ROOT.parent.parent / "MAX_hack" / "datasets"),
    ]
    for candidate in candidates:
        if candidate:
            path = Path(candidate)
            if (path / "labels_taxonomy.yaml").is_file():
                return ensure_v3(path)
    raise FileNotFoundError("v3.0 data not found; pass --data-root")


def json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def add_model(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine", choices=["light", "heavy"], default="light")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Standalone DomSignal ML")
    sub = root.add_subparsers(dest="mode", required=True)
    fit = sub.add_parser("train", help="fit on train; choose thresholds on val")
    fit.add_argument("--data-root")
    fit.add_argument("--variant", choices=["real", "synthetic_classes",
                                             "synthetic_gate_classes", "best"], default="best")
    fit.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    fit.add_argument("--output", type=Path)
    single = sub.add_parser("single", help="classify one message")
    add_model(single)
    single.add_argument("--text", help="message; if omitted read stdin")
    for name in ("chat", "replay"):
        stream = sub.add_parser(name, help="stream JSONL messages (id,text,ts,reply_to,house_id)")
        add_model(stream)
        stream.add_argument("--file", type=Path, help="input JSONL; default stdin")
        stream.add_argument("--limit", type=int, default=0)
        stream.add_argument("--merge-policy", choices=["conservative", "broad_6h",
                                                       "broad_24h", "service_context_6h"],
                            default="conservative")
    ev = sub.add_parser("eval", help="aggregate metrics on val/test; no raw text output")
    add_model(ev)
    ev.add_argument("--data-root")
    ev.add_argument("--split", choices=["val", "test"], default="test")
    ev.add_argument("--output", type=Path)
    ev.add_argument("--weak-pairs", action="store_true")
    return root


def run_stream(args: argparse.Namespace,
               predict: Callable[[str], dict[str, Any]]) -> None:
    tracker = ChatTracker(merge_policy=args.merge_policy)
    stream = args.file.open(encoding="utf-8") if args.file else sys.stdin
    try:
        for index, line in enumerate(stream):
            if args.limit and index >= args.limit:
                break
            if not line.strip():
                continue
            message = json.loads(line)
            prediction = predict(str(message["text"]))
            event = tracker.consume(message, prediction)
            json_print({"prediction": prediction, "event": event})
    finally:
        if args.file:
            stream.close()


def main() -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    if args.mode == "train":
        root = data_root(args.data_root)
        summary = train(root, args.artifact, args.variant)
        output = args.output or ML_ROOT / "experiments" / f"train_{args.variant}.json"
        save_result(summary, output)
        json_print({"artifact": str(args.artifact), "summary": summary,
                    "result_file": str(output)})
        return 0
    heavy = None
    if args.engine == "heavy":
        from domsignal_ml.heavy import HeavyEngine, evaluate_heavy
        heavy = HeavyEngine(ML_ROOT)
        variant = "hybrid_e5_rubert_sparse_ensemble"
    else:
        bundle = load_bundle(args.artifact)
        variant = bundle["variant"]
    if args.mode == "eval":
        root = data_root(args.data_root)
        if heavy is not None:
            report = evaluate_heavy(heavy, root, args.split, args.weak_pairs)
        else:
            report = evaluate(bundle, root, args.split)
        if args.weak_pairs and heavy is None:
            report["weak_pairs"] = weak_pair_report(root)
        output = args.output or ML_ROOT / "experiments" / (
            f"eval_{variant}_{args.split}.json")
        save_report(report, output)
        compact = {
            name: {
                "gate_ap": item["gate"]["ap"],
                "gate_ap_ci95": item["gate"]["ap_ci95_group_bootstrap"],
                "gate_precision": item["gate"]["precision_at_val_threshold"],
                "gate_recall": item["gate"]["recall_at_val_threshold"],
                "class_macro_f1": item["classes_on_true_problems"]["macro_f1"],
                "end_to_end_macro_f1": item["end_to_end_classes_all_messages"]["macro_f1"],
            }
            for name, item in report["sources"].items()
        }
        json_print({"split": args.split, "variant": variant,
                    "sources": compact, "safety": report.get("safety"),
                    "weak_pairs": report.get("weak_pairs"), "result_file": str(output)})
        return 0
    if heavy is not None:
        predict = heavy.classify_text
    else:
        mapping = load_mapping(args.mapping)
        predict = lambda message: classify_text(message, bundle, mapping)
    if args.mode == "single":
        message = args.text if args.text is not None else sys.stdin.read()
        json_print(predict(message))
        return 0
    run_stream(args, predict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
