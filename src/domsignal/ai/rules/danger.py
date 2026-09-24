"""Детерминированные правила опасности.

`screen_message_for_danger` вызывается продуктом в транзакции приёма webhook
на каждой реплике — до окна, до маскирования и до любой обрезки текста.
Поэтому функция чистая: без I/O, без сети, без чтения ресурсов, без
исключений. Лексикон намеренно живёт в коде, а не в YAML: приём сообщения не
должен зависеть от доступности файла ресурсов.

Правила отвечают только на вопрос «какой признак опасности виден в тексте».
Тексты инструкций безопасности, телефоны служб и маршруты — продуктовые
данные, их здесь нет.
"""

from __future__ import annotations

from collections.abc import Sequence

from domsignal.ai.contracts import DangerHit, DangerKind
from domsignal.ai.matching import StemMatch, StemSet, Token, tokenize
from domsignal.ai.normalize import NormalizedText, normalize

#: Максимальное расстояние между группами одного правила, в токенах.
_PROXIMITY = 8

_NEGATION = frozenset({"не", "нет", "нету", "ни", "никто", "никого", "ничего", "без"})

#: Маркеры «не у нас / не сейчас». Дублируют часть `lexicon.r1.yaml`
#: намеренно: правила опасности не читают ресурсы.
_DISPLACED = (
    "в соседнем доме",
    "соседнем доме",
    "соседнего дома",
    "соседний дом",
    "соседнем районе",
    "соседней улице",
    "в другом доме",
    "в новостях",
    "по новостям",
    "по телевизору",
    "у мамы",
    "у родителей",
    "у сестры",
    "у знакомых",
    "вчера было",
    "в прошлом году",
    "в прошлый раз",
    "месяц назад",
    "год назад",
    "в другом районе",
)

_RULES: tuple[tuple[DangerKind, tuple[tuple[str, ...], ...]], ...] = (
    (
        "gas",
        (
            ("газ", "газом", "газа", "газу"),
            ("пахнет", "пахло", "запах", "чувству", "воня", "тянет", "утечк", "травит"),
        ),
    ),
    (
        "smoke_fire",
        (
            (
                "дым",
                "дымит",
                "задымл",
                "гарь",
                "гарью",
                "гари",
                "горит",
                "горят",
                "горел",
                "пожар",
                "огон",
                "полыха",
                "тлеет",
                "чадит",
            ),
        ),
    ),
    (
        "electric",
        (("искр", "замыкан", "коротит", "током", "оплавил", "обуглил", "оголен"),),
    ),
    (
        "electric",
        (
            ("провод", "кабел", "щиток", "щитк", "щите"),
            ("оборвал", "оборван", "лежит на земле", "дымит", "оплавил", "греет"),
        ),
    ),
    (
        "person_trapped",
        (
            ("застрял", "заперт", "заблокирован", "зажало", "не может выйти", "не могу выйти"),
            (
                "лифт",
                "кабин",
                "человек",
                "ребенок",
                "ребенка",
                "женщин",
                "мужчин",
                "люди",
                "сосед",
                "бабушк",
                "внутри",
            ),
        ),
    ),
    (
        "flooding",
        (("залива", "хлещет", "прорвал", "потоп", "затопил", "фонтан", "бежит вода"),),
    ),
    (
        "structural",
        (
            (
                "обрушил",
                "обрушен",
                "рухнул",
                "обвал",
                "провалил",
                "осыпал",
                "развалил",
                "трещина в стене",
                "пошла трещина",
            ),
        ),
    ),
)

_COMPILED: tuple[tuple[DangerKind, tuple[StemSet, ...]], ...] = tuple(
    (kind, tuple(StemSet(group) for group in groups)) for kind, groups in _RULES
)
_DISPLACED_SET = StemSet(_DISPLACED)

