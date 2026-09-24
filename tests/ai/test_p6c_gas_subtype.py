"""P6c §1: газ после разбора — «запах газа», а не «Другое».

Живой шаг 4 P6b: предварительный газовый сигнал (подтип-заглушка
`other.unspecified`) попал в `open_items` своего же окна; модель при
минимальных рассуждениях продолжила его и повторила подтип заглушки, а
примирение записало его в сигнал. Корень исправлен в продукте (заглушка не
уходит в модель), а ядро страхует детерминированно: опасность вида K при
подтипе `other.unspecified` даёт подтип из таксономии, когда соответствие
вида подтипу однозначно (сейчас — только gas → gas.smell).
"""

from __future__ import annotations

from typing import Any

import pytest

from domsignal.ai import WindowAnalysis, WindowAnalyzer, WindowInput
from domsignal.ai.contracts import OpenItem
from domsignal.ai.engine import subtype_from_danger
from domsignal.ai.providers.fake import FakeProvider
from domsignal.ai.taxonomy import TaxonomyError, build_taxonomy, load_taxonomy
from domsignal.core.incidents import ReportCategory
from tests.ai.helpers import model_response, model_signal, window

#: Синтетический текст той же формы, что реплика живого шага 4.
GAS_2 = "Пахнет газом во втором подъезде"

#: Так продукт P6b передавал свой же предварительный сигнал окна.
PRELIMINARY = OpenItem(
    ref="signal:preliminary",
    kind="signal",
    category=ReportCategory.OTHER,
    subtype="other.unspecified",
    title="газ",
    danger_kinds=("gas",),
)


def danger(kind: str, quote: str, msg: str = "m1") -> dict[str, Any]:
    return {"kind": kind, "evidence": [{"msg": msg, "quote": quote}], "contextual": False}


async def analyse(response: dict[str, Any], window_input: WindowInput) -> WindowAnalysis:
    return await WindowAnalyzer(FakeProvider("ok", response)).analyze(window_input)


async def test_live_step_4_gas_is_gas_smell_even_when_the_model_copies_the_placeholder() -> None:
    response = model_response(
        [
            model_signal(
                ref="open:1",
                subtype="other.unspecified",
                object="газ",
                danger=[danger("gas", "Пахнет газом")],
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["open:1"]},
    )
    analysis = await analyse(response, window(GAS_2, open_items=(PRELIMINARY,)))
    assert analysis.mode == "model"
    [signal] = analysis.signals
    assert signal.emergency.is_emergency and signal.emergency.kinds == ("gas",)
    assert signal.subtype == "gas.smell"
    assert signal.product_category == ReportCategory.OTHER
    assert "subtype_from_danger" in signal.flags
    assert signal.entrance is not None and signal.entrance.value == "2"
    events = [event for event in analysis.audit_events if event.kind == "subtype_from_danger"]
    assert events and "gas.smell" in events[0].details


async def test_the_model_subtype_wins_when_it_is_known() -> None:
    response = model_response(
        [model_signal(subtype="gas.smell", object="газ", danger=[danger("gas", "Пахнет газом")])],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    [signal] = (await analyse(response, window(GAS_2))).signals
    assert signal.subtype == "gas.smell"
    assert "subtype_from_danger" not in signal.flags


@pytest.mark.parametrize(
    "text,kind,quote",
    [
        ("В подъезде дым", "smoke_fire", "дым"),
        ("Соседка застряла, дверь заклинило", "person_trapped", "Соседка застряла"),
        ("Сверху хлещет вода", "flooding", "хлещет вода"),
        ("В щитке искрит", "electric", "искрит"),
        ("Трещина пошла по стене", "structural", "Трещина пошла по стене"),
    ],
)
async def test_other_danger_kinds_keep_other_unspecified(text: str, kind: str, quote: str) -> None:
    signal = model_signal(
        subtype="other.unspecified", object="опасность", danger=[danger(kind, quote)]
    )
    response = model_response(
        [signal],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    signals = (await analyse(response, window(text))).signals
    assert signals and all(signal.subtype == "other.unspecified" for signal in signals)
    assert all("subtype_from_danger" not in signal.flags for signal in signals)


async def test_gas_with_another_kind_is_still_unambiguous() -> None:
    text = "Пахнет газом и дымом тянет"
    response = model_response(
        [
            model_signal(
                subtype="other.unspecified",
                object="газ и дым",
                danger=[danger("gas", "Пахнет газом"), danger("smoke_fire", "дымом тянет")],
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    [signal] = (await analyse(response, window(text))).signals
    assert set(signal.emergency.kinds) == {"gas", "smoke_fire"}
    assert signal.subtype == "gas.smell"


async def test_no_danger_keeps_other_unspecified() -> None:
    response = model_response(
        [model_signal(subtype="other.unspecified", object="что-то")],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    [signal] = (await analyse(response, window("Во дворе что-то странное"))).signals
    assert signal.subtype == "other.unspecified"


async def test_rules_path_has_the_same_safety_net() -> None:
    """Страховка ядра общая: режим правил получает её в том же месте."""
    analysis = await WindowAnalyzer().analyze(window(GAS_2))
    assert analysis.mode == "rules"
    [signal] = analysis.signals
    assert signal.subtype == "gas.smell"
    placeholder = signal.model_copy(update={"subtype": "other.unspecified", "flags": ()})
    [fixed], events = subtype_from_danger((placeholder,), load_taxonomy())
    assert fixed.subtype == "gas.smell" and "subtype_from_danger" in fixed.flags
    assert [event.kind for event in events] == ["subtype_from_danger"]


# ---------------------------------------------------------------- таксономия


def test_only_gas_maps_to_a_subtype() -> None:
    taxonomy = load_taxonomy()
    assert taxonomy.subtype_for_danger(("gas",)) == "gas.smell"
    for kind in ("smoke_fire", "electric", "person_trapped", "flooding", "structural"):
        assert taxonomy.subtype_for_danger((kind,)) is None, kind
    assert taxonomy.subtype_for_danger(()) is None


def _entry(code: str, danger_kind: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "code": code,
        "product_category": "other",
        "dedupe_scope": "house",
        "label": code,
        "description": "…",
        "patterns": [],
    }
    if danger_kind is not None:
        entry["danger_kind"] = danger_kind
    return entry


def test_two_subtypes_of_one_kind_are_ambiguous() -> None:
    taxonomy = build_taxonomy(
        {
            "version": "t",
            "subtypes": [
                _entry("a.one", "flooding"),
                _entry("a.two", "flooding"),
                _entry("other.unspecified"),
            ],
        }
    )
    assert taxonomy.subtype_for_danger(("flooding",)) is None


def test_unknown_danger_kind_in_taxonomy_is_rejected() -> None:
    with pytest.raises(TaxonomyError):
        build_taxonomy(
            {"version": "t", "subtypes": [_entry("a.one", "lava"), _entry("other.unspecified")]}
        )
