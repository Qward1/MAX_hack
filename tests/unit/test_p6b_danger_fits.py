"""P6b, живой шаг 6: продуктовая склейка по ключу держит инвариант ядра P6."""

from __future__ import annotations

from domsignal.ai import EmergencyDecision
from domsignal.services.signals import danger_fits

SMOKE = {"is_emergency": True, "kinds": ["smoke_fire"]}


def decision(*kinds: str) -> EmergencyDecision:
    return EmergencyDecision(is_emergency=bool(kinds), kinds=kinds)  # type: ignore[arg-type]


def test_a_new_danger_kind_does_not_fit_an_open_signal_without_it() -> None:
    assert not danger_fits(SMOKE, decision("person_trapped"))
    assert not danger_fits(SMOKE, decision("smoke_fire", "person_trapped"))


def test_the_same_kind_and_plain_signals_still_group() -> None:
    assert danger_fits(SMOKE, decision("smoke_fire"))
    assert danger_fits(SMOKE, decision())
    assert danger_fits(None, decision())


def test_a_refuted_signal_takes_no_new_danger() -> None:
    refuted = {"is_emergency": False, "kinds": ["smoke_fire"]}
    assert not danger_fits(refuted, decision("smoke_fire"))
    assert not danger_fits(None, decision("gas"))