#: «Свет горит», «лампочка горит» — не пожар (найдено на dev D3 в P6: без этого
#: правила давали критический сигнал и памятку в чат). Глагол горения
#: пропускается, если рядом осветительный объект и нет объекта возгорания.
_BURN_STEMS = frozenset({"горит", "горят", "горел"})
_LIGHT_OBJECTS = StemSet(
    (
        "свет",
        "ламп",
        "фонар",
        "индикатор",
        "кнопк",
        "табло",
        "подсветк",
        "светодиод",
        "гирлянд",
        "огоньк",
        "огонек",
        "люстр",
        "прожектор",
        "вывеск",
        "экран",
        "фары",
    )
)
_FIRE_OBJECTS = StemSet(
    (
        "проводк",
        "провод",
        "кабел",
        "щит",
        "подвал",
        "мусор",
        "балкон",
        "квартир",
        "крыш",
        "чердак",
        "машин",
        "дым",
        "огон",
        "пламя",
        "пожар",
    )
)
_LIGHT_RADIUS = 3
#: Место, где «горит» скорее пожар, чем лампа: без него осветительный объект
#: в той же реплике («гирлянду во дворе повесили, горит красиво») — не пожар.
_FIRE_PLACES = StemSet(
    (
        "подъезд",
        "этаж",
        "лестниц",
        "лифт",
        "шахт",
        "коридор",
        "тамбур",
        "холл",
        "окн",
        "гараж",
        "котельн",
        "площадк",
    )
)
#: Граница фразы: отрицание не переходит через знак препинания
#: («это не учения!! задымление в подъезде», «газа нет, но дымом пахнет»).
_CLAUSE_BREAKS = frozenset(",.!?;:…—–")

#: P6b: переносное значение — «горит дедлайн», «горят путёвки», «на работе
#: пожар», «концерт просто огонь». Слово горения рядом с таким объектом и без
#: объекта возгорания — не пожар; «огоньки» гирлянды — тоже.
_FIGURATIVE_STEMS = frozenset({"горит", "горят", "горел", "пожар", "огон"})
_FIGURATIVE_OBJECTS = StemSet(
    (
        "дедлайн",
        "срок",
        "путевк",
        "билет",
        "отчет",
        "проект",
        "план",
        "задач",
        "заказ",
        "скидк",
        "акци",
        "душа",
        "душе",
        "душу",
        "глаза",
        "щеки",
        "уши",
        "чат",
        "концерт",
        "на работе",
    )
)
_PRAISE = frozenset({"просто", "прям", "прямо", "реально", "вообще", "ваще", "чисто"})
_DIMINUTIVE_LIGHT = ("огоньк", "огонек")

#: P6b: учения и проверки оповещения — «учебная пожарная тревога»,
#: «тренировка эвакуации», «проверка сирен». Слово учений рядом с темой
#: тревоги отменяет срабатывания реплики; «это не учения» — не отменяет.
_DRILL_WORDS = StemSet(("учения", "учений", "учение", "учебн", "тренировк", "репетиц"))
_DRILL_TOPICS = StemSet(
    (
        "эвакуац",
        "тревог",
        "пожар",
        "мчс",
        "гражданск",
        "сирен",
        "оповещ",
        "сигнализац",
        "безопасност",
    )
)
_CHECK_WORDS = StemSet(("провер", "тестир", "испытан"))
_ALARM_OBJECTS = StemSet(("сирен", "сигнализац", "оповещ", "громкоговор"))

#: P6b: отчёт после устранения и благодарность службам — «потушили»,
#: «утечку устранили», «спасибо пожарным». Отменяет срабатывания реплики,
#: если в ней нет признака продолжения («но», «опять», «до сих пор»).
_RESOLVED = StemSet(
    (
        "потушил",
        "потушен",
        "затушил",
        "ликвидировал",
        "ликвидирован",
        "устранил",
        "устранен",
        "обошлось",
        "ложная тревога",
        "ложный вызов",
        "отбой тревог",
    )
)
_THANKS = StemSet(("спасибо", "благодар"))
_RESPONDERS = StemSet(
    ("пожарн", "мчс", "газовик", "газовщик", "аварийк", "аварийн", "спасател")
)
_STILL_WORDS = frozenset({"но", "опять", "снова"})
_STILL_PHRASES = StemSet(("до сих пор", "по прежнему", "все еще", "продолжа"))
_MARKER_RADIUS = 4

