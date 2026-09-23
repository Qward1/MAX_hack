"""Наборы P6: сборка D3 воспроизводима, D5 и эталон маршрутов проходят сторожа."""

from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import timedelta

import pytest

from domsignal.ai import WindowAnalyzer, WindowLine
from domsignal.ai.windowing import build_windows
from evaluation import d3_build
from evaluation.guard import load_allowed_jsonl
from evaluation.metrics import BASE_TIME


def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_d3_build_reproduces_committed_files() -> None:
    summary = d3_build.build(check_only=True)
    assert summary["dialogs"] >= 100
    lines = summary["dev"]["lines"] + summary["holdout"]["lines"]
    assert 1500 <= lines <= 2500
    routes = d3_build.load_routes()
    scenarios = d3_build.load_scenarios()
    dialogs = []
    for path in sorted(d3_build.SOURCE_DIR.glob("*.d3")):
        dialogs.extend(d3_build.parse_source(path.read_text(encoding="utf-8"), path.name))
    splits = d3_build.split_dialogs(dialogs, scenarios)
    for name, path in (("dev", d3_build.DEV_FILE), ("holdout", d3_build.HOLDOUT_FILE)):
        rows = [
            d3_build.to_row(dialog, routes, scenarios, name)
            for dialog in dialogs
            if splits[dialog.id] == name
        ]
        body = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in sorted(rows, key=lambda item: item["id"])
        )
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == _sha(path), name


def test_d3_split_keeps_every_dialog_in_one_part() -> None:
    dev = {row["id"] for row in load_allowed_jsonl(d3_build.DEV_FILE)}
    holdout = {row["id"] for row in load_allowed_jsonl(d3_build.HOLDOUT_FILE)}
    assert not dev & holdout
    share = len(dev) / (len(dev) + len(holdout))
    assert 0.55 <= share <= 0.65


def test_d3_source_rejects_unknown_role() -> None:
    text = "=== d999 s01 typical\n+0 A: текст | panic | -\n"
    dialogs = d3_build.parse_source(text, "inline")
    with pytest.raises(d3_build.D3Error):
        d3_build.validate(dialogs, d3_build.load_routes(), d3_build.load_scenarios())


def test_d5_and_route_reference_pass_the_data_guard() -> None:
    d5 = load_allowed_jsonl(pathlib.Path("datasets/synthetic/d5_danger.v1.jsonl"))
    groups = [row["group"] for row in d5]
    assert (groups.count("danger"), groups.count("trap"), groups.count("contextual")) == (
        30,
        30,
        10,
    )
    routes = load_allowed_jsonl(pathlib.Path("datasets/routing/route_reference.v1.jsonl"))
    assert routes and all(row["expected_route_type"] for row in routes)


async def test_rules_never_split_a_thread_on_d3_dev() -> None:
    """Инвариант режима правил из дефекта P7a — на диалогах D3 (только dev)."""
    analyzer = WindowAnalyzer()
    for row in load_allowed_jsonl(d3_build.DEV_FILE):
        lines = [
            WindowLine(
                line_id=f"{row['id']}-{item['n']}",
                author_ref=item["author"],
                text=item["text"],
                sent_at=BASE_TIME + timedelta(seconds=item["offset_s"]),
                reply_to=f"{row['id']}-{item['reply_to']}" if item["reply_to"] else None,
            )
            for item in row["lines"]
        ]
        for window in build_windows(lines, channel="group_passive"):
            analysis = await analyzer.analyze(window)
            pairs = [
                (signal.product_category, signal.entrance.value if signal.entrance else None)
                for signal in analysis.signals
                if not signal.emergency.is_emergency
            ]
            assert len(pairs) == len(set(pairs)), (row["id"], pairs)
