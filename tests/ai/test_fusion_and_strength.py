"""Emergency Fusion, сила сигнала и выборочный аудит."""

from __future__ import annotations

import pytest

from domsignal.ai import WindowAnalyzer, audit_sample, decide_strength
from domsignal.ai.contracts import EmergencyDecision, Facet, Facets
from domsignal.ai.engine import apply_audit_sample, input_sha256
from domsignal.ai.providers.fake import FakeProvider
from tests.ai.helpers import facets, model_response, model_signal, single, window

TRAPPED = window(
    "там кто-нибудь внутри?",
    "да, женщина стучит",
    "двери вообще не открываются",
)
GAS = single("В подъезде сильно пахнет газом!", channel="group_passive")


def semantic_danger(kind: str = "person_trapped", **evidence: str) -> dict[str, object]:
    return {
        "kind": kind,
        "evidence": [{"msg": msg, "quote": quote} for msg, quote in evidence.items()],
        "contextual": True,
    }


async def analyse(window_input, response: dict[str, object]):
    return await WindowAnalyzer(FakeProvider("ok", response)).analyze(window_input)


async def test_contextual_danger_without_rule_hits_is_critical() -> None:
    response = model_response(
        [
            model_signal(
                subtype="elevator.doors",
                danger=[semantic_danger(m2="женщина стучит", m3="двери вообще не открываются")],
            )
        ],
        roles={"m1": "more_info", "m2": "more_info", "m3": "new_problem"},
        refs={"m1": ["new:1"], "m2": ["new:1"], "m3": ["new:1"]},
    )
    analysis = await analyse(TRAPPED, response)
    signal = analysis.signals[0]
    assert signal.strength == "critical"
    assert signal.emergency.sources == ("semantic",)
    assert signal.emergency.kinds == ("person_trapped",)
    assert not signal.emergency.memo_allowed
    assert not signal.emergency.evidence_unverified
    assert not analysis.danger_hits