#: P6b, право на памятку в чат (голос бота — самый строгий уровень, v3 §5):
#: только высокоточные формулировки настоящего времени о текущей ситуации.
_GAS_WORDS = frozenset({"газ", "газом", "газа", "газу", "газе"})
_PRESENT_SMELL = ("пахнет", "запах", "воняет", "вонь", "тянет", "утечк", "травит", "чувству")
_FIRE_NOUNS = frozenset({"пожар", "пожара", "пожаре", "пожаром", "пожары"})
_PRESENT_BURN = ("горит", "горят", "полыха", "тлеет", "дымит", "дымят", "чадит")
_SMOKE = ("дым", "задымл")
_MEMO_PLACES = StemSet(
    (
        "подъезд",
        "квартир",
        "кв",
        "этаж",
        "подвал",
        "чердак",
        "крыш",
        "балкон",
        "лестниц",
        "площадк",
        "лифт",
        "шахт",
        "мусоропровод",
        "мусорк",
        "щит",
        "проводк",
        "провод",
        "кабел",
        "коридор",
        "тамбур",
        "холл",
        "окн",
        "дом",
        "двор",
        "машин",
        "гараж",
        "котельн",
    )
)
_SPARK = ("искр", "коротит", "замыкан")
_ELECTRIC_OBJECTS = StemSet(
    ("щит", "провод", "кабел", "розетк", "счетчик", "ламп", "выключател", "электр")
)
_SHOCK = StemSet(("бьет", "бьют", "бьется", "ударил", "шарахнул", "дерга"))
_LIFT = ("лифт", "кабин")
_TRAPPED = ("застрял", "заперт", "заблокирован", "зажало")
_COLLAPSE = ("обрушил", "обрушен", "рухнул", "обвал")
_BUILDING_PARTS = StemSet(
    (
        "потол",
        "стен",
        "балкон",
        "лестниц",
        "козыр",
        "перекрыт",
        "крыш",
        "подъезд",
        "плит",
        "перил",
        "крыльц",
        "фасад",
        "кладк",
        "ступен",
        "дом",
    )
)
_MEMO_RADIUS = 4
#: Гипотеза и прошлое снимают право на памятку, но не оповещение оператора.
_HYPOTHETICAL_WORDS = frozenset({"если"})
_HYPOTHETICAL_PHRASES = StemSet(
    ("на случай", "что делать", "не дай бог", "как понять", "что будет")
)
_PAST_WORDS = frozenset(
    {
        "был",
        "была",
        "было",
        "были",
        "вчера",
        "позавчера",
        "видел",
        "видела",
        "видели",
        "горело",
        "горела",
        "приезжал",
        "приезжала",
        "приезжали",
    }
)
_PAST_PHRASES = StemSet(("на прошлой неделе", "в прошлый раз"))


def _near(tokens: Sequence[Token], match: StemMatch, radius: int) -> Sequence[Token]:
    low = max(0, match.first_token - radius)
    return tokens[low : match.last_token + radius + 1]


def _fire_object_near(tokens: Sequence[Token], match: StemMatch, radius: int) -> bool:
    """Объект возгорания рядом, не считая самого совпадения («пожар» — не объект себе)."""
    low = max(0, match.first_token - radius)
    for item in _FIRE_OBJECTS.find_all(_near(tokens, match, radius)):
        first = item.first_token + low
        if not match.first_token <= first <= match.last_token:
            return True
    return False


def _is_light_on(tokens: Sequence[Token], match: StemMatch) -> bool:
    if match.stem not in _BURN_STEMS:
        return False
    near = _near(tokens, match, _LIGHT_RADIUS)
    if _LIGHT_OBJECTS.find_all(near) and not _FIRE_OBJECTS.find_all(near):
        return True
    return bool(
        _LIGHT_OBJECTS.find_all(tokens)
        and not _FIRE_OBJECTS.find_all(tokens)
        and not _FIRE_PLACES.find_all(tokens)
    )


def _is_figurative(tokens: Sequence[Token], match: StemMatch) -> bool:
    """«Горит дедлайн», «на работе пожар», «просто огонь», «огоньки»."""
    token = tokens[match.first_token].text
    if token.startswith(_DIMINUTIVE_LIGHT):
        return True
    if match.stem not in _FIGURATIVE_STEMS:
        return False
    if _fire_object_near(tokens, match, _LIGHT_RADIUS):
        return False
    if match.stem == "огон" and match.first_token > 0:
        if tokens[match.first_token - 1].text in _PRAISE:
            return True
    return bool(_FIGURATIVE_OBJECTS.find_all(_near(tokens, match, _LIGHT_RADIUS)))


def _same_clause(text: str, left: Token, right: Token) -> bool:
    return not any(char in _CLAUSE_BREAKS for char in text[left.end : right.start])


