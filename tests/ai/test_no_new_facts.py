"""Guard `no_new_facts`: модель не добавляет фактов, которых нет в репликах."""

from __future__ import annotations

import pytest

from domsignal.ai import check_no_new_facts

SOURCES = [
    "Соседи, во 2 подъезде лифт опять встал",
    "у нас тоже",
    "да, не работает с утра",
]


def test_business_wording_from_the_same_lines_passes() -> None:
    result = check_no_new_facts("лифт во 2 подъезде не работает с утра", SOURCES)
    assert result.ok
    assert result.violations == ()


def test_word_number_matches_the_digit_in_sources() -> None:
    result = check_no_new_facts(
        "лифт во втором подъезде не работает", ["Лифт во 2 подъезде не работает"]
    )
    assert result.ok


@pytest.mark.parametrize(
    "candidate,kind",
    [
        ("лифт не работает, просим устранить до 25 сентября", "date_or_time"),
        ("лифт не работает, согласно ст. 161 ЖК РФ", "obligation"),
        ("лифт не работает, обслуживает УК «Уют»", "organization"),
        ("лифт в третьем подъезде не работает", "entrance_or_floor"),
        ("лифт не работает уже 14 дней", "number"),
        ("лифт обязаны починить в течение суток", "obligation"),
    ],
)
def test_added_facts_are_violations(candidate: str, kind: str) -> None:
    result = check_no_new_facts(candidate, SOURCES)
    assert not result.ok
    assert kind in {violation.kind for violation in result.violations}


def test_proper_name_absent_from_sources_is_a_violation() -> None:
    result = check_no_new_facts("Лифт во 2 подъезде проверял Иванов", SOURCES)
    assert not result.ok
    assert any(violation.kind == "proper_name" for violation in result.violations)


def test_empty_sources_reject_every_number() -> None:
    result = check_no_new_facts("лифт во 2 подъезде", [])
    assert not result.ok
