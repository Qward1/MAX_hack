"""P6b: голос бота в чате — только высокоточные срабатывания правил.

Любое срабатывание без отрицания по-прежнему даёт оповещение оператора;
памятка в домовой чат (`chat_memo_hits`) — только высокоточная формулировка
настоящего времени о текущей ситуации. Ловушки из отчёта P6 (учения,
благодарность после устранения, «горит» как «светит», переносное значение)
правила больше не принимают за опасность. Настройка — только на `d5_dev` и
dev D3; D5 и holdout D3 — контроль.
"""

from __future__ import annotations

import pathlib
from datetime import timedelta

import pytest

from domsignal.ai import WindowAnalyzer, WindowInput, WindowLine, chat_memo_hits
from domsignal.ai import screen_message_for_danger as screen
from evaluation.guard import load_allowed_jsonl
from evaluation.metrics import BASE_TIME


def active(text: str) -> set[str]:
    return {hit.kind for hit in screen(text) if not hit.negated}


def memo(text: str) -> set[str]:
    return {hit.kind for hit in chat_memo_hits(screen(text))}


# ------------------------------------------------ право на памятку в чат


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Пахнет газом во втором подъезде", "gas"),
        ("запах газа на лестнице", "gas"),
        ("в подъезде сильно воняет газом", "gas"),
        ("горит квартира на пятом этаже", "smoke_fire"),
        ("пожар в подвале!", "smoke_fire"),
        ("дым из подвала валит", "smoke_fire"),
        ("задымление в подъезде, ничего не видно", "smoke_fire"),
        ("щиток на площадке горит", "smoke_fire"),
        ("искрит щиток на третьем этаже", "electric"),
        ("застряли в лифте во втором подъезде", "person_trapped"),
        ("ребенок застрял в лифте", "person_trapped"),
        ("обрушился балкон на четвёртом", "structural"),
    ],
)
def test_high_precision_present_tense_gives_a_memo(text: str, kind: str) -> None:
    assert kind in memo(text)


@pytest.mark.parametrize(
    "text,kind",
    [
        # Шаг 5 живого прогона: новый вид, оповещение и маршрут 112 — без памятки.
        ("и дымом тоже тянет", "smoke_fire"),
        ("да, горит", "smoke_fire"),
        ("если пахнет газом — куда звонить, в ук или 104?", "gas"),
        ("а что делать если застрял в лифте ночью?", "person_trapped"),
        ("вчера был пожар в подвале", "smoke_fire"),
        ("да, видела дым из окна", "smoke_fire"),
        ("это сверху заливает", "flooding"),
        ("провод оборвали, когда деревья пилили", "electric"),
        ("соседка не может выйти, дверь заклинило", "person_trapped"),
        ("у нас во дворе песочница развалилась", "structural"),
        ("гарью тянет", "smoke_fire"),
    ],
)
def test_operator_is_alerted_but_the_bot_stays_silent(text: str, kind: str) -> None:
    assert kind in active(text), "оповещение оператора остаётся"
    assert kind not in memo(text), "памятки в чат нет"


def test_displaced_danger_has_no_memo() -> None:
    hits = screen("в соседнем доме пахнет газом")
    assert hits and all(hit.displaced for hit in hits)
    assert not chat_memo_hits(hits)
    assert all(hit.displaced for hit in screen("дым у соседнего дома"))


def test_memo_filter_checks_every_condition() -> None:
    hit = screen("Пахнет газом во втором подъезде")[0]
    assert hit.chat_memo_eligible and chat_memo_hits([hit]) == [hit]
    assert not chat_memo_hits([hit.model_copy(update={"negated": True})])
    assert not chat_memo_hits([hit.model_copy(update={"displaced": True})])
    assert not chat_memo_hits([hit.model_copy(update={"chat_memo_eligible": False})])


# ------------------------------------------------------ семейства ловушек


@pytest.mark.parametrize(
    "text",
    [
        # Шаг 1 живого прогона.
        "Учебная пожарная тревога сегодня в 14:00, не пугайтесь",
        "завтра учения по пожарной безопасности, во дворе будет дым-машина",
        "управляйка пишет: 25го тренировка эвакуации при пожаре",
        "сегодня проверяют пожарную сигнализацию в подъездах, может пищать",
        "учения мчс, возможен запах дыма во дворе",
        "это была тренировка, пожарные уже уехали",
    ],
)
def test_drills_are_not_a_danger(text: str) -> None:
    hits = screen(text)
    assert not [hit for hit in hits if not hit.negated]
    assert not chat_memo_hits(hits)


@pytest.mark.parametrize(
    "text",
    [
        # Шаг 2 живого прогона.
        "Спасибо пожарным, приехали за 10 минут",
        "огромное спасибо пожарным, приехали минут через 7",
        "потушили всё, в подвале только запах гари остался",
        "газовики приезжали, утечку устранили, можно выдохнуть",
        "благодарим мчс за оперативность при вчерашнем пожаре",
        "пожар в 3 подъезде ликвидировали, всем спасибо кто помогал",
    ],
)
def test_thanks_and_reports_after_the_fix_are_not_a_danger(text: str) -> None:
    hits = screen(text)
    assert not [hit for hit in hits if not hit.negated]
    assert not chat_memo_hits(hits)


