"""Режимы структурированного ответа: одна схема — три формы запроса.

Провайдеры принимают JSON Schema по-разному. Строгий режим (`strict: true`)
требует, чтобы каждое свойство было в `required`, необязательное значение было
явно `null`-способным и чтобы в схеме не было ключевых слов, которые он не
поддерживает. Нестрогий режим принимает ту же схему без гарантии. Самые
простые модели умеют только «ответь любым JSON».

Гарантия провайдера здесь ничего не решает: **источником истины остаётся наш
валидатор** (`WindowModelOutput` + `validate_output`). Режим схемы влияет лишь
на то, сколько мусора приходит и как часто приходится отбрасывать окно.
"""

from __future__ import annotations

import copy
from typing import Any, Literal, cast

from domsignal.ai.model_output import SCHEMA_ID, build_json_schema
from domsignal.ai.taxonomy import Taxonomy

SchemaMode = Literal["json_schema_strict", "json_schema", "json_object"]

#: Порядок подбора режима при отборе моделей: от строгого к самому простому.
SCHEMA_MODES: tuple[SchemaMode, ...] = ("json_schema_strict", "json_schema", "json_object")

#: Ключевые слова, которые строгий режим обычно не поддерживает.
UNSUPPORTED_IN_STRICT: frozenset[str] = frozenset(
    {"default", "format", "maxItems", "maxLength", "minItems", "minLength", "pattern"}
)


class SchemaModeError(ValueError):
    """Запрошен режим схемы, которого не существует."""


def normalize_for_strict(schema: dict[str, Any]) -> dict[str, Any]:
    """Привести схему к форме, которую принимает строгий структурированный вывод.

    Что делается: каждое свойство попадает в `required`; `additionalProperties`
    везде `false`; неподдерживаемые ключевые слова убираются. Необязательные
    значения уже описаны как `anyOf` с `null` (pydantic), поэтому «необязательно»
    превращается в «обязательно, но может быть `null`». Массивы с умолчанием
    `()` становятся обязательными массивами: пустой список разрешён, `null` —
    нет. Перечисления сохраняются как есть.
    """
    result = copy.deepcopy(schema)
    _strictify(result)
    return result


def _strictify(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _strictify(item)
        return
    if not isinstance(node, dict):
        return
    mapping = cast(dict[str, Any], node)
    for keyword in UNSUPPORTED_IN_STRICT:
        mapping.pop(keyword, None)
    properties = mapping.get("properties")
    if mapping.get("type") == "object" and isinstance(properties, dict):
        mapping["additionalProperties"] = False
        mapping["required"] = list(cast(dict[str, Any], properties))
    for value in mapping.values():
        _strictify(value)


def strict_schema(taxonomy: Taxonomy | None = None, *, compact: bool = False) -> dict[str, Any]:
    """JSON Schema ответа модели в форме строгого режима.

    `compact` убирает `title` у свойств: pydantic пишет их везде, модели они
    ничего не сообщают, а в запросе стоят сотни токенов. Валидация от этого не
    меняется — источник истины по-прежнему наш валидатор.
    """
    schema = normalize_for_strict(build_json_schema(taxonomy))
    if compact:
        _drop_titles(schema)
    return schema


def _drop_titles(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _drop_titles(item)
        return
    if not isinstance(node, dict):
        return
    mapping = cast(dict[str, Any], node)
    title = mapping.get("title")
    if isinstance(title, str) and title != SCHEMA_ID:
        mapping.pop("title")
    properties = mapping.get("properties")
    for key, value in mapping.items():
        if key == "properties" and isinstance(properties, dict):
            for item in cast(dict[str, Any], properties).values():
                _drop_titles(item)
        elif key != "properties":
            _drop_titles(value)


def response_format(
    mode: SchemaMode,
    taxonomy: Taxonomy | None = None,
    *,
    name: str = SCHEMA_ID,
    compact: bool = False,
) -> dict[str, Any]:
    """Значение поля `response_format` запроса для выбранного режима.

    В режиме `json_object` схема в запрос не уходит: её несёт текст промпта
    (`domsignal.ai.prompts.render_system_prompt`).
    """
    if mode == "json_object":
        return {"type": "json_object"}
    if mode not in ("json_schema", "json_schema_strict"):
        raise SchemaModeError(f"unknown schema mode {mode!r}")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name.replace(".", "_"),
            "strict": mode == "json_schema_strict",
            "schema": strict_schema(taxonomy, compact=compact),
        },
    }


def schema_in_prompt(mode: SchemaMode) -> bool:
    """Нужно ли вкладывать схему в текст промпта."""
    return mode == "json_object"
