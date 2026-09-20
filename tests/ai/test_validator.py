"""Семантическая проверка ответа модели против окна."""

from __future__ import annotations

from domsignal.ai import WindowAnalyzer
from domsignal.ai.contracts import OpenItem
from domsignal.ai.providers.fake import FakeProvider
from domsignal.core.incidents import ReportCategory
from tests.ai.helpers import facets, model_response, model_signal, single, window

WINDOW = window("Лифт во 2 подъезде не работает с утра", "у нас тоже")
OPEN_ITEMS = tuple(
    OpenItem(
        ref=f"incident-{index}",
        kind="incident",
        category=ReportCategory.ELEVATOR,
        subtype="elevator.stopped",
        entrance=str(index),
        title=f"Лифт в {index} подъезде",
    )
    for index in (1, 2, 3)
)


async def analyse(response: dict[str, object], window_input=WINDOW):
    return await WindowAnalyzer(FakeProvider("ok", response)).analyze(window_input)


async def test_quote_from_another_line_drops_the_field() -> None:
    response = model_response(
        [
            model_signal(
                entrance={"value": "2", "quote": "во 2 подъезде", "msg": "m2"},
            )
        ],
        roles={"m1": "new_problem", "m2": "me_too"},
        refs={"m1": ["new:1"], "m2": ["new:1"]},
    )
    analysis = await analyse(response)
    assert analysis.signals[0].entrance is None
    assert analysis.dropped_fields >= 1
    assert "field_dropped" in {event.kind for event in analysis.audit_events}


async def test_unknown_open_item_reference_becomes_a_new_signal() -> None:
    response = model_response(
        [model_signal(ref="open:7")],
        roles={"m1": "new_problem"},
        refs={"m1": ["open:7"]},
    )
    analysis = await analyse(
        response, window("Лифт во 2 подъезде не работает", open_items=OPEN_ITEMS)
    )
    assert analysis.signals[0].ref.startswith("new:")
    assert "field_dropped" in {event.kind for event in analysis.audit_events}


async def test_known_open_item_reference_is_mapped_back() -> None:
    response = model_response(
        [model_signal(ref="open:2")],
        roles={"m1": "me_too"},
        refs={"m1": ["open:2"]},
    )
    analysis = await analyse(
        response, window("Лифт во 2 подъезде не работает", open_items=OPEN_ITEMS)
    )
    assert analysis.signals[0].ref == "incident-2"


async def test_unknown_subtype_falls_back_to_unspecified() -> None:
    response = model_response(
        [model_signal(subtype="elevator.teleport")],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(response)
    assert analysis.signals[0].subtype == "other.unspecified"
    assert analysis.signals[0].product_category is ReportCategory.OTHER


async def test_no_without_a_quote_becomes_unclear() -> None:
    response = model_response(
        [model_signal(facets=facets(current="no", local="yes", observed="yes"))],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(response)
    assert analysis.signals[0].facets.current.value == "unclear"
    assert analysis.signals[0].strength != "filtered"


async def test_location_scope_without_a_quote_becomes_unknown() -> None:
    response = model_response(
        [model_signal(location_scope={"value": "municipal_territory", "quote": None,
                                      "msg": None})],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(response)
    assert analysis.signals[0].location_scope.value == "unknown"


async def test_unknown_role_falls_back_to_the_rules_role() -> None:
    response = {
        "messages": [{"id": "m1", "role": "sarcasm", "signals": []}],
        "signals": [],
    }
    analysis = await analyse(response, single("Лифт во 2 подъезде не работает"))
    assert analysis.lines[0].role == "new_problem"


async def test_missing_line_takes_the_rules_role_with_an_audit_event() -> None:
    response = model_response([], roles={"m1": "new_problem"})
    analysis = await analyse(response)
    assert "model_missing_line" in {event.kind for event in analysis.audit_events}
    assert [verdict.line_id for verdict in analysis.lines] == ["line-1", "line-2"]


async def test_clean_description_with_invented_facts_is_dropped() -> None:
    response = model_response(
        [
            model_signal(
                clean_description={
                    "text": "Лифт в 3 подъезде не работает, согласно ст. 161 ЖК РФ",
                    "sources": ["m1"],
                },
                summary={"text": "Лифт во 2 подъезде не работает с утра", "sources": ["m1"]},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(response)
    signal = analysis.signals[0]
    assert signal.clean_description is None
    assert signal.summary is not None
    assert "no_new_facts_violation" in {event.kind for event in analysis.audit_events}


async def test_rules_mode_never_fills_model_texts() -> None:
    analysis = await WindowAnalyzer().analyze(WINDOW)
    assert all(signal.clean_description is None for signal in analysis.signals)
    assert all(signal.summary is None for signal in analysis.signals)
