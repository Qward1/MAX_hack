"""Тихие часы (BOT-VOICE-HUMAN-2026-09-27): окно по Москве, через полночь."""

from datetime import UTC, datetime

import pytest

from domsignal.core.quiet_hours import MSK, minutes_label, parse_minutes, quiet_until
from domsignal.services.digest import next_run


def msk(hour: int, minute: int = 0, day: int = 27) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=MSK)


@pytest.mark.parametrize(
    ("at", "until"),
    [
        (msk(23, 30), msk(8, 0, day=28)),
        (msk(2, 0), msk(8, 0)),
        (msk(7, 59), msk(8, 0)),
        (msk(8, 0), None),
        (msk(21, 59), None),
        (msk(22, 0), msk(8, 0, day=28)),
    ],
)
def test_the_default_window_crosses_midnight(at: datetime, until: datetime | None) -> None:
    assert quiet_until(22 * 60, 8 * 60, at.astimezone(UTC)) == until


def test_a_day_window_and_no_window() -> None:
    assert quiet_until(13 * 60, 15 * 60, msk(14, 0)) == msk(15, 0)
    assert quiet_until(13 * 60, 15 * 60, msk(15, 0)) is None
    assert quiet_until(0, 0, msk(3, 0)) is None


def test_labels_round_trip_and_reject_bad_input() -> None:
    assert minutes_label(1320) == "22:00" and parse_minutes("07:30") == 450
    for bad in ("24:00", "7:5", "ab:cd", "12:60"):
        with pytest.raises(ValueError):
            parse_minutes(bad)


def test_the_digest_runs_at_nine_moscow_time() -> None:
    assert next_run(msk(8, 59).astimezone(UTC), 9) == msk(9, 0).astimezone(UTC)
    assert next_run(msk(9, 0).astimezone(UTC), 9) == msk(9, 0, day=28).astimezone(UTC)
