"""Ресурс выбранных моделей: что именно продукт получает от отбора."""

from __future__ import annotations

from typing import Any

import pytest

from domsignal.ai.models import (
    ModelsUnavailable,
    build_catalog,
    load_models,
)
from domsignal.ai.schema_modes import SCHEMA_MODES

DOCUMENT: dict[str, Any] = {
    "version": "v1",
    "selected_at": "2026-09-20",
    "note": "синтетика",
    "default": "openai/gpt-5-nano",
    "models": [
        {
            "id": "openai/gpt-5-nano",
            "label": "GPT-5 nano",
            "role": "default",
            "schema_mode": "json_schema_strict",
            "max_tokens": 1600,
            "timeout_seconds": 10,
            "temperature": None,
            "extra_body": {"reasoning": {"effort": "low"}},
            "upstream": "openai",
            "stores_data_in_russia": False,
            "policy_basis": "polza «Конфиденциальность»",
            "policy_checked_at": "2026-09-20",
        },
        {
            "id": "sber/gigachat-2",
            "label": "GigaChat 2",
            "role": "fallback",
            "schema_mode": "json_object",
            "max_tokens": 1600,
            "timeout_seconds": 10,
            "temperature": 0,
            "upstream": "sber-gigachat",
            "stores_data_in_russia": True,
            "policy_basis": "каталог polza",
            "policy_checked_at": "2026-09-20",
        },
    ],
}


def test_catalog_splits_the_default_and_the_reserves() -> None:
    catalog = build_catalog(DOCUMENT)
    default = catalog.default
    assert default is not None
    assert default.id == "openai/gpt-5-nano"
    assert default.temperature is None
    assert default.extra_body == {"reasoning": {"effort": "low"}}
    assert [item.id for item in catalog.fallbacks] == ["sber/gigachat-2"]
    assert catalog.get("sber/gigachat-2") is not None
    assert catalog.get("openai/gpt-4.1-nano") is None


@pytest.mark.parametrize(
    "broken",
    [
        {"models": []},
        {"models": [{"id": "x", "schema_mode": "grammar"}]},
        {"models": [{"id": "x", "schema_mode": "json_object"}], "default": "y"},
        "не документ",
    ],
)
def test_broken_resource_is_refused(broken: Any) -> None:
    with pytest.raises(ModelsUnavailable):
        build_catalog(broken)


def test_shipped_resource_is_the_result_of_the_selection() -> None:
    catalog = load_models()
    assert catalog.version == "v1"
    assert catalog.selected_at
    assert 1 <= len(catalog.models) <= 3
    default = catalog.default
    assert default is not None, "модель по умолчанию должна быть выбрана"
    assert default.role == "default"
    for profile in catalog.models:
        assert profile.schema_mode in SCHEMA_MODES
        assert profile.policy_basis, f"{profile.id}: нет основания политики данных"
        assert profile.policy_checked_at, f"{profile.id}: нет даты проверки"
        assert profile.max_tokens > 0
        assert profile.timeout_seconds > 0


def test_shipped_resource_excludes_the_forbidden_providers() -> None:
    for profile in load_models().models:
        lowered = f"{profile.id} {profile.upstream}".lower()
        assert "deepseek" not in lowered
        assert "open-inference" not in lowered and "openinference" not in lowered
        assert "preview" not in lowered
        assert "free" not in lowered


def test_shipped_default_profile_follows_the_p6_measurement() -> None:
    """Профиль P6: минимальные рассуждения, flex первым, таймаут ≤ production."""
    default = load_models().default
    assert default is not None
    assert default.extra_body["reasoning"] == {"effort": "minimal"}
    assert default.extra_body["provider"]["order"][0] == "openai/flex"
    assert default.extra_body["provider"]["allow_fallbacks"] is True
    assert 20.0 < default.timeout_seconds <= 60.0
    # P6b: окна при открытом сигнале об опасности — reasoning low.
    assert default.open_danger_extra_body == {"reasoning": {"effort": "low"}}
