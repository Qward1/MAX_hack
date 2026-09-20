"""Метрики оценки AI-ядра на синтетических наборах.

Все числа здесь — **внутривыборочные оценки на синтетике**. Авторы данных и
авторы правил пересекаются, поэтому это ориентир регрессии, а не измерение
качества на реальных сообщениях жителей.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from domsignal.ai import (
    OpenItem,
    WindowAnalysis,
    WindowAnalyzer,
    WindowInput,
    WindowLine,
    passes_recall_gate,
)
from domsignal.ai.windowing import build_windows
from domsignal.core.incidents import ReportCategory

DATASETS = pathlib.Path("datasets/synthetic")
RELEVANT_ROLES = frozenset({"new_problem", "me_too", "more_info", "objection"})
BASE_TIME = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sha256_of(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson(successes: int, total: int) -> tuple[float, float]:
    """Интервал Уилсона 95 % для доли."""
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    phat = successes / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    spread = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (
        max(0.0, (centre - spread) / denominator),
        min(1.0, (centre + spread) / denominator),
    )


def ratio(successes: int, total: int) -> dict[str, Any]:
    low, high = wilson(successes, total)
    return {
        "k": successes,
        "n": total,
        "value": round(successes / total, 4) if total else None,
        "ci95": [round(low, 4), round(high, 4)] if total else None,
    }


@dataclass
class Counter:
    n: int = 0
    role_ok: int = 0
    n_problem: int = 0
    cat_exact: int = 0
    cat_any: int = 0
    missed_problem: int = 0
    subtype_known: int = 0
    n_nonproblem: int = 0
    false_problem: int = 0
    n_emergency: int = 0
    emergency_hit: int = 0
    emergency_false: int = 0
    n_entrance: int = 0
    entrance_ok: int = 0
    entrance_invented: int = 0
    gate_pass_problem: int = 0
    n_scope: int = 0
    scope_ok: int = 0

    def merge(self, other: Counter) -> None:
        for name, value in other.__dict__.items():
            setattr(self, name, getattr(self, name) + value)


@dataclass
class Prediction:
    role: str
    categories: set[ReportCategory]
    subtypes: list[str]
    emergency: bool
    entrance: str | None
    scope: str


def _line(index: int, text: str, author: str = "resident", minute: int = 0,
          line_id: str | None = None, reply_to: str | None = None) -> WindowLine:
    return WindowLine(
        line_id=line_id or f"m{index}",
        author_ref=author,
        text=text,
        sent_at=BASE_TIME + timedelta(minutes=minute),
        reply_to=reply_to,
    )


def predict(analysis: WindowAnalysis, line_id: str) -> Prediction:
    verdict = next((item for item in analysis.lines if item.line_id == line_id), None)
    signals = [signal for signal in analysis.signals if line_id in signal.line_ids]
    scope = next(
        (signal.location_scope.value for signal in signals
         if signal.location_scope.value != "unknown"),
        "unknown",
    )
    entrance = next(
        (signal.entrance.value for signal in signals if signal.entrance is not None), None
    )
    return Prediction(
        role=verdict.role if verdict else "chatter",
        categories={signal.product_category for signal in signals},
        subtypes=[signal.subtype for signal in signals],
        emergency=any(signal.emergency.is_emergency for signal in signals),
        entrance=entrance,
        scope=scope,
    )


async def analyze_single(analyzer: WindowAnalyzer, text: str) -> tuple[WindowAnalysis, str]:
    window = WindowInput(channel="group_report", lines=(_line(1, text),))
    return await analyzer.analyze(window), "m1"


def score_single(counter: Counter, row: dict[str, Any], prediction: Prediction) -> None:
    expected_role = row["role"]
    expected_categories = {ReportCategory(code) for code in row.get("categories", [])}
    is_problem = expected_role == "new_problem"
    counter.n += 1
    counter.role_ok += int(prediction.role == expected_role)
    if is_problem:
        counter.n_problem += 1
        predicted_problem = prediction.role == "new_problem" and bool(prediction.categories)
        counter.missed_problem += int(not predicted_problem)
        counter.cat_exact += int(predicted_problem and prediction.categories == expected_categories)
        counter.cat_any += int(
            predicted_problem and bool(prediction.categories & expected_categories)
        )
        counter.subtype_known += int(
            predicted_problem and any(code != "other.unspecified" for code in prediction.subtypes)
        )
        counter.gate_pass_problem += int(passes_recall_gate(row["text"]))
    else:
        counter.n_nonproblem += 1
        counter.false_problem += int(prediction.role == "new_problem")
    if row.get("emergency"):
        counter.n_emergency += 1
        counter.emergency_hit += int(prediction.emergency)
    else:
        counter.emergency_false += int(prediction.emergency)
    expected_entrance = row.get("entrance")
    if expected_entrance is not None:
        counter.n_entrance += 1
        counter.entrance_ok += int(prediction.entrance == expected_entrance)
    elif prediction.entrance is not None:
        counter.entrance_invented += 1
    if "location_scope" in row:
        counter.n_scope += 1
        counter.scope_ok += int(prediction.scope == row["location_scope"])


def counter_row(name: str, counter: Counter) -> dict[str, Any]:
    return {
        "slice": name,
        "n": counter.n,
        "role": ratio(counter.role_ok, counter.n),
        "category_exact": ratio(counter.cat_exact, counter.n_problem),
        "category_any": ratio(counter.cat_any, counter.n_problem),
        "subtype_known": ratio(counter.subtype_known, counter.n_problem),
        "missed_problems": {"k": counter.missed_problem, "n": counter.n_problem},
        "false_problems": {"k": counter.false_problem, "n": counter.n_nonproblem},
        "emergency": {"k": counter.emergency_hit, "n": counter.n_emergency,
                      "false_alarms": counter.emergency_false},
        "entrance": {"k": counter.entrance_ok, "n": counter.n_entrance,
                     "invented": counter.entrance_invented},
        "gate_recall": ratio(counter.gate_pass_problem, counter.n_problem),
        "location_scope": ratio(counter.scope_ok, counter.n_scope),
    }


async def evaluate_singles(
    analyzer: WindowAnalyzer, rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    by_slice: dict[str, Counter] = {}
    total = Counter()
    errors: list[dict[str, Any]] = []
    for row in rows:
        analysis, line_id = await analyze_single(analyzer, row["text"])
        prediction = predict(analysis, line_id)
        counter = by_slice.setdefault(row.get("slice", "-"), Counter())
        before = Counter(**counter.__dict__)
        score_single(counter, row, prediction)
        score_single(total, row, prediction)
        if _is_error(before, counter):
            errors.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "expected": {"role": row["role"], "categories": row.get("categories", []),
                                 "emergency": row.get("emergency", False)},
                    "got": {"role": prediction.role,
                            "categories": sorted(item.value for item in prediction.categories),
                            "subtypes": prediction.subtypes,
                            "emergency": prediction.emergency},
                }
            )
    return {
        "slices": [counter_row(name, counter) for name, counter in by_slice.items()],
        "total": counter_row("ИТОГО", total),
        "errors": errors,
    }


def _is_error(before: Counter, after: Counter) -> bool:
    return (
        after.role_ok == before.role_ok
        or after.missed_problem > before.missed_problem
        or after.false_problem > before.false_problem
        or (after.n_problem > before.n_problem and after.cat_exact == before.cat_exact)
        or after.emergency_false > before.emergency_false
        or (after.n_emergency > before.n_emergency and after.emergency_hit == before.emergency_hit)
    )


async def evaluate_scope(
    analyzer: WindowAnalyzer, rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    messages = [row for row in rows if row["kind"] == "message"]
    windows = [row for row in rows if row["kind"] == "window"]
    counter = Counter()
    subtype_ok = subtype_n = 0
    errors: list[dict[str, Any]] = []
    for row in messages:
        analysis, line_id = await analyze_single(analyzer, row["text"])
        prediction = predict(analysis, line_id)
        before = Counter(**counter.__dict__)
        score_single(counter, row, prediction)
        if row.get("subtype"):
            subtype_n += 1
            subtype_ok += int(row["subtype"] in prediction.subtypes)
        if _is_error(before, counter) or (
            row.get("subtype") and row["subtype"] not in prediction.subtypes
        ):
            errors.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "expected": {"role": row["role"], "subtype": row.get("subtype"),
                                 "location_scope": row.get("location_scope")},
                    "got": {"role": prediction.role, "subtypes": prediction.subtypes,
                            "location_scope": prediction.scope},
                }
            )
    contextual: list[dict[str, Any]] = []
    for row in windows:
        lines = tuple(
            _line(item["n"], item["text"], author=item["author"], minute=item["minute"])
            for item in row["lines"]
        )
        analysis = await analyzer.analyze(WindowInput(channel="group_passive", lines=lines))
        contextual.append(
            {
                "id": row["id"],
                "expected_semantic_danger": row["expected_semantic_danger"],
                "rules_found_danger": any(
                    not hit.negated for hit in analysis.danger_hits
                ),
                "signals": len(analysis.signals),
                "mode": analysis.mode,
            }
        )
    return {
        "messages": counter_row("scope_and_danger", counter),
        "subtype_exact": ratio(subtype_ok, subtype_n),
        "contextual_windows": contextual,
        "errors": errors,
    }


async def evaluate_stream(
    analyzer: WindowAnalyzer, rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    lines = [
        _line(row["n"], row["text"], author=row["author"], minute=row["minute"],
              line_id=row["id"], reply_to=row["reply_to"])
        for row in rows
    ]
    windows = build_windows(lines, channel="group_passive")
    verdicts: dict[str, str] = {}
    signal_lines: dict[str, str] = {}
    inbox_lines: set[str] = set()
    audit_lines: set[str] = set()
    signals_total = 0
    for window in windows:
        analysis = await analyzer.analyze(window)
        signals_total += len(analysis.signals)
        for verdict in analysis.lines:
            verdicts[verdict.line_id] = verdict.role
        for signal in analysis.signals:
            for line_id in signal.line_ids:
                signal_lines[line_id] = signal.ref
                (inbox_lines if signal.disposition == "inbox" else audit_lines).add(line_id)
    relevant = [row for row in rows if row["role"] in RELEVANT_ROLES]
    other = [row for row in rows if row["role"] not in RELEVANT_ROLES]
    captured = sum(1 for row in relevant if verdicts.get(row["id"], "chatter") in RELEVANT_ROLES)
    extra = sum(1 for row in other if verdicts.get(row["id"], "chatter") in RELEVANT_ROLES)
    incidents = {row["incident"] for row in rows if row["incident"]}
    found = {
        incident
        for incident in incidents
        if any(row["id"] in signal_lines for row in rows if row["incident"] == incident)
    }
    return {
        "windows": len(windows),
        "lines": len(rows),
        "signals": signals_total,
        "relevant_recall": ratio(captured, len(relevant)),
        "extra_lines": {"k": extra, "n": len(other)},
        "incident_recall": ratio(len(found), len(incidents)),
        "missing_incidents": sorted(incidents - found),
        "inbox_share": ratio(len(inbox_lines), len(rows)),
        "audit_pool_share": ratio(len(audit_lines), len(rows)),
        "roles": {row["id"]: {"expected": row["role"],
                              "got": verdicts.get(row["id"], "chatter")} for row in rows},
    }


async def evaluate_dedup(
    analyzer: WindowAnalyzer, rules_only: WindowAnalyzer, rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    incidents = [row for row in rows if row["kind"] == "incident"]
    queries = [row for row in rows if row["kind"] == "query"]
    open_items: list[OpenItem] = []
    for row in incidents:
        analysis, line_id = await analyze_single(rules_only, row["text"])
        prediction = predict(analysis, line_id)
        open_items.append(
            OpenItem(
                ref=row["id"],
                kind="incident",
                category=ReportCategory(row["category"]),
                subtype=prediction.subtypes[0] if prediction.subtypes else None,
                entrance=row["entrance"],
                title=row["text"][:200],
            )
        )
    correct_join = wrong_target = false_join = missed_join = correct_new = 0
    details: list[dict[str, Any]] = []
    for row in queries:
        window = WindowInput(
            channel="group_report",
            lines=(_line(1, row["text"]),),
            open_items=tuple(open_items),
        )
        analysis = await analyzer.analyze(window)
        refs = [signal.ref for signal in analysis.signals]
        joined = next((ref for ref in refs if not ref.startswith("new:")), None)
        expected = row["expected_incident"]
        if expected:
            if joined == expected:
                correct_join += 1
            elif joined is None:
                missed_join += 1
            else:
                wrong_target += 1
        else:
            if joined is None:
                correct_new += 1
            else:
                false_join += 1
        details.append({"id": row["id"], "expected": expected, "got": joined, "note": row["note"]})
    positives = sum(1 for row in queries if row["expected_incident"])
    return {
        "open_items": [
            {"ref": item.ref, "category": item.category.value, "subtype": item.subtype,
             "entrance": item.entrance}
            for item in open_items
        ],
        "correct_joins": ratio(correct_join, positives),
        "wrong_target": wrong_target,
        "missed_joins": missed_join,
        "false_joins": {"k": false_join, "n": len(queries) - positives},
        "correct_new": correct_new,
        "details": details,
    }


@dataclass
class DatasetCard:
    path: pathlib.Path
    records: int
    digest: str = field(default="")

    def as_dict(self) -> dict[str, Any]:
        return {"file": self.path.as_posix(), "records": self.records, "sha256": self.digest}


def dataset_card(path: pathlib.Path, rows: Iterable[dict[str, Any]]) -> DatasetCard:
    return DatasetCard(path=path, records=len(list(rows)), digest=sha256_of(path))
