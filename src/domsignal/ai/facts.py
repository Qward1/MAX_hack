"""Guard `no_new_facts`: детерминированная проверка текста модели.

Модели разрешено привести разговорное описание к деловому тексту и объединить
подтверждённые наблюдения ветки. Запрещено добавлять нормы, организации,
сроки, обязательства и любые факты, которых нет в исходных репликах.

Проверка не использует модель и не обращается в сеть.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from domsignal.ai.normalize import light_normalize

ViolationKind = Literal[
    "number",
    "date_or_time",
    "entrance_or_floor",
    "proper_name",
    "organization",
    "obligation",
]

_WORD = re.compile(r"[а-яa-z0-9]+")
_SENTENCE_SPLIT = re.compile(r"[.!?]\s+|\n+")
_DIGITS = re.compile(r"\d+")

_NUMBER_WORDS: dict[str, str] = {
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
    "один": "1",
    "одна": "1",
    "два": "2",
    "две": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
    "десять": "10",
}
_ORDINAL = re.compile(
    r"^(?:перв|втор|трет|четверт|пят|шест|седьм|восьм|девят|десят)"
    r"(?:ый|ой|ая|ое|ые|ого|ему|ому|ом|ым|ых|ими|ий|его|ем|им|о|а|у|е|и|ь)?$"
)

_MONTHS = (
    "январ", "феврал", "март", "апрел", "мая", "май", "июн", "июл", "август",
    "сентябр", "октябр", "ноябр", "декабр",
)
_WEEKDAYS = (
    "понедельник", "вторник", "среду", "среда", "четверг", "пятниц", "суббот",
    "воскресень",
)
_TIME = re.compile(r"\b\d{1,2}[:.]\d{2}\b")

_OBLIGATION = (
    "статья",
    "статьи",
    "ст.",
    "закон",
    "постановлени",
    "жк рф",
    "гк рф",
    "обязан",
    "обязател",
    "в течение",
    "срок",
    "норматив",
    "регламент",
    "предписан",
    "штраф",
)
_ORGANIZATION = ("ооо", "оао", "зао", "ао", "гуп", "муп", "администраци", "управа", "ук",
                 "жилинспекц", "прокуратур")
_ORGANIZATION_RE = tuple(
    (phrase, re.compile(rf"(?<![а-яa-z]){re.escape(phrase)}(?![а-яa-z])"))
    for phrase in _ORGANIZATION
)
_PLACE_HINTS = ("подъезд", "подьезд", "этаж", "квартир", "парадн")


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ViolationKind
    value: str


class NoNewFactsResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    violations: tuple[Violation, ...] = ()


def _source_index(sources: Sequence[str]) -> tuple[str, set[str]]:
    text = " ".join(light_normalize(source) for source in sources)
    return text, set(_WORD.findall(text))


def _number_forms(token: str) -> set[str]:
    forms = {token}
    if token.isdigit():
        stripped = token.lstrip("0") or token
        forms.add(stripped)
        for stem, digit in _NUMBER_WORDS.items():
            if digit == stripped:
                forms.add(stem)
        return forms
    for stem, digit in _NUMBER_WORDS.items():
        if token.startswith(stem):
            forms.add(digit)
            forms.add(stem)
    return forms


def _known_number(token: str, source_words: set[str]) -> bool:
    for form in _number_forms(token):
        if form.isdigit():
            if form in source_words:
                return True
        elif any(word.startswith(form) for word in source_words):
            return True
    return False


def check_no_new_facts(candidate: str, sources: Sequence[str]) -> NoNewFactsResult:
    """Есть ли в тексте факты, которых нет в исходных репликах."""
    source_text, source_words = _source_index(sources)
    normalized = light_normalize(candidate)
    violations: list[Violation] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: ViolationKind, value: str) -> None:
        key = (kind, value)
        if key not in seen:
            seen.add(key)
            violations.append(Violation(kind=kind, value=value))

    for phrase in _OBLIGATION:
        if phrase in normalized:
            add("obligation", phrase.strip())
    for phrase, pattern in _ORGANIZATION_RE:
        if pattern.search(normalized) and not pattern.search(source_text):
            add("organization", phrase)

    for match in _TIME.finditer(normalized):
        if match.group(0) not in source_text:
            add("date_or_time", match.group(0))
    for group in (_MONTHS, _WEEKDAYS):
        for stem in group:
            if stem in normalized and stem not in source_text:
                add("date_or_time", stem)

    tokens = _WORD.findall(normalized)
    for index, token in enumerate(tokens):
        is_digit = bool(_DIGITS.fullmatch(token))
        if not is_digit and not _ORDINAL.match(token):
            continue
        if _known_number(token, source_words):
            continue
        neighbours = " ".join(tokens[max(0, index - 1) : index + 3])
        kind: ViolationKind = (
            "entrance_or_floor"
            if any(hint in neighbours for hint in _PLACE_HINTS)
            else "number"
        )
        add(kind, token)

    for sentence in _SENTENCE_SPLIT.split(candidate):
        words = sentence.split()
        for word in words[1:]:
            stripped = word.strip("«»\"'(),.;:!?—-")
            if len(stripped) < 2 or not stripped[:1].isalpha() or not stripped[:1].isupper():
                continue
            if stripped.isupper() and len(stripped) <= 4:
                continue
            if light_normalize(stripped) in source_words:
                continue
            add("proper_name", stripped)

    return NoNewFactsResult(ok=not violations, violations=tuple(violations))
