"""D6 (MEMO-PRECISION-2026-09-28): ложные памятки на семействах реальных окон D5.

Найдено на реальных окнах (разметка агентом), исправлено общими правилами на
наборе настройки `d5_dev`, контроль не перезапускался. Фразы — синтетика той
же формы, реальные тексты не копируются. Оповещение оператора при настоящей
опасности и Fusion «ИЛИ» не ослаблены: каждая ловушка идёт в паре с
настоящей опасностью рядом.
"""

from __future__ import annotations

import pathlib

import pytest

from domsignal.ai import chat_memo_hits
from domsignal.ai import screen_message_for_danger as screen
from evaluation.guard import load_allowed_jsonl


def active(text: str) -> set[str]:
    return {hit.kind for hit in screen(text) if not hit.negated}


def memo(text: str) -> set[str]:
    return {hit.kind for hit in chat_memo_hits(screen(text))}


@pytest.mark.parametrize(
    "text",
    [
        "опять кто-то курит в подъезде, дым на весь 3 этаж",
        "соседи снизу курят на балконе, сигаретный дым прямо в окно",
        "не курите пожалуйста на лестнице, табачный дым тянет в квартиры",
        "курильщики на площадке достали, весь подъезд в дыму",
        "сосед курит в квартире, дым через вытяжку к нам",
    ],
)
def test_tobacco_smoke_is_not_a_fire(text: str) -> None:
    assert "smoke_fire" not in active(text)
    assert not memo(text)


@pytest.mark.parametrize(
    "text",
    [
        "сосед уснул с сигаретой, из квартиры дым и горит диван!",
        "окурок бросили в мусоропровод, горит, дым на весь подъезд",
        "курили в подвале, теперь пожар в подвале, дым валит",
        "дым из квартиры 45, кто-то курил в постели, стучим — не открывают",
        "в подъезде дым и гарь, это не сигареты, что-то горит в подвале",
    ],
)
def test_fire_next_to_tobacco_keeps_the_memo(text: str) -> None:
    assert "smoke_fire" in memo(text)


def test_gas_with_a_smoking_warning_keeps_the_memo() -> None:
    assert "gas" in memo("пахнет газом на площадке, не курите и не включайте свет")


@pytest.mark.parametrize(
    "text",
    [
        "в доме напротив горит квартира, пожарные уже там",
        "через дорогу дым столбом, горит склад",
        "дом напротив, 3й этаж, огонь из окна, кто видит?",
        "в соседнем дворе дым, кто-то жжёт мусор",
        "в доме через дорогу пахнет газом, газовая служба уже приехала",
    ],
)
def test_another_house_alerts_the_operator_without_a_memo(text: str) -> None:
    hits = [hit for hit in screen(text) if not hit.negated]
    assert hits and all(hit.displaced for hit in hits), "оповещение остаётся, «не у нас»"
    assert not memo(text)


@pytest.mark.parametrize(
    "text,kind",
    [
        ("в соседнем подъезде горит квартира на 7 этаже!", "smoke_fire"),
        ("соседний подъезд — сильно пахнет газом, звоните 104", "gas"),
        ("из квартиры напротив лифта идёт дым, горит что-то", "smoke_fire"),
        ("в соседней квартире дым и треск, горит!", "smoke_fire"),
        ("напротив нашего дома горит машина у подъезда", "smoke_fire"),
    ],
)
def test_neighbouring_entrance_is_our_house(text: str, kind: str) -> None:
    assert kind in memo(text)


@pytest.mark.parametrize(
    "text",
    [
        "электроошейник для собаки бьёт током, кто пользовался?",
        "ошейник у соседской собаки бьёт током при лае, жалко пса",
        "от ручки двери бьёт током, свитер синтетический наверное",
        "каждый раз бьёт током от машины, статическое электричество",
        "кот бьётся током от пледа, смешно",
    ],
)
def test_harmless_shock_is_not_an_electrical_fault(text: str) -> None:
    assert "electric" not in active(text)


@pytest.mark.parametrize(
    "text",
    [
        "бьёт током от щитка в подъезде, не трогайте!",
        "из розетки искры, бьёт током, пахнет горелым",
        "от стиральной машины бьёт током и коротит розетка",
        "искрит проводка у лифта на 4 этаже",
    ],
)
def test_electrical_fault_keeps_the_memo(text: str) -> None:
    assert "electric" in memo(text)


@pytest.mark.parametrize(
    "text",
    [
        "у меня горят сроки по отчёту, завтра не смогу на собрание",
        "горит желание уже починить эту площадку",
        "в чате жара, горят все от этой новости",
        "пожарный проезд опять заставили машинами, если что — не проедут",
        "правила пожарной безопасности висят на первом этаже",
        "проверили пожарные краны, воды в них нет",
        "пожарная лестница во дворе ржавая, надо покрасить",
    ],
)
def test_figurative_and_equipment_words_are_not_a_fire(text: str) -> None:
    assert "smoke_fire" not in active(text)


@pytest.mark.parametrize(
    "text",
    [
        "когда квартиры горят, никто не думает о правилах",
        "в случае пожара выход через чердак закрыт, это нарушение",
        "при пожаре звоните 112, памятка висит на двери",
        "на случай пожара проверьте огнетушители в квартире",
    ],
)
def test_general_statements_give_no_memo(text: str) -> None:
    assert not memo(text)


@pytest.mark.parametrize(
    "text,kind",
    [
        ("когда уже приедут? горит подвал, дым в квартирах", "smoke_fire"),
        ("в случае чего — у нас сейчас реально пахнет газом на 3 этаже", "gas"),
        ("пожарная сигнализация орёт и реально дым на 9 этаже", "smoke_fire"),
        ("задымление на лестнице, пожарный выход закрыт!", "smoke_fire"),
        ("в подвале пожар, пожарные едут", "smoke_fire"),
    ],
)
def test_real_danger_after_a_general_word_keeps_the_memo(text: str, kind: str) -> None:
    assert kind in memo(text)


def test_firefighters_arriving_still_alert_the_operator() -> None:
    assert "smoke_fire" in active("пожарные приехали, разворачивают рукав")
    assert not memo("пожарные приехали, разворачивают рукав")


def _row_facts(row: dict[str, object]) -> tuple[bool, bool]:
    alert = has_memo = False
    for line in row["lines"]:  # type: ignore[union-attr]
        hits = screen(line["text"])  # type: ignore[index]
        alert = alert or any(not hit.negated for hit in hits)
        has_memo = has_memo or bool(chat_memo_hits(hits))
    return alert, has_memo


def test_tuning_set_new_families_have_no_memo_and_no_lost_danger() -> None:
    rows = load_allowed_jsonl(pathlib.Path("datasets/synthetic/d5_dev.v1.jsonl"))
    d6 = [row for row in rows if str(row["id"]).startswith("d6-")]
    assert len(d6) >= 64
    for row in d6:
        alert, has_memo = _row_facts(row)
        if row["group"] == "trap":
            assert not has_memo, row["id"]
        else:
            assert alert, row["id"]
