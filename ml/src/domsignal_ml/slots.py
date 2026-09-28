"""Conservative extraction of explicit entrance and floor mentions."""
from __future__ import annotations

import re

ENTRANCE = (
    re.compile(r"(?<!\d)([1-4])\s*[-–]?\s*(?:й|ый|ой|го|м)?\s*(?:подъезд|подьезд|под\.|парадн)", re.I),
    re.compile(r"(?:подъезд|подьезд|парадн)\w*\s*№?\s*([1-4])(?!\d)", re.I),
)
ENTRANCE_WORD = re.compile(r"(?<![а-я])(перв\w*|втор\w*|трет\w*|четвер\w*)\s+(?:подъезд|подьезд)", re.I)
WORD_NUMBERS = {"перв": 1, "втор": 2, "трет": 3, "четвер": 4}
FLOOR = (
    re.compile(r"(?<!\d)([1-9]|1\d|2[0-6])\s*[-–]?\s*(?:й|ый|ой|го|м)?\s*(?:этаж|эт\.)", re.I),
    re.compile(r"(?:этаж|эт\.)\w*\s*№?\s*([1-9]|1\d|2[0-6])(?!\d)", re.I),
)


def slots(text: str) -> dict[str, int | None]:
    out: dict[str, int | None] = {"entrance": None, "floor": None}
    for name, patterns in (("entrance", ENTRANCE), ("floor", FLOOR)):
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                out[name] = int(match.group(1))
                break
    if out["entrance"] is None:
        match = ENTRANCE_WORD.search(text)
        if match:
            for stem, value in WORD_NUMBERS.items():
                if match.group(1).lower().startswith(stem):
                    out["entrance"] = value
                    break
    return out
