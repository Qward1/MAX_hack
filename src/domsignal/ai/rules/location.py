"""Место и время из реплики: подъезд, этаж, «с какого времени», территория.

Каждое значение возвращается только вместе с дословной цитатой из той же
реплики. `location_scope` — предварительное наблюдение о территории, а не
утверждение об ответственности.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from domsignal.ai.contracts import Evidence, LocationEvidence
from domsignal.ai.matching import Token
from domsignal.ai.normalize import NormalizedText
from domsignal.ai.rules.lexicon import Lexicon, load_lexicon

_NUM_WORDS = {
    "перв": "1",
    "втор": "2",
    "трет": "3",
    "четверт": "4",
    "пят": "5",
    "шест": "6",
    "седьм": "7",
    "восьм": "8",
    "девят": "9",
    "десят": "10",
}
_ORDINAL = "|".join(_NUM_WORDS)

_ENTRANCE_PATTERNS = (
    re.compile(r"(\d{1,2})\s*-?\s*(?:м|й|ом|ем|ый|ой|го)?\s*(?:подъезд|подьезд|под\.|парадн)"),
    re.compile(r"(?:подъезд|подьезд|парадн)[а-я]*\s*№?\s*(\d{1,2})"),
    re.compile(r"(?<![а-я])п\.\s*(\d{1,2})"),
    re.compile(rf"({_ORDINAL})[а-я]*\s+(?:подъезд|подьезд|парадн)"),
    re.compile(rf"(?:^|\s)в[о]?\s+({_ORDINAL})[а-я]*\s*$"),
)

_FLOOR_PATTERNS = (
    re.compile(r"между\s+(\d{1,2})\s*и\s*(\d{1,2})"),
    re.compile(r"(\d{1,2})\s*-?\s*(?:м|й|ом|ем|ый|ой|го)?\s*этаж"),
    re.compile(r"этаж[а-я]*\s*№?\s*(\d{1,2})"),
    re.compile(rf"на\s+({_ORDINAL})[а-я]*\s+этаж"),
)

_SINCE_PATTERNS = (
    re.compile(r"с\s+(?:самого\s+)?(утра|вечера|обеда|ночи|выходных|понедельника|пятницы)"),
    re.compile(rf"({_ORDINAL})[а-я]*\s+(?:день|сутки|суток|неделю|недели|месяц)"),
    re.compile(r"(?:уже|вот)\s+(\d{1,2}\s*(?:день|дня|дней|недел[а-я]*|месяц[а-я]*))"),
    re.compile(r"(?:уже|вот)\s+(неделю|месяц|сутки|полгода)"),
    re.compile(r"(\d{1,2})\s*(?:день|дня|дней|сутки|суток)\s+(?:подряд|уже|как)"),
    re.compile(r"(?<![а-я])(со\s+вчера|с\s+вчерашнего\s+дня|вторые\s+сутки|неделю)(?![а-я])"),
)


@dataclass(frozen=True)
class PlaceTime:
    entrance: Evidence | None = None
    floor: Evidence | None = None
    since: Evidence | None = None
    scope: LocationEvidence = LocationEvidence(value="unknown")

    @property
    def has_any(self) -> bool:
        return bool(self.entrance or self.floor or self.since)


def _evidence(
    normalized: NormalizedText, match: re.Match[str], value: str, line_id: str
) -> Evidence:
    return Evidence(
        value=value,
        quote=normalized.quote(match.start(), match.end()),
        line_id=line_id,
    )


def _digits_or_word(raw: str) -> str:
    if raw.isdigit():
        return raw.lstrip("0") or raw
    for stem, digit in _NUM_WORDS.items():
        if raw.startswith(stem):
            return digit
    return raw


def find_entrance(normalized: NormalizedText, line_id: str) -> Evidence | None:
    for pattern in _ENTRANCE_PATTERNS:
        match = pattern.search(normalized.text)
        if match:
            return _evidence(normalized, match, _digits_or_word(match.group(1)), line_id)
    return None


def find_floor(normalized: NormalizedText, line_id: str) -> Evidence | None:
    for pattern in _FLOOR_PATTERNS:
        match = pattern.search(normalized.text)
        if not match:
            continue
        if match.re.groups == 2:
            value = f"между {match.group(1)} и {match.group(2)}"
        else:
            value = _digits_or_word(match.group(1))
        return _evidence(normalized, match, value, line_id)
    return None


def find_since(normalized: NormalizedText, line_id: str) -> Evidence | None:
    for pattern in _SINCE_PATTERNS:
        match = pattern.search(normalized.text)
        if match:
            return _evidence(normalized, match, match.group(0).strip(), line_id)
    return None


def find_scope(
    normalized: NormalizedText,
    tokens: Sequence[Token],
    line_id: str,
    lexicon: Lexicon | None = None,
) -> LocationEvidence:
    """Предварительная территория с цитатой; без цитаты — `unknown`."""
    lex = lexicon or load_lexicon()
    for value, stems in lex.location_scope:
        found = stems.find_all(tokens)
        if not found:
            continue
        first = min(found, key=lambda item: item.first_token)
        return LocationEvidence(
            value=value,
            quote=normalized.quote(first.start, first.end),
            line_id=line_id,
        )
    return LocationEvidence(value="unknown")


def extract(
    normalized: NormalizedText,
    tokens: Sequence[Token],
    line_id: str,
    lexicon: Lexicon | None = None,
) -> PlaceTime:
    return PlaceTime(
        entrance=find_entrance(normalized, line_id),
        floor=find_floor(normalized, line_id),
        since=find_since(normalized, line_id),
        scope=find_scope(normalized, tokens, line_id, lexicon),
    )
