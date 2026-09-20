"""Сопоставление основ с начала слова и нечёткое сравнение опечаток.

Урок эксперимента E0: подстрочный поиск основы «вод» находит её внутри
«мусоропровод», «доводчик» и «провод», поэтому здесь сравниваются только
начала слов. Нечёткое сравнение (расстояние ≤ 1, длина ≥ 4) включается
точечно для перечисленных ключевых основ — «лфит», «домофн», «мусар».
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from domsignal.ai.normalize import NormalizedText

_WORD = re.compile(r"[а-яa-z0-9]+")


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class StemMatch:
    """Совпадение основы: позиции токенов и границы в нормализованном тексте."""

    stem: str
    first_token: int
    last_token: int
    start: int
    end: int


def tokenize(text: str) -> tuple[Token, ...]:
    return tuple(
        Token(match.group(0), match.start(), match.end()) for match in _WORD.finditer(text)
    )


def within_one_edit(candidate: str, stem: str) -> bool:
    """Расстояние Дамерау — Левенштейна не больше единицы."""
    left, right = len(candidate), len(stem)
    if abs(left - right) > 1:
        return False
    if candidate == stem:
        return True
    if left == right:
        diffs = [index for index in range(left) if candidate[index] != stem[index]]
        if len(diffs) == 1:
            return True
        if len(diffs) == 2 and diffs[1] == diffs[0] + 1:
            first = diffs[0]
            return candidate[first] == stem[first + 1] and candidate[first + 1] == stem[first]
        return False
    shorter, longer = (candidate, stem) if left < right else (stem, candidate)
    index = other = 0
    skipped = False
    while index < len(shorter) and other < len(longer):
        if shorter[index] == longer[other]:
            index += 1
            other += 1
            continue
        if skipped:
            return False
        skipped = True
        other += 1
    return True


class StemSet:
    """Набор основ (возможно многословных), скомпилированный один раз."""

    __slots__ = ("_phrases", "_fuzzy")

    def __init__(self, stems: Iterable[str], fuzzy_stems: Iterable[str] = ()) -> None:
        phrases: list[tuple[str, tuple[str, ...]]] = []
        for stem in stems:
            words = tuple(match.group(0) for match in _WORD.finditer(stem.lower()))
            if words:
                phrases.append((stem, words))
        self._phrases = tuple(phrases)
        self._fuzzy = frozenset(word for word in fuzzy_stems if len(word) >= 4)

    def __bool__(self) -> bool:
        return bool(self._phrases)

    def _word_matches(self, token: str, word: str) -> bool:
        if token.startswith(word):
            return True
        if word not in self._fuzzy:
            return False
        candidate = token[: len(word)]
        if not candidate or abs(len(candidate) - len(word)) > 1:
            return False
        if candidate[0] != word[0] and candidate[1:2] != word[1:2]:
            return False
        return within_one_edit(candidate, word)

    def find_all(self, tokens: Sequence[Token]) -> list[StemMatch]:
        matches: list[StemMatch] = []
        total = len(tokens)
        for stem, words in self._phrases:
            span = len(words)
            for start in range(total - span + 1):
                if all(self._word_matches(tokens[start + offset].text, words[offset])
                       for offset in range(span)):
                    last = start + span - 1
                    matches.append(
                        StemMatch(
                            stem=stem,
                            first_token=start,
                            last_token=last,
                            start=tokens[start].start,
                            end=tokens[last].end,
                        )
                    )
        return matches

    def find_first(self, tokens: Sequence[Token]) -> StemMatch | None:
        matches = self.find_all(tokens)
        if not matches:
            return None
        return min(matches, key=lambda match: (match.first_token, -len(match.stem)))


def quote_for(normalized: NormalizedText, matches: Sequence[StemMatch]) -> str:
    """Дословная цитата, покрывающая все переданные совпадения."""
    if not matches:
        return ""
    start = min(match.start for match in matches)
    end = max(match.end for match in matches)
    return normalized.quote(start, end)
