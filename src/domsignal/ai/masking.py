"""Маскирование персональных данных перед внешним вызовом.

Маскирование выполняется только на пути к провайдеру. Правила опасности и
извлечение места работают по исходному тексту (иначе признак может оказаться
за границей замены), а цитаты в результате остаются подстроками оригинала.

Номера подъездов и этажей не маскируются: без них сигнал теряет смысл.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+", re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_PHONE = re.compile(
    r"(?<!\d)(?:\+?7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"
)
_CARD = re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)")
_APARTMENT = re.compile(r"(?<![а-яa-z])(кв|квартир[а-я]*)\.?\s*№?\s*\d{1,4}", re.IGNORECASE)
_PLATE = re.compile(
    r"(?<![а-яa-z])[авекмнорстухabekmhopctyx]\s?\d{3}\s?[авекмнорстухabekmhopctyx]{2}\s?\d{2,3}"
    r"(?![а-яa-z0-9])",
    re.IGNORECASE,
)
_LONG_NUMBER = re.compile(r"(?<!\d)\d{6,}(?!\d)")

_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_EMAIL, "[почта]"),
    (_URL, "[ссылка]"),
    (_CARD, "[карта]"),
    (_PHONE, "[телефон]"),
    (_APARTMENT, "[квартира]"),
    (_PLATE, "[госномер]"),
    (_LONG_NUMBER, "[номер]"),
)


def mask_text(text: str) -> str:
    """Замаскированный текст для внешнего запроса."""
    masked = text
    for pattern, replacement in _REPLACEMENTS:
        masked = pattern.sub(replacement, masked)
    return masked


def author_alias(index: int) -> str:
    """Псевдоним автора по порядку первого появления в окне: A, B, … Z, AA."""
    if index < 0:
        raise ValueError("author index must be non-negative")
    alias = ""
    current = index
    while True:
        alias = chr(ord("A") + current % 26) + alias
        current = current // 26 - 1
        if current < 0:
            return alias
