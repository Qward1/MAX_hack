"""Дефекты ядра, найденные живым прогоном P7a (синтетические тексты).

1. Место и доказательства — только из реплик окна, не из контекста.
2. Номер подъезда и этажа — цифрой, как бы он ни был написан.
3. Новая опасность другого вида не привязывается к открытому элементу.
4. Правила не дробят одну ветку на несколько слабых сигналов.
"""

from __future__ import annotations

from typing import Any

import pytest

from domsignal.ai import WindowAnalysis, WindowAnalyzer, WindowInput
from domsignal.ai.contracts import OpenItem
from domsignal.ai.providers.fake import FakeProvider
from domsignal.ai.rules.location import normalize_place_number
from domsignal.core.incidents import ReportCategory
from tests.ai.helpers import facets, line, model_response, model_signal, window


async def analyse(response: dict[str, Any], window_input: WindowInput) -> WindowAnalysis:
    return await WindowAnalyzer(FakeProvider("ok", response)).analyze(window_input)


def with_context(context: str, *texts: str, open_items: tuple[OpenItem, ...] = ()) -> WindowInput:
    """m1 — реплика прошлого разговора (`is_context`), m2… — реплики окна."""
    lines = (line(0, context, author="resident-0", is_context=True),) + tuple(
        line(index, text, author=f"resident-{index}", seconds=600 + index * 30)
        for index, text in enumerate(texts, start=1)
    )
    return WindowInput(channel="group_passive", lines=lines, open_items=open_items)


def dropped_details(analysis: WindowAnalysis) -> list[str]:
    return [event.details for event in analysis.audit_events if event.kind == "field_dropped"]


# ------------------------------------------------ 1. место только из окна

CONTEXT = "в 3 подъезде на 5 этаже со вчера лифт стоял, на улице"
OWN = "лифт опять не работает"


@pytest.mark.parametrize(
    ("field", "value", "quote"),
    [
        ("entrance", "3", "в 3 подъезде"),
        ("floor", "5", "на 5 этаже"),
        ("since", "со вчера", "со вчера"),
    ],
)
async def test_place_quoted_from_context_line_is_not_used(
    field: str, value: str, quote: str
) -> None:
    # P6b: место модели не используется вовсе, правила читают только реплики окна.
    response = model_response(
        [model_signal(**{field: {"value": value, "quote": quote, "msg": "m1"}})],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(CONTEXT, OWN))
    assert getattr(analysis.signals[0], field) is None


async def test_location_scope_quoted_from_context_line_is_dropped() -> None:
    response = model_response(
        [
            model_signal(
                location_scope={"value": "municipal_territory", "quote": "на улице", "msg": "m1"}
            )
        ],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(CONTEXT, "опять не работает"))
    assert analysis.signals[0].location_scope.value == "unknown"
    assert any("location_scope" in details for details in dropped_details(analysis))


async def test_place_quoted_from_own_line_is_kept() -> None:
    response = model_response(
        [model_signal(entrance={"value": "2", "quote": "во 2 подъезде", "msg": "m2"})],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(CONTEXT, "во 2 подъезде лифт стоит"))
    entrance = analysis.signals[0].entrance
    assert entrance is not None and entrance.value == "2"


async def test_danger_evidence_only_from_context_does_not_raise_emergency() -> None:
    response = model_response(
        [
            model_signal(
                danger=[
                    {
                        "kind": "person_trapped",
                        "evidence": [{"msg": "m1", "quote": "лифт стоял"}],
                        "contextual": True,
                    }
                ]
            )
        ],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(CONTEXT, OWN))
    assert not analysis.signals[0].emergency.is_emergency
    assert analysis.semantic_danger == ()
    assert any("danger" in details for details in dropped_details(analysis))


async def test_context_evidence_is_removed_but_own_evidence_keeps_danger() -> None:
    response = model_response(
        [
            model_signal(
                danger=[
                    {
                        "kind": "person_trapped",
                        "evidence": [
                            {"msg": "m1", "quote": "лифт стоял"},
                            {"msg": "m2", "quote": "внутри кто-то стучит"},
                        ],
                        "contextual": True,
                    }
                ]
            )
        ],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(CONTEXT, "внутри кто-то стучит"))
    assert analysis.signals[0].emergency.is_emergency
    evidence = analysis.semantic_danger[0].evidence
    assert [item.line_id for item in evidence] == ["line-1"]


async def test_refutation_quoted_from_context_cannot_downgrade_rules_danger() -> None:
    context = "это было в прошлом году"
    response = model_response(
        [
            model_signal(
                subtype="gas.smell",
                danger_refutation={"reason": "past", "quote": "в прошлом году", "msg": "m1"},
            )
        ],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(context, "в подъезде пахнет газом"))
    emergency = analysis.signals[0].emergency
    assert emergency.is_emergency and not emergency.downgraded
    assert "refutation_rejected" in {event.kind for event in analysis.audit_events}