def _negated(tokens: Sequence[Token], matches: Sequence[StemMatch], text: str = "") -> bool:
    # «Не» внутри самой фразы правила («соседка не может выйти») — не отрицание.
    own = {index for match in matches for index in range(match.first_token, match.last_token + 1)}
    for match in matches:
        first = tokens[match.first_token]
        if first.text in _NEGATION:
            continue
        for offset in (1, 2):
            index = match.first_token - offset
            if (
                index >= 0
                and index not in own
                and tokens[index].text in _NEGATION
                and _same_clause(text, tokens[index], first)
            ):
                return True
        after = match.last_token + 1
        if (
            after < len(tokens)
            and after not in own
            and tokens[after].text in _NEGATION
            and _same_clause(text, tokens[match.last_token], tokens[after])
        ):
            return True
    return False


def _close(left: Sequence[StemMatch], right: Sequence[StemMatch], radius: int) -> bool:
    return any(
        abs(first.first_token - second.first_token) <= radius
        for first in left
        for second in right
    )


def _is_drill(tokens: Sequence[Token], text: str) -> bool:
    """Учения рядом с темой тревоги или проверка оповещения; «не учения» — нет."""
    words = [
        match for match in _DRILL_WORDS.find_all(tokens) if not _negated(tokens, [match], text)
    ]
    if words and _close(words, _DRILL_TOPICS.find_all(tokens), _MARKER_RADIUS):
        return True
    return _close(_CHECK_WORDS.find_all(tokens), _ALARM_OBJECTS.find_all(tokens), _MARKER_RADIUS)


def _is_resolved(tokens: Sequence[Token], text: str) -> bool:
    """Отчёт после устранения или благодарность службам без признака продолжения."""
    if any(token.text in _STILL_WORDS for token in tokens) or _STILL_PHRASES.find_all(tokens):
        return False
    if any(not _negated(tokens, [match], text) for match in _RESOLVED.find_all(tokens)):
        return True
    return _close(_THANKS.find_all(tokens), _RESPONDERS.find_all(tokens), _MARKER_RADIUS)


def _starts(tokens: Sequence[Token], match: StemMatch, prefixes: tuple[str, ...]) -> bool:
    return tokens[match.first_token].text.startswith(prefixes)


def _memo_blocked(tokens: Sequence[Token]) -> bool:
    """Гипотеза («если пахнет газом — куда звонить») или прошлое («был дым»)."""
    texts = {token.text for token in tokens}
    return bool(
        texts & _HYPOTHETICAL_WORDS
        or texts & _PAST_WORDS
        or _HYPOTHETICAL_PHRASES.find_all(tokens)
        or _PAST_PHRASES.find_all(tokens)
    )


def _memo_pattern(
    kind: DangerKind, tokens: Sequence[Token], found: Sequence[Sequence[StemMatch]]
) -> bool:
    """Высокоточная формулировка настоящего времени для вида опасности.

    Список намеренно узкий: «пахнет газом», «запах газа», «горит квартира»,
    «пожар в подвале», «дым из подвала», «искрит щиток», «застряли в лифте»,
    «обрушился балкон». Затопление в него не входит: памятка говорит об угрозе
    жизни и 112, а для протечки это не высокоточный признак.
    """
    if kind == "gas":
        gas = [match for match in found[0] if tokens[match.first_token].text in _GAS_WORDS]
        smell = [match for match in found[1] if _starts(tokens, match, _PRESENT_SMELL)]
        return _close(gas, smell, _PROXIMITY)
    if kind == "smoke_fire":
        places = _MEMO_PLACES.find_all(tokens)
        strong = [
            match
            for match in found[0]
            if tokens[match.first_token].text in _FIRE_NOUNS
            or _starts(tokens, match, _PRESENT_BURN)
            or _starts(tokens, match, _SMOKE)
        ]
        return _close(strong, places, _MEMO_RADIUS)
    if kind == "electric":
        if len(found) == 2:
            smoking = [match for match in found[1] if _starts(tokens, match, ("дымит",))]
            return _close(found[0], smoking, _MEMO_RADIUS)
        sparks = [match for match in found[0] if _starts(tokens, match, _SPARK)]
        shock = [match for match in found[0] if _starts(tokens, match, ("током",))]
        return _close(sparks, _ELECTRIC_OBJECTS.find_all(tokens), _MEMO_RADIUS) or _close(
            shock, _SHOCK.find_all(tokens), _MEMO_RADIUS
        )
    if kind == "person_trapped":
        trapped = [match for match in found[0] if _starts(tokens, match, _TRAPPED)]
        lift = [match for match in found[1] if _starts(tokens, match, _LIFT)]
        return _close(trapped, lift, _MEMO_RADIUS)
    if kind == "structural":
        collapse = [match for match in found[0] if _starts(tokens, match, _COLLAPSE)]
        return _close(collapse, _BUILDING_PARTS.find_all(tokens), _MEMO_RADIUS)
    return False