@pytest.mark.parametrize(
    "text",
    [
        "гирлянду на ёлке во дворе повесили, горит красиво",
        "фонари во дворе горят до обеда, деньги на ветер",
        "на 6 этаже лампочка горит круглые сутки",
        "огоньки на ёлке у подъезда",
    ],
)
def test_light_that_is_on_is_not_a_fire(text: str) -> None:
    assert "smoke_fire" not in active(text)


@pytest.mark.parametrize(
    "text",
    [
        "у меня дедлайн горит, кто может завтра принять посылку?",
        "горят путёвки в турцию, если кому надо пишите в лс",
        "концерт во дворе вчера был просто огонь",
        "на работе пожар, раньше 10 не вернусь",
        "чат сегодня горит",
        "у меня сроки по отчёту горят",
        "у меня уже душа горит от этих платёжек",
    ],
)
def test_figurative_burning_is_not_a_fire(text: str) -> None:
    assert "smoke_fire" not in active(text)


# ------------------------------- настоящая опасность не теряется


@pytest.mark.parametrize(
    "text,kind",
    [
        ("это не учения!! задымление в подъезде", "smoke_fire"),
        ("спасибо что написали, у меня тоже газом пахнет, 2 подъезд", "gas"),
        ("потушили, но в подвале опять горит", "smoke_fire"),
        ("газовики приезжали, утечку устранили, а газом пахнет до сих пор", "gas"),
        ("газа нет, но дымом пахнет в подъезде", "smoke_fire"),
        ("пахнет газом, не знаю откуда", "gas"),
        ("соседка не может выйти, дверь заклинило", "person_trapped"),
        ("проводка горит!", "smoke_fire"),
        ("в щитке горит проводка, свет мигает", "smoke_fire"),
        ("горит машина у подъезда, фонари рядом", "smoke_fire"),
    ],
)
def test_real_danger_survives_the_trap_markers(text: str, kind: str) -> None:
    assert kind in active(text)


def test_negation_does_not_cross_a_clause_but_still_works_inside_it() -> None:
    assert active("газом не пахнет, всё проверили") == set()
    assert active("нет никакого дыма") == set()
    assert active("дыма нет, это сосед шашлык жарит") == set()
    assert "smoke_fire" in active("газа нет, но дымом тянет")


# ---------------------------------- живые шаги P6b на правилах приёма


def test_live_steps_on_intake_rules() -> None:
    assert not active("Учебная пожарная тревога сегодня в 14:00, не пугайтесь")
    assert not active("Спасибо пожарным, приехали за 10 минут")
    lighting = screen("В третьем подъезде опять не горит свет на лестнице")
    assert lighting and all(hit.negated for hit in lighting)
    assert memo("Пахнет газом во втором подъезде") == {"gas"}
    assert active("и дымом тоже тянет") == {"smoke_fire"}
    assert not memo("и дымом тоже тянет")
    for text in ("Там кто-нибудь внутри?", "Да, женщина стучит", "Двери вообще не открываются"):
        assert not memo(text), "смысловая опасность — без памятки"


# ------------------------------------------- набор настройки d5_dev


D5_DEV = pathlib.Path("datasets/synthetic/d5_dev.v1.jsonl")


def test_d5_dev_shape() -> None:
    rows = load_allowed_jsonl(D5_DEV)
    groups = [row["group"] for row in rows]
    assert (groups.count("danger"), groups.count("trap"), groups.count("contextual")) == (
        30,
        40,
        10,
    )
    assert {row["family"] for row in rows if row["group"] == "trap"} >= {
        "drill",
        "resolved",
        "light",
        "figurative",
    }


async def test_d5_dev_floors() -> None:
    """Порог регрессии на наборе настройки (внутривыборочный, не измерение)."""
    rows = load_allowed_jsonl(D5_DEV)
    trap_memos: list[str] = []
    danger_found = 0
    for row in rows:
        lines = tuple(
            WindowLine(
                line_id=f"{row['id']}-{item['n']}",
                author_ref=item["author"],
                text=item["text"],
                sent_at=BASE_TIME + timedelta(seconds=item["offset_s"]),
            )
            for item in row["lines"]
        )
        if row["group"] == "trap":
            if any(chat_memo_hits(screen(line.text)) for line in lines):
                trap_memos.append(row["id"])
        elif row["group"] == "danger":
            analysis = await WindowAnalyzer().analyze(
                WindowInput(channel="group_passive", lines=lines)
            )
            danger_found += any(signal.emergency.is_emergency for signal in analysis.signals)
    assert trap_memos == []
    assert danger_found >= 24
