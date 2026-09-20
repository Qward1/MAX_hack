"""Строгая схема ответа модели на окно и экспорт JSON Schema.

Закрытые перечисления описаны в JSON Schema (провайдер получает `enum`), но в
Python остаются строками: по контракту неизвестное значение перечисления
отбрасывается валидатором, а не роняет разбор всего окна. Структурно неверный
JSON — другое дело, он даёт `fallback_invalid_output`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from domsignal.ai.contracts import (
    DANGER_KINDS,
    FACET_VALUES,
    LOCATION_SCOPES,
    REFUTATION_REASONS,
    ROLES,
)
from domsignal.ai.taxonomy import Taxonomy, load_taxonomy

SCHEMA_ID = "window_output.v1"
SCHEMA_RESOURCE = "schemas/window_output.v1.json"

MAX_SIGNALS = 5
_SUBTYPE_PLACEHOLDER = "__subtype_enum__"


def _enum(values: tuple[str, ...]) -> dict[str, Any]:
    return {"enum": list(values)}


class Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelEvidence(Strict):
    msg: str = Field(description="Идентификатор реплики окна, например m3")
    quote: str = Field(description="Дословная цитата из этой реплики")


class ModelValue(Strict):
    value: str
    quote: str
    msg: str


class ModelScope(Strict):
    value: Annotated[str, Field(json_schema_extra=_enum(LOCATION_SCOPES))]
    quote: str | None = None
    msg: str | None = None


class ModelFacet(Strict):
    v: Annotated[str, Field(json_schema_extra=_enum(FACET_VALUES))]
    quote: str | None = None
    msg: str | None = None


class ModelFacets(Strict):
    current: ModelFacet
    local: ModelFacet
    observed: ModelFacet


class ModelDanger(Strict):
    kind: Annotated[str, Field(json_schema_extra=_enum(DANGER_KINDS))]
    evidence: tuple[ModelEvidence, ...] = Field(default=(), max_length=8)
    contextual: bool = False


class ModelRefutation(Strict):
    reason: Annotated[str, Field(json_schema_extra=_enum(REFUTATION_REASONS))]
    quote: str
    msg: str


class ModelText(Strict):
    text: str = Field(max_length=1000)
    sources: tuple[str, ...] = Field(default=(), max_length=40)


class ModelSignal(Strict):
    ref: str = Field(description="new:N для новой проблемы или open:K открытого элемента")
    subtype: Annotated[str, Field(json_schema_extra={"enum": [_SUBTYPE_PLACEHOLDER]})]
    object: str = Field(max_length=120)
    entrance: ModelValue | None = None
    floor: ModelValue | None = None
    since: ModelValue | None = None
    location_scope: ModelScope
    facets: ModelFacets
    danger: tuple[ModelDanger, ...] = Field(default=(), max_length=8)
    danger_refutation: ModelRefutation | None = None
    clean_description: ModelText | None = None
    summary: ModelText | None = None


class ModelLine(Strict):
    id: str
    role: Annotated[str, Field(json_schema_extra=_enum(ROLES))]
    signals: tuple[str, ...] = Field(default=(), max_length=MAX_SIGNALS)
    link_certainty: Literal["sure", "unsure"] | None = None


class WindowModelOutput(Strict):
    """Ответ модели на одно окно."""

    messages: tuple[ModelLine, ...] = Field(default=(), max_length=45)
    signals: tuple[ModelSignal, ...] = Field(default=(), max_length=MAX_SIGNALS)


def _inject_subtypes(node: Any, codes: list[str]) -> None:
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        enum = mapping.get("enum")
        if isinstance(enum, list) and enum == [_SUBTYPE_PLACEHOLDER]:
            mapping["enum"] = codes
        for value in mapping.values():
            _inject_subtypes(value, codes)
    elif isinstance(node, list):
        for value in node:
            _inject_subtypes(value, codes)


def build_json_schema(taxonomy: Taxonomy | None = None) -> dict[str, Any]:
    """JSON Schema ответа модели с `additionalProperties: false` везде."""
    tax = taxonomy or load_taxonomy()
    schema = WindowModelOutput.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = SCHEMA_ID
    _inject_subtypes(schema, list(tax.codes))
    return schema
