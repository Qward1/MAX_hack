"""Регрессионные полы на синтетике — не заявление о качестве.

Наборы и правила написаны пересекающимися авторами, поэтому эти числа ловят
ухудшение относительно зафиксированной базовой линии и ничего не говорят о
работе на реальных сообщениях жителей (см. `datasets/README.md`).
"""

from __future__ import annotations

import pytest

from domsignal.ai import WindowAnalyzer
from evaluation import metrics


@pytest.fixture(scope="module")
def analyzer() -> WindowAnalyzer:
    return WindowAnalyzer()


async def _singles(analyzer: WindowAnalyzer) -> dict[str, object]:
    rows = metrics.load_jsonl(metrics.DATASETS / "single_messages.v1.jsonl")
    return await metrics.evaluate_singles(analyzer, rows)


async def test_typical_slice_role_and_category(analyzer: WindowAnalyzer) -> None:
    report = await _singles(analyzer)
    typical = next(item for item in report["slices"] if item["slice"] == "typical")  # type: ignore[attr-defined]
    assert typical["role"]["value"] >= 0.95
    assert typical["category_exact"]["value"] >= 0.95


async def test_missed_and_false_problems(analyzer: WindowAnalyzer) -> None:
    report = await _singles(analyzer)
    total = report["total"]
    assert total["missed_problems"]["n"] == 66  # type: ignore[index]
    assert total["missed_problems"]["k"] <= 8  # type: ignore[index]
    assert total["false_problems"]["n"] == 32  # type: ignore[index]
    assert total["false_problems"]["k"] <= 2  # type: ignore[index]


async def test_emergency_slice_is_complete(analyzer: WindowAnalyzer) -> None:
    report = await _singles(analyzer)
    emergency = next(item for item in report["slices"] if item["slice"] == "emergency")  # type: ignore[attr-defined]
    assert emergency["emergency"]["k"] == emergency["emergency"]["n"] == 10


async def test_recall_gate_keeps_problems(analyzer: WindowAnalyzer) -> None:
    report = await _singles(analyzer)
    gate = report["total"]["gate_recall"]  # type: ignore[index]
    assert gate["k"] >= 64
    assert gate["n"] == 66


async def test_stream_variant_c_recall(analyzer: WindowAnalyzer) -> None:
    rows = metrics.load_jsonl(metrics.DATASETS / "chat_stream.v1.jsonl")
    report = await metrics.evaluate_stream(analyzer, rows)
    assert report["relevant_recall"]["value"] >= 0.70


async def test_scope_dataset_subtypes_and_territory(analyzer: WindowAnalyzer) -> None:
    rows = metrics.load_jsonl(metrics.DATASETS / "scope_and_danger.v1.jsonl")
    report = await metrics.evaluate_scope(analyzer, rows)
    assert report["subtype_exact"]["value"] >= 0.90
    assert report["messages"]["location_scope"]["value"] >= 0.90


async def test_v2_dataset_keeps_the_external_route_labelling(analyzer: WindowAnalyzer) -> None:
    """Пол набора v2 — текущий результат правил, а не заявление о качестве."""
    rows = metrics.load_jsonl(metrics.DATASETS / "single_messages.v2.jsonl")
    assert len(rows) == 98
    changed = [row for row in rows if row.get("changed_from_v1")]
    assert [row["id"] for row in changed] == ["o03"]
    assert changed[0]["role"] == "new_problem"
    assert changed[0]["location_scope"] == "municipal_territory"

    report = await metrics.evaluate_singles(analyzer, rows)
    total = report["total"]
    assert total["role"]["value"] >= 0.94  # type: ignore[index]
    assert total["missed_problems"]["k"] <= 1  # type: ignore[index]
    assert total["false_problems"]["k"] <= 0  # type: ignore[index]


async def test_v1_labelling_is_untouched() -> None:
    """Набор v1 не меняется ради сопоставимости с экспериментом E0."""
    rows = metrics.load_jsonl(metrics.DATASETS / "single_messages.v1.jsonl")
    row = next(item for item in rows if item["id"] == "o03")
    assert row["role"] == "out_of_scope"
    assert "location_scope" not in row
