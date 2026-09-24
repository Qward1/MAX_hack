"""P6c §2: прошлое время — памятки в чат нет, оповещение оператору остаётся.

На контроле D5 осталась памятка на реплику о прошлом («в прошлом месяце
искрило»). Семейство «прошлое → памятки нет» заявлено в P6b; это пробел
покрытия общего правила: (1) прошедшая форма самого предиката опасности
(«искрило», «дымило», «полыхало») не считается формулировкой настоящего
времени; (2) маркеры прошлого — «в прошлом месяце», «как-то раз», «однажды»,
«когда-то», «N лет/месяцев/недель/дней назад». «Давно» и «тогда» маркерами
не стали: «давно пахнет газом» — это сейчас. Настройка — на `d5_dev`,
контроль D5 не перезапускался.
"""

from __future__ import annotations

import pytest

from domsignal.ai import chat_memo_hits
from domsignal.ai import screen_message_for_danger as screen


def active(text: str) -> set[str]:
    return {hit.kind for hit in screen(text) if not hit.negated}


def memo(text: str) -> set[str]:
    return {hit.kind for hit in chat_memo_hits(screen(text))}


@pytest.mark.parametrize(
    "text,kind",
    [
        # Живой шаг P6c — реплика жителя A.
        ("В прошлом месяце в щитке искрило, сейчас всё нормально", "electric"),
        ("на прошлой неделе дымило из подвала", "smoke_fire"),
        ("в позапрошлом году на балконе у соседей полыхало", "smoke_fire"),
        ("однажды застряли в лифте во 2 подъезде", "person_trapped"),
        ("лет 5 назад рухнул козырёк подъезда", "structural"),
        ("как-то раз из щитка искры летели", "electric"),
        ("когда-то тут пожар в подвале тушили", "smoke_fire"),
        ("месяца три назад дымило в мусоропроводе", "smoke_fire"),
        ("тогда в щитке искрило, электрик всё поменял", "electric"),
        ("давно, в тот раз, щиток искрил на 3 этаже", "electric"),
    ],
)
def test_past_danger_alerts_the_operator_but_the_bot_stays_silent(text: str, kind: str) -> None:
    assert kind in active(text), "оповещение оператору остаётся"
    assert kind not in memo(text), "памятки в чат нет"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("в щитке на площадке искрит прямо сейчас", "electric"),
        ("из подвала дым валит", "smoke_fire"),
        ("минут 5 назад запахло газом, сейчас сильно пахнет в подъезде", "gas"),
        ("уже полчаса прошло, а в подвале всё полыхает", "smoke_fire"),
        ("давно пахнет газом на лестнице, сейчас ещё сильнее", "gas"),
        ("ну тогда вызываем аварийку, в щитке искрит", "electric"),
        ("из розетки искры сыплются, выключили автомат", "electric"),
        ("застряли в лифте во 2 подъезде, уже минут 20 сидим", "person_trapped"),
        ("обрушился балкон на четвёртом", "structural"),
        ("щиток на площадке горит", "smoke_fire"),
    ],
)
def test_present_danger_next_to_them_keeps_the_memo(text: str, kind: str) -> None:
    assert kind in memo(text)