async def test_summary_cannot_borrow_facts_from_context_line() -> None:
    response = model_response(
        [
            model_signal(
                summary={"text": "Лифт в 3 подъезде не работает.", "sources": ["m1", "m2"]}
            )
        ],
        roles={"m2": "new_problem"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(response, with_context(CONTEXT, OWN))
    assert analysis.signals[0].summary is None
    assert "no_new_facts_violation" in {event.kind for event in analysis.audit_events}


# -------------------------------------------- 2. номер подъезда и этажа


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3", "3"),
        ("03", "3"),
        ("3-м", "3"),
        ("3м", "3"),
        ("3й", "3"),
        ("3-ий", "3"),
        ("№3", "3"),
        ("№ 3", "3"),
        ("подъезд 3", "3"),
        ("третьем", "3"),
        ("третий", "3"),
        ("третьего", "3"),
        ("в третьем подъезде", "3"),
        ("Третьем", "3"),
        ("три", "3"),
        ("трёх", "3"),
        ("первом", "1"),
        ("одном", "1"),
        ("второй", "2"),
        ("двух", "2"),
        ("четвёртом", "4"),
        ("четвертом", "4"),
        ("четырьмя", "4"),
        ("пятый", "5"),
        ("пяти", "5"),
        ("шестого", "6"),
        ("седьмом", "7"),
        ("семи", "7"),
        ("восьмом", "8"),
        ("восьми", "8"),
        ("девятом", "9"),
        ("десятом", "10"),
        ("одиннадцатом", "11"),
        ("двенадцатый", "12"),
        ("тринадцати", "13"),
        ("четырнадцатом", "14"),
        ("пятнадцатом", "15"),
        ("шестнадцатом", "16"),
        ("семнадцатом", "17"),
        ("восемнадцатом", "18"),
        ("девятнадцатом", "19"),
        ("двадцатом", "20"),
        ("двадцати", "20"),
    ],
)
def test_place_number_is_normalized_to_digits(raw: str, expected: str) -> None:
    assert normalize_place_number(raw) == expected


@pytest.mark.parametrize("raw", ["пятно", "крайний", "последний", "у лифта"])
def test_non_number_values_are_left_as_written(raw: str) -> None:
    assert normalize_place_number(raw) == raw


def test_floor_range_keeps_both_numbers() -> None:
    assert normalize_place_number("между третьим и четвёртым") == "между 3 и 4"
    assert normalize_place_number("между 3 и 4") == "между 3 и 4"


