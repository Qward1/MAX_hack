"""Сторож данных: что читают скрипты оценки и что уходит во внешний API.

Реальные выгрузки домовых чатов лежат в `data/` основного checkout. Скрипт,
которому дали такой путь или строку без пометки синтетики, обязан
остановиться, а не «на всякий случай» продолжить.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from evaluation import run_eval, select_models
from evaluation.guard import (
    DataGuardError,
    ensure_allowed_path,
    ensure_allowed_rows,
    ensure_request_is_synthetic,
    load_allowed_jsonl,
    row_is_allowed,
)
from evaluation.metrics import DATASETS, load_jsonl

SYNTHETIC = {"id": "x1", "text": "лифт стоит", "synthetic": True}
DERIVED = {
    "id": "x2",
    "text": "лифт стоит",
    "origin": "real_derived_anonymized",
    "reviewed_by": "владелец",
    "reviewed_at": "2026-09-20",
}


def write_jsonl(path: pathlib.Path, rows: list[dict[str, Any]]) -> pathlib.Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------- пути


@pytest.mark.parametrize(
    "path",
    ["data/chat_export.jsonl", "data/telegram/messages.jsonl", "../data/whatsapp.jsonl"],
)
def test_paths_into_the_real_exports_are_refused(path: str) -> None:
    with pytest.raises(DataGuardError, match="реальных выгрузок"):
        ensure_allowed_path(path)


def test_paths_outside_the_datasets_tree_are_refused() -> None:
    with pytest.raises(DataGuardError, match="читается только из"):
        ensure_allowed_path("evaluation/metrics.py")


def test_a_narrower_root_cannot_reopen_the_real_exports(tmp_path: pathlib.Path) -> None:
    forbidden = tmp_path / "data"
    forbidden.mkdir()
    with pytest.raises(DataGuardError):
        ensure_allowed_path(forbidden / "rows.jsonl", root=forbidden)


def test_the_committed_datasets_are_allowed() -> None:
    for name in ("single_messages.v1.jsonl", "scope_and_danger.v1.jsonl"):
        assert ensure_allowed_path(DATASETS / name).name == name
    assert len(load_jsonl(DATASETS / "single_messages.v1.jsonl")) == 98


# ------------------------------------------------------------------ строки


def test_only_synthetic_or_verified_derived_rows_are_allowed() -> None:
    assert row_is_allowed(SYNTHETIC)
    assert row_is_allowed(DERIVED)
    assert not row_is_allowed({"id": "x3", "text": "лифт стоит"})
    assert not row_is_allowed({"id": "x4", "text": "лифт", "synthetic": "yes"})
    assert not row_is_allowed({**DERIVED, "reviewed_by": ""})
    assert not row_is_allowed({**DERIVED, "reviewed_at": None})


def test_rows_without_the_mark_stop_the_run(tmp_path: pathlib.Path) -> None:
    path = write_jsonl(tmp_path / "mixed.jsonl", [SYNTHETIC, {"id": "x9", "text": "нет пометки"}])
    with pytest.raises(DataGuardError, match="x9"):
        load_allowed_jsonl(path, root=tmp_path)


def test_a_clean_file_loads(tmp_path: pathlib.Path) -> None:
    path = write_jsonl(tmp_path / "clean.jsonl", [SYNTHETIC, DERIVED])
    assert len(load_allowed_jsonl(path, root=tmp_path)) == 2


def test_empty_row_list_is_allowed() -> None:
    ensure_allowed_rows([])


def test_texts_outside_the_allowed_set_never_reach_the_model() -> None:
    ensure_request_is_synthetic(["лифт стоит"], ["лифт стоит", "у нас тоже"])
    with pytest.raises(DataGuardError, match="не из синтетического набора"):
        ensure_request_is_synthetic(["реальная реплика жителя"], ["лифт стоит"])


# --------------------------------------------------------------- скрипты


@pytest.mark.parametrize("loader", [run_eval.load_dataset, select_models.load_dataset])
def test_both_evaluation_scripts_use_the_guard(loader: Any) -> None:
    with pytest.raises(DataGuardError):
        loader(pathlib.Path("data/chat_export.jsonl"))


def test_model_selection_refuses_windows_built_from_unknown_texts() -> None:
    with pytest.raises(DataGuardError):
        select_models.guard_windows(
            [select_models.EvalWindow(id="w1", texts=("реальная реплика",))],
            allowed_texts={"лифт стоит"},
        )
