"""Выбранные модели и режимы схемы: ресурс `models.v1.yaml`.

Файл заполняет отбор (`evaluation/select_models.py`) по результату прогона на
**синтетических** окнах. Здесь он только читается: продукт собирает провайдера
из настроек и профиля модели, не зашивая имена моделей в код.

Профиль отвечает на вопрос «как обращаться к этой модели»: режим схемы, лимит
токенов, таймаут, температура и параметры конкретного семейства. Вопрос «можно
ли включать LLM-слой вообще» решается в P6 на данных D2/D3, а не этим файлом.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from domsignal.ai.resources import load_yaml_resource
from domsignal.ai.schema_modes import SCHEMA_MODES, SchemaMode

MODELS_RESOURCE = "models.v1.yaml"


class ModelsUnavailable(RuntimeError):
    """Ресурс выбранных моделей отсутствует или не проходит проверку."""


@dataclass(frozen=True)
class ModelProfile:
    """Как обращаться к конкретной модели и на каком основании она допущена."""

    id: str
    label: str
    role: str
    schema_mode: SchemaMode
    max_tokens: int
    timeout_seconds: float
    temperature: float | None
    extra_body: dict[str, Any]
    upstream: str
    stores_data_in_russia: bool
    policy_basis: str
    policy_checked_at: str


@dataclass(frozen=True)
class ModelCatalog:
    """Модель по умолчанию и резервы в порядке подстановки."""

    version: str
    selected_at: str
    note: str
    models: tuple[ModelProfile, ...]
    default_id: str | None

    @property
    def default(self) -> ModelProfile | None:
        return self.get(self.default_id) if self.default_id else None

    @property
    def fallbacks(self) -> tuple[ModelProfile, ...]:
        return tuple(item for item in self.models if item.id != self.default_id)

    def get(self, model_id: str | None) -> ModelProfile | None:
        return next((item for item in self.models if item.id == model_id), None)


def build_catalog(document: Any) -> ModelCatalog:
    if not isinstance(document, dict):
        raise ModelsUnavailable("models document must be a mapping")
    data = cast(dict[str, Any], document)
    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ModelsUnavailable("models list is empty")
    profiles: list[ModelProfile] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise ModelsUnavailable("model entry must be a mapping")
        entry = cast(dict[str, Any], raw)
        mode = entry.get("schema_mode")
        if mode not in SCHEMA_MODES:
            raise ModelsUnavailable(f"{entry.get('id')}: unknown schema mode {mode!r}")
        profiles.append(
            ModelProfile(
                id=str(entry["id"]),
                label=str(entry.get("label", entry["id"])),
                role=str(entry.get("role", "fallback")),
                schema_mode=cast(SchemaMode, mode),
                max_tokens=int(entry.get("max_tokens", 1600)),
                timeout_seconds=float(entry.get("timeout_seconds", 10)),
                temperature=entry.get("temperature"),
                extra_body=dict(entry.get("extra_body") or {}),
                upstream=str(entry.get("upstream", "")),
                stores_data_in_russia=bool(entry.get("stores_data_in_russia", False)),
                policy_basis=str(entry.get("policy_basis", "")),
                policy_checked_at=str(entry.get("policy_checked_at", "")),
            )
        )
    default_id = data.get("default")
    if default_id is not None and not any(item.id == default_id for item in profiles):
        raise ModelsUnavailable(f"default model {default_id!r} is not in the list")
    return ModelCatalog(
        version=str(data.get("version", "unknown")),
        selected_at=str(data.get("selected_at", "")),
        note=str(data.get("note", "")),
        models=tuple(profiles),
        default_id=str(default_id) if default_id else None,
    )


@lru_cache(maxsize=1)
def load_models() -> ModelCatalog:
    """Каталог выбранных моделей из ресурсов пакета (кэшируется на процесс)."""
    try:
        document = load_yaml_resource(MODELS_RESOURCE)
    except FileNotFoundError as exc:
        raise ModelsUnavailable(
            "ресурс models.v1.yaml отсутствует: отбор моделей ещё не выполнялся"
        ) from exc
    return build_catalog(document)