async def test_rules_danger_downgraded_by_a_valid_refutation() -> None:
    response = model_response(
        [
            model_signal(
                subtype="gas.smell",
                facets=facets(current="unclear", local="unclear", observed="unclear"),
                danger_refutation={
                    "reason": "not_literal",
                    "quote": "пахнет газом",
                    "msg": "m1",
                },
            )
        ],
        roles={"m1": "discussion"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(GAS, response)
    signal = analysis.signals[0]
    assert signal.emergency.downgraded
    assert signal.emergency.downgrade_reason == "not_literal"
    assert not signal.emergency.is_emergency
    assert signal.strength == "weak"
    assert [event.kind for event in analysis.audit_events] == ["emergency_downgraded"]


async def test_refutation_without_a_valid_quote_is_rejected() -> None:
    response = model_response(
        [
            model_signal(
                subtype="gas.smell",
                danger_refutation={"reason": "past", "quote": "это было вчера", "msg": "m1"},
            )
        ],
        roles={"m1": "new_problem"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(GAS, response)
    signal = analysis.signals[0]
    assert signal.strength == "critical"
    assert not signal.emergency.downgraded
    assert "refutation_rejected" in {event.kind for event in analysis.audit_events}


async def test_semantic_danger_with_an_invalid_quote_keeps_critical() -> None:
    response = model_response(
        [
            model_signal(
                subtype="elevator.doors",
                danger=[semantic_danger(m2="кричит из кабины")],
            )
        ],
        roles={"m1": "chatter", "m2": "new_problem", "m3": "more_info"},
        refs={"m2": ["new:1"]},
    )
    analysis = await analyse(TRAPPED, response)
    signal = analysis.signals[0]
    assert signal.strength == "critical"
    assert signal.emergency.evidence_unverified
    assert "evidence_unverified" in {event.kind for event in analysis.audit_events}
    assert analysis.semantic_danger[0].evidence[0].quote_valid is False


async def test_model_silence_does_not_cancel_rule_danger() -> None:
    response = model_response(
        [model_signal(subtype="other.unspecified")],
        roles={"m1": "chatter"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(GAS, response)
    signal = analysis.signals[0]
    assert signal.strength == "critical"
    assert signal.emergency.sources == ("rules",)
    assert signal.emergency.memo_allowed


async def test_model_without_signals_keeps_the_rules_signal() -> None:
    analysis = await WindowAnalyzer(FakeProvider("ok")).analyze(GAS)
    assert analysis.mode == "model"
    assert analysis.signals and analysis.signals[0].strength == "critical"


async def test_memo_is_not_allowed_for_displaced_rule_hits() -> None:
    analysis = await WindowAnalyzer().analyze(
        single("в соседнем доме газом пахнет, страшно", channel="group_passive")
    )
    assert analysis.danger_hits and analysis.danger_hits[0].displaced
    assert all(not signal.emergency.memo_allowed for signal in analysis.signals)


def facet(value: str, quote: str | None = None) -> Facet:
    return Facet(value=value, quote=quote, line_id="line-1" if quote else None)


@pytest.mark.parametrize(
    "emergency,current,local,observed,strength,reason",
    [
        (True, "unclear", "unclear", "unclear", "critical", "emergency"),
        (False, "yes", "no", "yes", "filtered", "facet_no_local"),
        (False, "yes", "yes", "yes", "strong", "all_facets_yes"),
        (False, "unclear", "yes", "yes", "medium", "observed_yes"),
        (False, "yes", "yes", "unclear", "weak", "facets_unclear"),
    ],
)
def test_strength_rows(
    emergency: bool, current: str, local: str, observed: str, strength: str, reason: str
) -> None:
    decision = EmergencyDecision(is_emergency=emergency)
    quote = "цитата"
    value = decide_strength(
        decision,
        Facets(
            current=facet(current, quote),
            local=facet(local, quote),
            observed=facet(observed, quote),
        ),
    )
    assert value == (strength, reason)


def test_no_without_a_quote_is_treated_as_unclear() -> None:
    strength, _reason = decide_strength(
        EmergencyDecision(is_emergency=False),
        Facets(current=facet("no"), local=facet("yes", "q"), observed=facet("yes", "q")),
    )
    assert strength == "medium"


async def test_filtered_signal_goes_to_the_audit_pool() -> None:
    response = model_response(
        [
            model_signal(
                subtype="elevator.stopped",
                facets=facets(
                    current="no", local="yes", observed="yes", quote="лифт опять встал", msg="m1"
                ),
            )
        ],
        roles={"m1": "discussion"},
        refs={"m1": ["new:1"]},
    )
    analysis = await analyse(single("лифт опять встал", channel="group_passive"), response)
    signal = analysis.signals[0]
    assert signal.strength == "filtered"
    assert signal.disposition == "audit_pool"


def test_audit_sample_is_deterministic_and_close_to_the_rate() -> None:
    digests = [f"window-{index}" for index in range(1000)]
    first = [audit_sample(digest, 10) for digest in digests]
    second = [audit_sample(digest, 10) for digest in digests]
    assert first == second
    share = sum(first) / len(first)
    assert 0.06 <= share <= 0.14


def test_audit_sample_only_marks_windows_without_inbox_signals() -> None:
    from tests.ai.helpers import single as single_window

    digest = input_sha256(single_window("лифт не работает"))
    assert apply_audit_sample((), digest, 100) == ()


async def test_competence_does_not_change_strength() -> None:
    """Проблема вне зоны УК остаётся сигналом той же силы."""
    inside = await WindowAnalyzer().analyze(single("в подъезде нет света на лестнице"))
    outside = await WindowAnalyzer().analyze(single("на улице у остановки не горят фонари"))
    assert inside.signals[0].strength == outside.signals[0].strength == "weak"
    assert inside.signals[0].disposition == outside.signals[0].disposition == "inbox"
