"""P7b §1.1–1.2: время показа, текст оповещения и выбор реплики-доказательства."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from domsignal.core.display_time import display_zone, staff_moment, zone_label
from domsignal.services.chat_voice import SignalAlertIntent, operator_alert_message
from domsignal.services.signals import SignalEngine, added_kinds, evidence_mid
from domsignal.settings import Settings

MOMENT = datetime(2026, 9, 23, 10, 18, 1, tzinfo=UTC)


def test_staff_time_is_moscow_with_its_label() -> None:
    assert staff_moment(MOMENT) == "23.09.2026 13:18 МСК"
    assert staff_moment(MOMENT, "Europe/Moscow") == "23.09.2026 13:18 МСК"
    # Полночь по UTC — уже следующий день в Москве.
    assert staff_moment(datetime(2026, 9, 23, 22, 30, tzinfo=UTC)) == "24.09.2026 01:30 МСК"


def test_other_zones_get_an_offset_label_not_msk() -> None:
    fixed = UTC
    assert zone_label("Etc/UTC", MOMENT.astimezone(fixed)) == "UTC+00:00"
    try:
        display_zone("Asia/Yekaterinburg")
    except ValueError:
        pytest.skip("нет базы часовых поясов (Windows без tzdata)")
    assert staff_moment(MOMENT, "Asia/Yekaterinburg") == "23.09.2026 15:18 UTC+05:00"


def test_an_unknown_display_zone_stops_the_start() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, display_timezone="Mars/Olympus")
    assert Settings(_env_file=None).display_timezone == "Europe/Moscow"


def test_the_first_alert_quotes_the_line_with_msk_time() -> None:
    text = operator_alert_message(
        house_address="Казань, улица, 1",
        danger_kinds=["gas"],
        from_rules=True,
        quote="Пахнет газом во втором подъезде",
        quote_author="A",
        quote_sent_at=MOMENT,
    ).text
    assert text.splitlines()[0] == "ДомСигнал: возможная опасность в домовом чате."
    assert "Признаки: запах газа" in text
    assert "Цитата: «Пахнет газом во втором подъезде» — Житель A, 23.09.2026 13:18 МСК" in text
    assert "UTC" not in text


def test_a_new_kind_alert_names_the_new_kind_and_all_kinds() -> None:
    text = operator_alert_message(
        house_address="Казань, улица, 1",
        danger_kinds=["gas", "smoke_fire"],
        from_rules=True,
        quote="и дымом тоже тянет",
        quote_author="A",
        quote_sent_at=MOMENT,
        new_kinds=["smoke_fire"],
    ).text
    lines = text.splitlines()
    assert lines[0] == "ДомСигнал: новый признак опасности в уже открытом сигнале."
    assert "Новый признак: дым или огонь" in lines
    assert "Все признаки сигнала: запах газа, дым или огонь" in lines
    assert not any(line.startswith("Признаки:") for line in lines)


def test_the_intent_carries_no_words_of_residents() -> None:
    fields = set(SignalAlertIntent.model_fields)
    assert fields == {"signal_id", "house_id", "new_kinds", "evidence_mid"}
    assert not fields & {"quote", "text", "description"}


def test_evidence_prefers_rules_then_verified_quotes() -> None:
    evidence = [
        {"kind": "person_trapped", "line_mid": "m-a", "source": "semantic", "quote_valid": False},
        {"kind": "person_trapped", "line_mid": "m-b", "source": "semantic", "quote_valid": True},
        {"kind": "gas", "line_mid": "m-c", "source": "rules"},
    ]
    assert evidence_mid(evidence, ["person_trapped"]) == "m-b"
    assert evidence_mid(evidence, ["gas"]) == "m-c"
    assert evidence_mid(evidence, []) == "m-c"
    assert evidence_mid(evidence, ["flooding"]) is None
    assert evidence_mid([{"kind": "gas", "line_mid": None, "source": "rules"}], ["gas"]) is None


def test_only_kinds_the_signal_did_not_have_are_new() -> None:
    assert added_kinds(["gas"], ["gas", "smoke_fire"]) == ["smoke_fire"]
    assert added_kinds(["gas"], ["gas"]) == []
    assert added_kinds([], ["person_trapped", "person_trapped"]) == ["person_trapped"]


def test_each_new_kind_has_its_own_alert_key() -> None:
    signal_id = "0b4e3f1c-2f7a-4c5e-9a3d-7c1f2e3d4b5a"
    first = SignalEngine.alert_key(signal_id)  # type: ignore[arg-type]
    smoke = SignalEngine.alert_key(signal_id, ["smoke_fire"])  # type: ignore[arg-type]
    assert first == f"signal_alert:{signal_id}"
    assert smoke == f"signal_alert:{signal_id}:smoke_fire"
    both = SignalEngine.alert_key(signal_id, ["smoke_fire", "gas"])  # type: ignore[arg-type]
    assert both == f"signal_alert:{signal_id}:gas+smoke_fire" and len(both) <= 100
