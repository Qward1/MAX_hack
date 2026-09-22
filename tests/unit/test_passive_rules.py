"""Чистые правила продукта пассивного чтения: фильтр, склейка, лимит `weak`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domsignal.core.signals import (
    MAX_QUOTES,
    QUOTE_LIMIT,
    TEXT_LIMIT,
    BindingState,
    buffer_text,
    danger_key,
    dedupe_key,
    is_command,
    place_signal,
    quote_text,
    stronger,
    structural_drop_reason,
)
from domsignal.services.signals import PassiveConfig
from domsignal.settings import Settings

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
HOUR_AGO = NOW - timedelta(hours=1)
ACTIVE = BindingState(status="active", activated_at=HOUR_AGO, passive_capture_enabled=True)

BASE = dict(
    capture_enabled=True,
    kind="message_created",
    chat_id="-701",
    actor="711",
    mid="mid.1",
    text="Лифт стоит",
    occurred_at=NOW,
    binding=ACTIVE,
)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({}, None),
        ({"capture_enabled": False}, "capture_disabled"),
        ({"kind": "message_callback"}, "not_a_message"),
        ({"kind": "bot_added"}, "not_a_message"),
        ({"chat_id": None}, "not_a_message"),
        ({"actor": None}, "not_a_message"),
        ({"binding": None}, "no_binding"),
        ({"binding": BindingState("suspended", HOUR_AGO, True)}, "binding_inactive"),
        ({"binding": BindingState("revoked", HOUR_AGO, True)}, "binding_inactive"),
        ({"binding": BindingState("active", None, True)}, "before_activation"),
        ({"occurred_at": NOW - timedelta(hours=2)}, "before_activation"),
        ({"binding": BindingState("active", HOUR_AGO, False)}, "binding_capture_disabled"),
        # Бот, канал и пустое тело нормализуются в пустой текст ещё при разборе.
        ({"text": None}, "no_text"),
        ({"text": "   \n "}, "no_text"),
        ({"mid": None}, "no_message_id"),
        ({"text": "/report elevator Лифт стоит"}, "command"),
        ({"text": "/report Лифт стоит"}, "command"),
        ({"text": "  /start"}, "command"),
        ({"text": "/help@domsignal_bot"}, "command"),
        ({"text": "/ это не команда"}, None),
        ({"text": "Кто писал /report вчера?"}, None),
    ],
)
def test_structural_filter_table(change: dict[str, object], reason: str | None) -> None:
    assert structural_drop_reason(**{**BASE, **change}) == reason  # type: ignore[arg-type]


def test_commands_are_detected_only_at_the_start() -> None:
    assert is_command("/report elevator Лифт")
    assert not is_command("Ответ на /report")
    assert not is_command("//report")


def test_buffer_text_is_cut_at_the_core_line_limit_with_a_flag() -> None:
    assert buffer_text("коротко") == ("коротко", False)
    text, truncated = buffer_text("я" * (TEXT_LIMIT + 7))
    assert len(text) == TEXT_LIMIT and truncated


def test_quotes_are_verbatim_prefixes() -> None:
    assert quote_text("  Лифт стоит  ") == "Лифт стоит"
    long = quote_text("слово " * 200)
    assert len(long) == QUOTE_LIMIT and long.endswith("…")
    assert "слово слово".startswith(long[:5])
    assert MAX_QUOTES == 3


@pytest.mark.parametrize(
    ("subtype", "scope", "entrance", "key"),
    [
        ("water.hot_outage", "house", "2", "water.hot_outage|house"),
        ("water.hot_outage", "house", None, "water.hot_outage|house"),
        ("elevator.stopped", "object", "2", "elevator.stopped|object|2"),
        ("elevator.stopped", "object", " 2 ", "elevator.stopped|object|2"),
        ("elevator.stopped", "object", "Второй", "elevator.stopped|object|второй"),
        ("elevator.stopped", "object", None, "elevator.stopped|object|-"),
    ],
)
def test_dedupe_key(subtype: str, scope: str, entrance: str | None, key: str) -> None:
    assert dedupe_key(subtype, scope, entrance) == key


def test_an_unknown_entrance_does_not_merge_with_a_known_one() -> None:
    assert dedupe_key("elevator.stopped", "object", None) != dedupe_key(
        "elevator.stopped", "object", "2"
    )


def test_danger_key_is_order_independent() -> None:
    assert danger_key(("gas", "smoke_fire")) == danger_key(("smoke_fire", "gas", "gas"))


@pytest.mark.parametrize(
    ("strength", "core", "sample", "weak_today", "limit", "expected"),
    [
        ("critical", "inbox", False, 99, 10, ("inbox", None)),
        ("strong", "inbox", False, 99, 10, ("inbox", None)),
        ("medium", "inbox", False, 99, 10, ("inbox", None)),
        ("weak", "inbox", False, 9, 10, ("inbox", None)),
        ("weak", "inbox", False, 10, 10, ("audit_pool", "weak_overflow")),
        ("weak", "inbox", False, 0, 0, ("audit_pool", "weak_overflow")),
        ("filtered", "audit_pool", False, 0, 10, ("audit_pool", "filtered")),
        ("filtered", "audit_pool", True, 0, 10, ("audit_pool", "audit_sample")),
    ],
)
def test_weak_limiter_and_audit_pool(
    strength: str,
    core: str,
    sample: bool,
    weak_today: int,
    limit: int,
    expected: tuple[str, str | None],
) -> None:
    assert (
        place_signal(strength, core, audit_sample=sample, weak_today=weak_today, weak_limit=limit)
        == expected
    )


def test_strength_only_grows_when_a_thread_is_merged() -> None:
    assert stronger("weak", "critical") and stronger("filtered", "weak")
    assert not stronger("critical", "strong") and not stronger("medium", "medium")


def test_window_policy_values_come_from_settings_with_core_defaults() -> None:
    from domsignal.ai import WindowPolicy

    defaults = PassiveConfig.from_settings(Settings(_env_file=None))
    core = WindowPolicy()
    assert defaults.capture_enabled is False
    assert (
        defaults.policy.silence_seconds,
        defaults.policy.max_lines,
        defaults.policy.max_age_seconds,
    ) == (core.silence_seconds, core.max_lines, core.max_age_seconds)
    assert (defaults.weak_daily_limit, defaults.dedupe_days, defaults.buffer_hours) == (10, 7, 72)
    demo = PassiveConfig.from_settings(
        Settings(_env_file=None, passive_window_silence_seconds=20)
    )
    assert demo.policy.silence_seconds == 20


def test_the_buffer_can_never_be_configured_beyond_72_hours() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(_env_file=None, passive_buffer_hours=73)
