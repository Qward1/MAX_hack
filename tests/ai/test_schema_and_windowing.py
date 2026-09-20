"""Схема ответа модели, таксономия и политика нарезки окон."""

from __future__ import annotations

import json
from typing import Any

import pytest

from domsignal.ai import build_json_schema
from domsignal.ai.model_output import SCHEMA_RESOURCE
from domsignal.ai.resources import load_yaml_resource, read_resource
from domsignal.ai.taxonomy import UNSPECIFIED, TaxonomyError, build_taxonomy, load_taxonomy
from domsignal.ai.windowing import WindowPolicy, build_windows, split_stream
from domsignal.core.incidents import ReportCategory
from tests.ai.helpers import line


def test_committed_schema_matches_generation() -> None:
    committed = json.loads(read_resource(SCHEMA_RESOURCE))
    assert committed == build_json_schema(), (
        "перегенерируйте ресурс: build_json_schema() расходится с коммитом"
    )


def _objects(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append((path, node))
        for key, value in node.items():
            found.extend(_objects(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_objects(value, f"{path}[{index}]"))
    return found


def test_schema_forbids_additional_properties_everywhere() -> None:
    schema = build_json_schema()
    for path, node in _objects(schema):
        assert node.get("additionalProperties") is False, path


def test_schema_carries_the_taxonomy_enum() -> None:
    schema = build_json_schema()
    subtype = schema["$defs"]["ModelSignal"]["properties"]["subtype"]
    assert subtype["enum"] == list(load_taxonomy().codes)
    assert UNSPECIFIED in subtype["enum"]


def test_taxonomy_is_valid() -> None:
    taxonomy = load_taxonomy()
    assert taxonomy.version == "v2"
    assert UNSPECIFIED in taxonomy.codes
    for subtype in taxonomy.subtypes:
        assert subtype.product_category in set(ReportCategory)
        assert subtype.dedupe_scope in ("object", "house")
        assert subtype.description
        assert subtype.code == subtype.code.strip().lower()


ALLOWED_SUBTYPE_KEYS = {
    "code",
    "product_category",
    "dedupe_scope",
    "label",
    "description",
    "patterns",
    "exclude",
}


def test_taxonomy_holds_no_routing_data() -> None:
    """У подтипа нет полей маршрута, организации, канала или срока."""
    document = load_yaml_resource("taxonomy.v2.yaml")
    for entry in document["subtypes"]:
        assert set(entry) <= ALLOWED_SUBTYPE_KEYS, entry["code"]


def test_taxonomy_requires_unspecified() -> None:
    with pytest.raises(TaxonomyError):
        build_taxonomy(
            {
                "version": "v2",
                "subtypes": [
                    {
                        "code": "elevator.stopped",
                        "product_category": "elevator",
                        "dedupe_scope": "object",
                        "label": "лифт",
                        "description": "…",
                        "patterns": [],
                    }
                ],
            }
        )


def test_taxonomy_rejects_unknown_category() -> None:
    with pytest.raises(TaxonomyError):
        build_taxonomy(
            {
                "version": "v2",
                "subtypes": [
                    {
                        "code": "x",
                        "product_category": "plumbing",
                        "dedupe_scope": "object",
                        "label": "x",
                        "description": "x",
                    }
                ],
            }
        )


def test_window_closes_on_silence() -> None:
    lines = [
        line(1, "первое", seconds=0),
        line(2, "второе", seconds=60),
        line(3, "третье", seconds=400),
    ]
    assert [len(group) for group in split_stream(lines)] == [2, 1]


def test_window_closes_on_line_count() -> None:
    lines = [line(index, f"реплика {index}", seconds=index) for index in range(1, 26)]
    assert [len(group) for group in split_stream(lines)] == [10, 10, 5]


def test_window_closes_on_age() -> None:
    lines = [line(index, f"реплика {index}", seconds=index * 100) for index in range(1, 6)]
    assert [len(group) for group in split_stream(lines)] == [4, 1]


def test_danger_closes_the_window_immediately() -> None:
    lines = [
        line(1, "всем привет", seconds=0),
        line(2, "в подъезде пахнет газом", seconds=10),
        line(3, "кто-нибудь звонил?", seconds=20),
    ]
    groups = split_stream(lines)
    assert [len(group) for group in groups] == [2, 1]
    assert groups[0][-1].text.endswith("газом")


def test_negated_danger_does_not_close_the_window() -> None:
    lines = [
        line(1, "всем привет", seconds=0),
        line(2, "газом не пахнет, показалось", seconds=10),
        line(3, "ну и хорошо", seconds=20),
    ]
    assert [len(group) for group in split_stream(lines)] == [3]


def test_context_lines_are_attached_read_only() -> None:
    lines = [line(index, f"реплика {index}", seconds=index * 200) for index in range(1, 8)]
    windows = build_windows(lines, policy=WindowPolicy(silence_seconds=120, context_lines=2))
    assert len(windows) == 7
    third = windows[2]
    assert [item.is_context for item in third.lines] == [True, True, False]
    assert third.lines[-1].line_id == "line-3"
