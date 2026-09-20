"""Лёгкая нормализация текста с сохранением позиций в оригинале.

Цитата в результате анализа обязана быть точной подстрокой исходной реплики,
поэтому нормализация хранит для каждого символа диапазон исходных символов:
совпадение правила в нормализованном тексте всегда превращается обратно в
дословную цитату.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LATIN_WORD = re.compile(r"[a-z]+")

#: Минимальный словарь транслита живых формулировок домовых чатов.
TRANSLIT: dict[str, str] = {
    "dver": "дверь",
    "dom": "дом",
    "doma": "дома",
    "domofon": "домофон",
    "dym": "дым",
    "etazh": "этаж",
    "gaz": "газ",
    "goryachey": "горячей",
    "lampa": "лампа",
    "lift": "лифт",
    "musor": "мусор",
    "ne": "не",
    "net": "нет",
    "podezd": "подъезд",
    "podyezd": "подъезд",
    "podvale": "подвале",
    "rabotaet": "работает",
    "svet": "свет",
    "techet": "течет",
    "trub": "труб",
    "voda": "вода",
    "vody": "воды",
    "voobshe": "вообще",
    "zastryal": "застрял",
}


@dataclass(frozen=True)
class NormalizedText:
    """Нормализованный текст и отображение его символов в оригинал."""

    original: str
    text: str
    offsets: tuple[tuple[int, int], ...]

    def quote(self, start: int, end: int) -> str:
        """Дословная подстрока оригинала для диапазона нормализованного текста."""
        if not self.offsets or start >= end:
            return ""
        start = max(0, min(start, len(self.offsets) - 1))
        end = max(start + 1, min(end, len(self.offsets)))
        return self.original[self.offsets[start][0] : self.offsets[end - 1][1]]


def _fold(char: str) -> str:
    folded = char.lower()
    return "е" if folded == "ё" else folded


def _base_pass(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            end = index
            while end < length and text[end].isspace():
                end += 1
            if chars and chars[-1] != " ":
                chars.append(" ")
                offsets.append((index, end))
            index = end
            continue
        folded = _fold(char)
        end = index + 1
        while end < length and _fold(text[end]) == folded:
            end += 1
        if end - index >= 3:
            chars.append(folded)
            offsets.append((index, end))
            index = end
            continue
        chars.append(folded)
        offsets.append((index, index + 1))
        index += 1
    while chars and chars[-1] == " ":
        chars.pop()
        offsets.pop()
    return chars, offsets


def normalize(text: str) -> NormalizedText:
    """Регистр, ё→е, пробелы, повторы букв и транслит с картой позиций."""
    chars, offsets = _base_pass(text)
    base = "".join(chars)
    if not any("a" <= char <= "z" for char in base):
        return NormalizedText(original=text, text=base, offsets=tuple(offsets))
    out_chars: list[str] = []
    out_offsets: list[tuple[int, int]] = []
    cursor = 0
    for match in _LATIN_WORD.finditer(base):
        replacement = TRANSLIT.get(match.group(0))
        if replacement is None:
            continue
        out_chars.extend(chars[cursor : match.start()])
        out_offsets.extend(offsets[cursor : match.start()])
        span = (offsets[match.start()][0], offsets[match.end() - 1][1])
        out_chars.extend(replacement)
        out_offsets.extend([span] * len(replacement))
        cursor = match.end()
    out_chars.extend(chars[cursor:])
    out_offsets.extend(offsets[cursor:])
    return NormalizedText(original=text, text="".join(out_chars), offsets=tuple(out_offsets))


def light_normalize(text: str) -> str:
    """Одинаковая лёгкая нормализация обеих сторон при сравнении цитат."""
    return " ".join("".join(_fold(char) for char in text).split())


def contains_quote(haystack: str, quote: str) -> bool:
    """Цитата — подстрока реплики после одинаковой лёгкой нормализации."""
    if not quote.strip():
        return False
    return light_normalize(quote) in light_normalize(haystack)
