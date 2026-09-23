"""Общий лимит вызовов модели на срез: резерв до вызова и жёсткая остановка."""

from __future__ import annotations

import pathlib

import pytest

from evaluation.guard import SliceBudget, SliceBudgetExceeded


def test_calls_limit_stops_before_the_call(tmp_path: pathlib.Path) -> None:
    budget = SliceBudget(tmp_path / "ledger.json", max_calls=2, max_rub=100.0)
    budget.reserve()
    budget.commit("run", 0.5)
    budget.reserve()
    with pytest.raises(SliceBudgetExceeded):
        budget.reserve()
    budget.commit("run", None)
    assert budget.calls == 2
    assert budget.state["unknown_cost_calls"] == 1


def test_counter_survives_restarts_and_rub_limit_holds(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "ledger.json"
    first = SliceBudget(path, max_calls=10, max_rub=1.0)
    first.reserve()
    first.commit("a", 0.7)
    second = SliceBudget(path, max_calls=10, max_rub=1.0)
    assert second.calls == 1 and second.rub == pytest.approx(0.7)
    second.reserve()
    second.commit("b", 0.4)
    with pytest.raises(SliceBudgetExceeded):
        second.reserve()
    assert set(second.state["runs"]) == {"a", "b"}