def _combine(groups: Sequence[list[StemMatch]]) -> list[StemMatch] | None:
    """Ближайшая комбинация совпадений всех групп в пределах окна."""
    best: list[StemMatch] | None = None
    best_span = _PROXIMITY + 1
    for anchor in groups[0]:
        chosen = [anchor]
        for group in groups[1:]:
            nearest: StemMatch | None = None
            distance = _PROXIMITY + 1
            for item in group:
                current = abs(item.first_token - anchor.first_token)
                if current < distance:
                    nearest, distance = item, current
            if nearest is None:
                break
            chosen.append(nearest)
        if len(chosen) != len(groups):
            continue
        first = min(item.first_token for item in chosen)
        last = max(item.last_token for item in chosen)
        span = last - first
        if span <= _PROXIMITY and span < best_span:
            best, best_span = chosen, span
    return best


def _hits(normalized: NormalizedText, tokens: Sequence[Token], line_id: str) -> list[DangerHit]:
    displaced = bool(_DISPLACED_SET.find_all(tokens))
    # Учения и отчёт после устранения отменяют срабатывания всей реплики:
    # они остаются в журнале как отменённые, как «газом не пахнет».
    text = normalized.text
    cancelled = _is_drill(tokens, text) or _is_resolved(tokens, text)
    memo_blocked = displaced or cancelled or _memo_blocked(tokens)
    hits: list[DangerHit] = []
    seen: set[tuple[DangerKind, str]] = set()
    for kind, groups in _COMPILED:
        found = [group.find_all(tokens) for group in groups]
        if kind == "smoke_fire":
            # «Свет не горит» остаётся в журнале как отменённое отрицанием;
            # отбрасывается только утвердительное «свет горит» и переносное
            # значение («горит дедлайн»).
            found = [
                [
                    match
                    for match in group
                    if not (_is_light_on(tokens, match) and not _negated(tokens, [match], text))
                    and not _is_figurative(tokens, match)
                ]
                for group in found
            ]
        if any(not item for item in found):
            continue
        combined = _combine(found)
        if combined is None:
            continue
        start = min(item.start for item in combined)
        end = max(item.end for item in combined)
        quote = normalized.quote(start, end)
        key = (kind, quote)
        if key in seen:
            continue
        seen.add(key)
        negated = cancelled or _negated(tokens, combined, text)
        hits.append(
            DangerHit(
                kind=kind,
                line_id=line_id,
                quote=quote,
                negated=negated,
                displaced=displaced,
                chat_memo_eligible=(
                    not negated and not memo_blocked and _memo_pattern(kind, tokens, found)
                ),
            )
        )
    return hits



def screen_message_for_danger(text: str, *, line_id: str = "") -> list[DangerHit]:
    """Признаки опасности в одной реплике, включая отменённые отрицанием.

    Возвращает все срабатывания: с `negated=True` — отменённые отрицанием
    («газом не пахнет», «никто не застрял»), учениями («учебная пожарная
    тревога») или отчётом после устранения («спасибо пожарным», «потушили»),
    с `displaced=True` — отнесённые к другому месту или времени («в соседнем
    доме», «в прошлом году»). `chat_memo_eligible` — право на памятку в чат
    (`chat_memo_hits`). Решение о том, что считать аварией, принимает
    Emergency Fusion, а не эта функция.
    """
    try:
        normalized = normalize(text)
        return _hits(normalized, tokenize(normalized.text), line_id)
    except Exception:  # приём webhook не должен падать из-за ошибки правил
        return []


def screen_normalized(
    normalized: NormalizedText, tokens: Sequence[Token], line_id: str
) -> list[DangerHit]:
    """Тот же разбор для уже нормализованной реплики окна."""
    try:
        return _hits(normalized, tokens, line_id)
    except Exception:  # анализ окна не должен падать из-за ошибки правил
        return []


def chat_memo_hits(hits: Sequence[DangerHit]) -> list[DangerHit]:
    """Срабатывания, дающие боту право на памятку в домовой чат.

    Голос бота в чате — самый строгий уровень (v3 §5): только высокоточные
    формулировки (`chat_memo_eligible`), без отрицания и «не у нас».
    Оповещение оператора от этого не зависит — оно идёт на любое срабатывание
    без отрицания.
    """
    return [
        hit
        for hit in hits
        if hit.chat_memo_eligible and not hit.negated and not hit.displaced
    ]
