"""Загрузка и валидация таксономии подтипов v2.

Подтип — стабильный код, общий для AI и продукта. Маршрутов, организаций и
сроков в таксономии нет: ответственность определяет Responsibility Router.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, cast

from domsignal.ai.matching import StemMatch, StemSet, Token
from domsignal.ai.resources import load_yaml_resource
from domsignal.core.incidents import ReportCategory

DedupeScope = Literal["object", "house"]

#: Код, используемый когда подтип не определён.
UNSPECIFIED = "other.unspecified"

NEGATION_WORDS: frozenset[str] = frozenset(
    {"не", "нет", "нету", "ни", "никто", "никого", "ничего", "без"}
)


class TaxonomyError(RuntimeError):
    """Таксономия отсутствует или не проходит валидацию."""


@dataclass(frozen=True)
class Subtype:
    code: str
    product_category: ReportCategory
    dedupe_scope: DedupeScope
    label: str
    description: str
    patterns: tuple[tuple[StemSet, ...], ...]
    exclude: StemSet


@dataclass(frozen=True)
class SubtypeMatch:
    subtype: Subtype
    groups: tuple[StemMatch, ...]

    @property
    def object_match(self) -> StemMatch | None:
        return self.groups[0] if len(self.groups) > 1 else None

    @property
    def state_match(self) -> StemMatch:
        return self.groups[-1]


def _negated(tokens: Sequence[Token], match: StemMatch, negation: frozenset[str]) -> bool:
    if tokens[match.first_token].text in negation:
        return False
    for offset in (1, 2):
        index = match.first_token - offset
        if index >= 0 and tokens[index].text in negation:
            return True
    after = match.last_token + 1
    return after < len(tokens) and tokens[after].text in negation


class Taxonomy:
    """Скомпилированная таксономия подтипов."""

    def __init__(self, version: str, subtypes: Sequence[Subtype]) -> None:
        self.version = version
        self.subtypes = tuple(subtypes)
        self.by_code = {subtype.code: subtype for subtype in self.subtypes}
        if UNSPECIFIED not in self.by_code:
            raise TaxonomyError(f"taxonomy must define {UNSPECIFIED}")

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(self.by_code)

    def get(self, code: str) -> Subtype:
        return self.by_code.get(code, self.by_code[UNSPECIFIED])

    def is_known(self, code: str) -> bool:
        return code in self.by_code

    def product_category(self, code: str) -> ReportCategory:
        return self.get(code).product_category

    def match(
        self,
        tokens: Sequence[Token],
        negation: frozenset[str] = NEGATION_WORDS,
    ) -> list[SubtypeMatch]:
        """Все сработавшие подтипы в порядке приоритета таксономии.

        Отрицание проверяется только у последней группы правила — группы
        состояния: «воду не отключали» не является сообщением о проблеме,
        а «нет горячей воды» является.
        """
        results: list[SubtypeMatch] = []
        for subtype in self.subtypes:
            if not subtype.patterns:
                continue
            if subtype.exclude and subtype.exclude.find_all(tokens):
                continue
            for pattern in subtype.patterns:
                groups: list[StemMatch] = []
                last_index = len(pattern) - 1
                for index, group in enumerate(pattern):
                    found = group.find_all(tokens)
                    if index == last_index:
                        found = [item for item in found if not _negated(tokens, item, negation)]
                    if not found:
                        break
                    groups.append(min(found, key=lambda item: item.first_token))
                else:
                    results.append(SubtypeMatch(subtype=subtype, groups=tuple(groups)))
                    break
        return results


def _as_list(raw: Any, field: str, code: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise TaxonomyError(f"{code}: {field} must be a list of strings")
    return cast(list[str], raw)


def _build_subtype(raw: Any, fuzzy: Sequence[str]) -> Subtype:
    if not isinstance(raw, dict):
        raise TaxonomyError("subtype entry must be a mapping")
    entry = cast(dict[str, Any], raw)
    code = entry.get("code")
    if not isinstance(code, str) or not code:
        raise TaxonomyError("subtype entry without code")
    category = entry.get("product_category")
    if category not in tuple(item.value for item in ReportCategory):
        raise TaxonomyError(f"{code}: unknown product_category {category!r}")
    scope = entry.get("dedupe_scope")
    if scope not in ("object", "house"):
        raise TaxonomyError(f"{code}: dedupe_scope must be object or house")
    label = entry.get("label")
    description = entry.get("description")
    if not isinstance(label, str) or not isinstance(description, str):
        raise TaxonomyError(f"{code}: label and description are required")
    patterns: list[tuple[StemSet, ...]] = []
    raw_patterns = entry.get("patterns") or []
    if not isinstance(raw_patterns, list):
        raise TaxonomyError(f"{code}: patterns must be a list")
    for item in raw_patterns:
        if not isinstance(item, dict) or "all" not in item:
            raise TaxonomyError(f"{code}: every pattern needs an 'all' group list")
        groups = cast(dict[str, Any], item)["all"]
        if not isinstance(groups, list) or not groups:
            raise TaxonomyError(f"{code}: pattern 'all' must be a non-empty list")
        patterns.append(
            tuple(
                StemSet(_as_list(group, "pattern group", code), fuzzy)
                for group in groups
            )
        )
    exclude = StemSet(_as_list(entry.get("exclude") or [], "exclude", code), fuzzy)
    return Subtype(
        code=code,
        product_category=ReportCategory(category),
        dedupe_scope=cast(DedupeScope, scope),
        label=label,
        description=description,
        patterns=tuple(patterns),
        exclude=exclude,
    )


def build_taxonomy(document: Any, fuzzy_stems: Sequence[str] = ()) -> Taxonomy:
    if not isinstance(document, dict):
        raise TaxonomyError("taxonomy document must be a mapping")
    data = cast(dict[str, Any], document)
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise TaxonomyError("taxonomy version is required")
    raw_subtypes = data.get("subtypes")
    if not isinstance(raw_subtypes, list) or not raw_subtypes:
        raise TaxonomyError("taxonomy needs a non-empty subtypes list")
    subtypes = [_build_subtype(item, fuzzy_stems) for item in raw_subtypes]
    codes = [subtype.code for subtype in subtypes]
    if len(set(codes)) != len(codes):
        raise TaxonomyError("subtype codes must be unique")
    return Taxonomy(version=version, subtypes=subtypes)


@lru_cache(maxsize=1)
def load_taxonomy() -> Taxonomy:
    """Таксономия из ресурсов пакета (кэшируется на процесс)."""
    from domsignal.ai.rules.lexicon import load_lexicon

    return build_taxonomy(load_yaml_resource("taxonomy.v2.yaml"), load_lexicon().fuzzy_stems)
