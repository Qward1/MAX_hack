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


#: M1 (27.09.2026): правила хакатона — ни американских, ни проприетарных моделей.
US_DEVELOPERS = ("openai/", "anthropic/", "google/", "meta-llama/", "microsoft/", "x-ai/")
PROPRIETARY = ("gigachat/", "yandex", "gpt-", "gemini", "gemma", "claude")


def test_shipped_resource_excludes_the_forbidden_models() -> None:
    for profile in load_models().models:
        lowered = profile.id.lower()
        assert not lowered.startswith(US_DEVELOPERS), profile.id
        assert not any(marker in lowered for marker in PROPRIETARY), profile.id
        assert "preview" not in lowered and "free" not in lowered


def test_shipped_default_profile_follows_the_m1_measurement() -> None:
    """M1: открытая Qwen3 в Cloud.ru, без рассуждений, цена для учёта ₽."""
    catalog = load_models()
    default = catalog.default
    assert default is not None
    assert default.id == "Qwen/Qwen3-30B-A3B"
    assert default.schema_mode == "json_schema_strict"
    assert default.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert default.open_danger_extra_body == {}
    assert default.price_rub_per_million == (13.908, 55.6076)
    assert default.temperature == 0
    assert default.max_tokens == 1600
    # Аренда AI-пула production (80 с) покрывает таймаут с запасом 20 с.
    assert 0 < default.timeout_seconds <= 60.0
    # Внешняя модель каталога Cloud.ru: данные уходят вне его инфраструктуры.
    assert default.stores_data_in_russia is False
    for profile in catalog.models:
        assert profile.price_rub_per_million is not None, profile.id


def test_price_must_be_numeric_and_not_negative() -> None:
    entry = {**DOCUMENT["models"][0], "price_rub_per_million": {"input": 1.5, "output": 3}}
    catalog = build_catalog({**DOCUMENT, "models": [entry]})
    assert catalog.models[0].price_rub_per_million == (1.5, 3.0)
    for broken in ({"input": 1}, {"input": "x", "output": 1}, {"input": -1, "output": 1}, 5):
        with pytest.raises(ModelsUnavailable):
            build_catalog({**DOCUMENT, "models": [{**entry, "price_rub_per_million": broken}]})
