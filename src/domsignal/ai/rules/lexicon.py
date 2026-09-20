"""Роли реплик, recall-гейт и вспомогательные маркеры правил."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from domsignal.ai.contracts import LineRole, LocationScope
from domsignal.ai.matching import StemSet, Token, tokenize
from domsignal.ai.normalize import normalize
from domsignal.ai.resources import load_yaml_resource


class LexiconError(RuntimeError):
    """Лексикон отсутствует или не проходит валидацию."""


@dataclass(frozen=True)
class Lexicon:
    version: str
    fuzzy_stems: tuple[str, ...]
    break_markers: StemSet
    complaint_markers: StemSet
    absence_markers: StemSet
    negation_tokens: frozenset[str]
    roles: dict[str, StemSet]
    displaced: StemSet
    hypothesis: StemSet
    planned_duration: StemSet
    more_info: StemSet
    location_scope: tuple[tuple[LocationScope, StemSet], ...]


def _strings(document: dict[str, Any], key: str) -> list[str]:
    raw = document.get(key)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise LexiconError(f"lexicon key {key!r} must be a list of strings")
    return cast(list[str], raw)


_ROLE_KEYS = (
    "status_question",
    "resolved_claim",
    "announcement",
    "me_too",
    "objection",
    "out_of_scope",
    "chatter",
)
_SCOPE_VALUES: tuple[LocationScope, ...] = (
    "apartment",
    "house_common",
    "house_territory",
    "municipal_territory",
    "external_network",
    "other_building",
)


def build_lexicon(document: Any) -> Lexicon:
    if not isinstance(document, dict):
        raise LexiconError("lexicon document must be a mapping")
    data = cast(dict[str, Any], document)
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise LexiconError("lexicon version is required")
    fuzzy = tuple(_strings(data, "fuzzy_stems"))
    raw_roles = data.get("roles")
    if not isinstance(raw_roles, dict):
        raise LexiconError("lexicon roles must be a mapping")
    roles_document = cast(dict[str, Any], raw_roles)
    roles = {key: StemSet(_strings(roles_document, key), fuzzy) for key in _ROLE_KEYS}
    raw_scope = data.get("location_scope")
    if not isinstance(raw_scope, list) or not raw_scope:
        raise LexiconError("lexicon location_scope must be a non-empty list")
    scope: list[tuple[LocationScope, StemSet]] = []
    for item in raw_scope:
        if not isinstance(item, dict):
            raise LexiconError("location_scope entry must be a mapping")
        entry = cast(dict[str, Any], item)
        value = entry.get("value")
        if value not in _SCOPE_VALUES:
            raise LexiconError(f"unknown location scope {value!r}")
        scope.append((cast(LocationScope, value), StemSet(_strings(entry, "markers"), fuzzy)))
    return Lexicon(
        version=version,
        fuzzy_stems=fuzzy,
        break_markers=StemSet(_strings(data, "break_markers"), fuzzy),
        complaint_markers=StemSet(_strings(data, "complaint_markers"), fuzzy),
        absence_markers=StemSet(_strings(data, "absence_markers"), fuzzy),
        negation_tokens=frozenset(_strings(data, "negation_tokens")),
        roles=roles,
        displaced=StemSet(_strings(data, "displaced_markers"), fuzzy),
        hypothesis=StemSet(_strings(data, "hypothesis_markers"), fuzzy),
        planned_duration=StemSet(_strings(data, "planned_duration_markers"), fuzzy),
        more_info=StemSet(_strings(data, "more_info_markers"), fuzzy),
        location_scope=tuple(scope),
    )


@lru_cache(maxsize=1)
def load_lexicon() -> Lexicon:
    return build_lexicon(load_yaml_resource("lexicon.r1.yaml"))


def has_chatter_marker(tokens: Sequence[Token], lexicon: Lexicon | None = None) -> bool:
    """Явный маркер болтовни: приветствие, продажа, благодарность, смех."""
    return bool((lexicon or load_lexicon()).roles["chatter"].find_all(tokens))


def is_displaced(tokens: Sequence[Token], lexicon: Lexicon | None = None) -> bool:
    """Маркеры «не здесь / не сейчас»: соседний дом, новости, прошлое."""
    return bool((lexicon or load_lexicon()).displaced.find_all(tokens))


def classify_role(
    tokens: Sequence[Token],
    *,
    has_subtype: bool,
    active_danger: bool,
    displaced: bool,
    has_place_or_time: bool,
    ends_with_question: bool,
    lexicon: Lexicon | None = None,
) -> LineRole:
    """Роль реплики по эвристикам, сверху вниз — первая подошедшая."""
    lex = lexicon or load_lexicon()
    roles = lex.roles
    has_break = bool(lex.break_markers.find_all(tokens))
    if active_danger:
        return "new_problem"
    if roles["out_of_scope"].find_all(tokens):
        return "out_of_scope"
    if roles["announcement"].find_all(tokens):
        return "announcement"
    if lex.planned_duration.find_all(tokens) and any(
        token.text.startswith("отключ") for token in tokens
    ):
        return "announcement"
    if roles["status_question"].find_all(tokens):
        return "status_question"
    if ends_with_question and has_subtype and not has_break and not displaced:
        return "status_question"
    if roles["resolved_claim"].find_all(tokens):
        return "resolved_claim"
    if roles["objection"].find_all(tokens):
        return "objection"
    if displaced:
        return "discussion"
    if not has_subtype and lex.hypothesis.find_all(tokens):
        return "discussion"
    if roles["me_too"].find_all(tokens):
        return "me_too"
    if not has_subtype and not has_break and lex.more_info.find_all(tokens):
        return "more_info"
    if roles["chatter"].find_all(tokens):
        return "chatter"
    if has_subtype or has_break:
        return "new_problem"
    return "chatter"


def passes_recall_gate(text: str, lexicon: Lexicon | None = None) -> bool:
    """Гейт E0b: ИЛИ независимых дешёвых признаков.

    Словарь подтипов, глаголы поломки, маркеры жалобы, конструкции
    отсутствия и лексикон опасности — любой из них пропускает реплику дальше.
    """
    from domsignal.ai.rules.danger import screen_message_for_danger
    from domsignal.ai.taxonomy import load_taxonomy

    lex = lexicon or load_lexicon()
    tokens = tokenize(normalize(text).text)
    if load_taxonomy().match(tokens, lex.negation_tokens):
        return True
    for stems in (lex.break_markers, lex.complaint_markers, lex.absence_markers):
        if stems.find_all(tokens):
            return True
    return any(not hit.negated for hit in screen_message_for_danger(text))
