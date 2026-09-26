"""Explicit risk cues used with the statistical safety score.

This is intentionally a narrow local screen, not a legal or emergency-service decision.
"""
from __future__ import annotations

import re

RISK = re.compile(
    r"газ|дым|гар[ьи]|пожар|возгор|искр|замыкан|коротит|удар\w* током|"
    r"застр|не могу выйти|не можем выйти|заперт|залив|затоп|прорвал|"
    r"ль[её]т|хлещ|теч[её]т|капает|протеч|сигнализац",
    re.I,
)
DIRECT = (
    ("gas", re.compile(r"пахн\w* газом|запах газа|утечк\w* газа", re.I)),
    ("fire", re.compile(r"дым\w* в (?:подъезд|доме)|горит (?:подъезд|дом|квартир)|пожар в", re.I)),
    ("trapped", re.compile(r"застр\w* в лифт|в лифт\w* застр|не (?:могу|можем) выйти из лифт", re.I)),
    ("electric", re.compile(r"искр\w* (?:щит|провод|розет)|замыкан\w* в щит", re.I)),
    ("flood", re.compile(r"вод\w* (?:ль[её]тся|хлещет|прибывает)|затаплива\w* (?:подъезд|квартир)", re.I)),
)
NEGATED = re.compile(
    r"не пахнет газом|нет запаха газа|дыма нет|не горит|никто не застрял|"
    r"пожара нет|не затаплива|не теч[её]т|не ль[её]тся|"
    r"учени[яеи]|тренировк|планов\w* проверк|"
    r"в соседнем доме|в другом доме|в новостях|вчера|раньше|уже устранил",
    re.I,
)


def risk_cue(text: str) -> bool:
    return bool(RISK.search(text))


def direct_rule(text: str) -> str | None:
    if NEGATED.search(text):
        return None
    for kind, pattern in DIRECT:
        if pattern.search(text):
            return kind
    return None


def emergency_from_score(text: str, score: float, threshold: float) -> tuple[bool, str]:
    direct = direct_rule(text)
    if direct is not None:
        return True, f"rule:{direct}"
    if score >= threshold and risk_cue(text):
        return True, "model_with_cue"
    return False, "none"