async def test_entrance_word_becomes_digit_and_the_model_floor_is_not_used() -> None:
    text = "в третьем подъезде лифт стоит"
    response = model_response(
        [
            model_signal(
                entrance={"value": "третьем", "quote": "в третьем подъезде", "msg": "m1"},
                floor={"value": "пятом", "quote": "лифт", "msg": "m1"},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(response, window(text))
    signal = analysis.signals[0]
    assert signal.entrance is not None
    assert signal.entrance.value == "3"
    assert signal.entrance.quote in text and "третьем" in signal.entrance.quote
    # Этаж «пятом» с цитатой «лифт» модель выдумала; правила этажа не видят.
    assert signal.floor is None


async def test_rules_entrance_word_becomes_digit() -> None:
    analysis = await WindowAnalyzer().analyze(window("в четырнадцатом подъезде лифт стоит"))
    entrance = analysis.signals[0].entrance
    assert entrance is not None and entrance.value == "14"


# ------------------------- 3. новая опасность и открытый элемент другого вида

GAS_ITEM = OpenItem(
    ref="signal:gas",
    kind="signal",
    category=ReportCategory.OTHER,
    subtype="gas.smell",
    title="запах газа",
    danger_kinds=("gas",),
)
ELEVATOR_ITEM = OpenItem(
    ref="signal:lift",
    kind="signal",
    category=ReportCategory.ELEVATOR,
    subtype="elevator.stopped",
    entrance="2",
    title="лифт",
)


def trapped_signal(ref: str) -> dict[str, Any]:
    return model_signal(
        ref=ref,
        subtype="elevator.doors",
        danger=[
            {
                "kind": "person_trapped",
                "evidence": [
                    {"msg": "m2", "quote": "женщина стучит"},
                    {"msg": "m3", "quote": "двери вообще не открываются"},
                ],
                "contextual": True,
            }
        ],
    )


TRAPPED_WINDOW_TEXTS = (
    "там кто-нибудь внутри?",
    "да, женщина стучит",
    "двери вообще не открываются",
)


async def test_new_danger_kind_does_not_join_open_item_of_another_kind() -> None:
    response = model_response(
        [trapped_signal("open:1")],
        roles={"m1": "discussion", "m2": "more_info", "m3": "new_problem"},
        refs={"m2": ["open:1"], "m3": ["open:1"]},
    )
    analysis = await analyse(response, window(*TRAPPED_WINDOW_TEXTS, open_items=(GAS_ITEM,)))
    signal = analysis.signals[0]
    assert signal.ref.startswith("new:")
    assert signal.emergency.kinds == ("person_trapped",)
    refs = {verdict.line_id: verdict.signal_refs for verdict in analysis.lines}
    assert refs["line-3"] == (signal.ref,)
    assert "signal:gas" not in {ref for item in refs.values() for ref in item}


async def test_danger_signal_does_not_join_open_item_without_danger() -> None:
    response = model_response(
        [trapped_signal("open:1")],
        roles={"m1": "discussion", "m2": "more_info", "m3": "new_problem"},
        refs={"m3": ["open:1"]},
    )
    analysis = await analyse(response, window(*TRAPPED_WINDOW_TEXTS, open_items=(ELEVATOR_ITEM,)))
    assert analysis.signals[0].ref.startswith("new:")


async def test_same_danger_kind_still_joins_open_item() -> None:
    response = model_response(
        [
            model_signal(
                ref="open:1",
                subtype="gas.smell",
                danger=[
                    {
                        "kind": "gas",
                        "evidence": [{"msg": "m1", "quote": "газом пахнет"}],
                        "contextual": False,
                    }
                ],
            )
        ],
        roles={"m1": "me_too"},
        refs={"m1": ["open:1"]},
    )
    analysis = await analyse(response, window("и у нас газом пахнет", open_items=(GAS_ITEM,)))
    assert analysis.signals[0].ref == "signal:gas"


async def test_signal_without_danger_joins_open_item_as_before() -> None:
    response = model_response(
        [model_signal(ref="open:1", facets=facets())],
        roles={"m1": "me_too"},
        refs={"m1": ["open:1"]},
    )
    analysis = await analyse(
        response, window("во 2 подъезде лифт так и стоит", open_items=(ELEVATOR_ITEM,))
    )
    assert analysis.signals[0].ref == "signal:lift"


async def test_rules_danger_line_does_not_join_open_item_without_that_danger() -> None:
    analysis = await WindowAnalyzer().analyze(
        window("во 2 подъезде в лифте застрял ребенок", open_items=(ELEVATOR_ITEM,))
    )
    critical = [signal for signal in analysis.signals if signal.emergency.is_emergency]
    assert critical and all(signal.ref.startswith("new:") for signal in critical)


def test_open_item_danger_kinds_are_optional() -> None:
    item = OpenItem(ref="x", kind="signal", category=ReportCategory.OTHER, title="t")
    assert item.danger_kinds == ()


# ------------------------------------------- 4. правила не дробят ветку


def _non_danger_pairs(analysis: WindowAnalysis) -> list[tuple[str, str | None]]:
    return [
        (signal.product_category.value, signal.entrance.value if signal.entrance else None)
        for signal in analysis.signals
        if not signal.emergency.is_emergency
    ]


@pytest.mark.parametrize(
    "texts",
    [
        ("фонарь у подъезда не горит", "освещения во дворе вообще нет", "темно, страшно ходить"),
        ("Домофон в 1 подъезде сломался", "дверь не открывается с ключа", "у меня тоже"),
        ("Лифт во 2 подъезде не работает", "кнопка вызова не горит", "да, с утра стоит"),
    ],
)
async def test_rules_keep_one_signal_per_category_and_entrance(texts: tuple[str, ...]) -> None:
    analysis = await WindowAnalyzer().analyze(window(*texts))
    assert len(analysis.signals) == 1
    signal = analysis.signals[0]
    assert set(signal.line_ids) == {f"line-{index}" for index in range(1, len(texts) + 1)}
    referenced = {ref for verdict in analysis.lines for ref in verdict.signal_refs}
    assert referenced == {signal.ref}


async def test_rules_keep_different_entrances_apart() -> None:
    analysis = await WindowAnalyzer().analyze(
        window("в 1 подъезде лифт стоит", "а во 2 подъезде лифт тоже не работает")
    )
    assert sorted(pair[1] or "" for pair in _non_danger_pairs(analysis)) == ["1", "2"]


async def test_rules_merge_never_hides_a_danger_line() -> None:
    analysis = await WindowAnalyzer().analyze(
        window("свет в подъезде не горит", "в щитке искрит и воняет гарью", "темно совсем")
    )
    critical = [signal for signal in analysis.signals if signal.emergency.is_emergency]
    assert critical and any("line-2" in signal.line_ids for signal in critical)
    assert len(_non_danger_pairs(analysis)) <= 1


async def test_rules_never_split_a_thread_on_the_e0c_stream() -> None:
    from domsignal.ai.windowing import build_windows
    from evaluation import metrics

    rows = metrics.load_jsonl(metrics.DATASETS / "chat_stream.v1.jsonl")
    lines = [
        metrics._line(row["n"], row["text"], author=row["author"], minute=row["minute"],
                      line_id=row["id"], reply_to=row["reply_to"])
        for row in rows
    ]
    analyzer = WindowAnalyzer()
    for window_input in build_windows(lines, channel="group_passive"):
        pairs = _non_danger_pairs(await analyzer.analyze(window_input))
        assert len(pairs) == len(set(pairs)), pairs


# ------------------- 5. «свет горит» — не пожар (найдено на dev D3, P6)


@pytest.mark.parametrize(
    "text",
    [
        "в лифте свет горит, а кнопки не реагируют",
        "лампочка горит, но лифт стоит",
        "фонарь горит только один",
        "индикатор на кнопке горит",
        "горит свет на пятом, а на шестом темно",
        "у подъезда лампы горят весь день",
    ],
)
def test_lights_that_are_on_are_not_a_fire(text: str) -> None:
    from domsignal.ai import screen_message_for_danger

    assert not [hit for hit in screen_message_for_danger(text) if hit.kind == "smoke_fire"]


@pytest.mark.parametrize(
    "text",
    [
        "проводка горит!",
        "в подвале горит",
        "в щитке горит проводка, свет мигает",
        "горит мусоропровод, свет на площадке погас",
        "из окна валит дым",
    ],
)
def test_real_fire_is_still_a_fire(text: str) -> None:
    from domsignal.ai import screen_message_for_danger

    assert [hit for hit in screen_message_for_danger(text) if hit.kind == "smoke_fire"]


# ---------- 6. место, которое модель не назвала, — из правил по репликам сигнала

PLACE_TEXT = "во втором подъезде кнопка вызова лифта на первом этаже не работает"


async def test_missing_model_place_is_taken_from_rules_on_signal_lines() -> None:
    response = model_response(
        [model_signal(subtype="elevator.button")],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    signal = (await analyse(response, window(PLACE_TEXT))).signals[0]
    assert signal.entrance is not None and signal.entrance.value == "2"
    assert signal.entrance.quote in PLACE_TEXT
    assert signal.floor is not None and signal.floor.value == "1"
    assert "place_from_rules" in signal.flags


async def test_invented_model_place_is_replaced_by_rules() -> None:
    response = model_response(
        [
            model_signal(
                subtype="elevator.button",
                entrance={"value": "7", "quote": "во 2-м подъезде", "msg": "m1"},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(response, window(PLACE_TEXT))
    signal = analysis.signals[0]
    assert signal.entrance is not None and signal.entrance.value == "2"
    assert signal.entrance.quote in PLACE_TEXT


async def test_even_a_valid_model_place_comes_from_rules() -> None:
    """P6b: подъезд, этаж и «с какого времени» — только из правил."""
    response = model_response(
        [
            model_signal(
                subtype="elevator.button",
                entrance={"value": "2", "quote": "во втором подъезде", "msg": "m1"},
                floor={"value": "1", "quote": "на первом этаже", "msg": "m1"},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    signal = (await analyse(response, window(PLACE_TEXT))).signals[0]
    assert signal.entrance is not None and signal.entrance.value == "2"
    assert signal.floor is not None and signal.floor.value == "1"
    assert "place_from_rules" in signal.flags


async def test_scope_comes_from_rules_when_they_quote_it() -> None:
    text = "у остановки фонарь не горит"
    response = model_response(
        [
            model_signal(
                subtype="street_lighting.failure",
                location_scope={"value": "house_territory", "quote": "фонарь", "msg": "m1"},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    scope = (await analyse(response, window(text))).signals[0].location_scope
    assert scope.value == "municipal_territory" and scope.quote and scope.quote in text


async def test_model_scope_is_used_when_rules_do_not_know_it() -> None:
    text = "фонарь опять не горит"
    response = model_response(
        [
            model_signal(
                subtype="street_lighting.failure",
                location_scope={"value": "house_territory", "quote": "фонарь", "msg": "m1"},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    scope = (await analyse(response, window(text))).signals[0].location_scope
    assert scope.value == "house_territory" and scope.quote == "фонарь"


async def test_rules_place_never_comes_from_context_or_foreign_lines() -> None:
    response = model_response(
        [model_signal(), model_signal(ref="new:2", subtype="water.leak")],
        roles={"m2": "new_problem", "m3": "new_problem"},
        refs={"m2": ["new:1"], "m3": ["new:2"]},
    )
    analysis = await analyse(
        response, with_context(CONTEXT, "лифт опять не работает", "в 4 подъезде течёт с потолка")
    )
    lift, leak = analysis.signals
    assert lift.entrance is None
    assert leak.entrance is not None and leak.entrance.value == "4"
