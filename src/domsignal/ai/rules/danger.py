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
    # D6 (MEMO-PRECISION-2026-09-28): чужое место на реальных окнах D5.
    # «Соседний подъезд» и «соседняя квартира» — наш дом, их здесь нет.
    "через дорогу",
    "через улицу",
    "соседнем дворе",
    "соседнего двора",
    "соседний двор",
    "соседних домах",
    "соседних домов",
    "соседнему дому",
    "в квартале",
    "по соседству",
    "на другой стороне",
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

#: D6: «в доме напротив», «дом напротив» — чужой дом. Форма слова «дом»
#: сравнивается целиком: основа «дом» нашла бы и «домофон напротив лифта»;
#: «напротив нашего дома» — это у нас.
_HOUSE_FORMS = frozenset({"дом", "доме", "дома", "дому", "домом", "домах", "домов"})
_ACROSS = "напротив"

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
#: F1 (пробы §4): «горит свет в подвале» — место рядом с включённым светом, не
#: горящий предмет. Если осветительный объект стоит вплотную к глаголу горения
#: и в реплике нет материала возгорания, памятки в чат нет; оповещение
#: оператора остаётся (не ослабляем опасность).
_FIRE_MATERIALS = StemSet(
    (
        "проводк",
        "провод",
        "кабел",
        "щит",
        "мусор",
        "машин",
        "дым",
        "гар",
        "огон",
        "пламя",
        "пожар",
        "искр",
    )
)
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
#: D6: «горит желание», «горят все от этой новости», «нервы горят».
_FIGURATIVE_EXTRA = StemSet(("желани", "новост", "нерв", "сердц", "азарт", "терпени"))
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
_RESPONDERS = StemSet(("пожарн", "мчс", "газовик", "газовщик", "аварийк", "аварийн", "спасател"))
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
#: P6c: маркеры прошлого шире — «в прошлом месяце», «в позапрошлом году»,
#: «как-то раз», «однажды», «когда-то», «в тот раз», «N лет назад». «Давно»
#: и «тогда» маркерами не стали: «давно пахнет газом» — это сейчас; для них
#: работает прошедшая форма самого предиката («тогда искрило»).
_PAST_ADJECTIVES = frozenset(
    prefix + ending
    for prefix in ("прошл", "позапрошл")
    for ending in ("ый", "ая", "ое", "ые", "ого", "ой", "ому", "ым", "ом", "ую", "ых", "ыми")
)
_PAST_EVENT_WORDS = frozenset({"однажды"})
_PAST_EVENT_PHRASES = StemSet(("как то раз", "когда то", "в тот раз"))
_LONG_UNITS = frozenset(
    {"лет", "год", "года", "месяц", "месяца", "месяцев"}
    | {"неделю", "недели", "недель", "дня", "дней"}
)
_AGO = "назад"
#: P6c: прошедшая форма предиката процесса («искрило», «дымило», «полыхало»)
#: — не формулировка настоящего времени. «Застрял» и «обрушился» сюда не
#: входят: они описывают состояние сейчас.
_PAST_ENDINGS = ("л", "ла", "ло", "ли", "лся", "лась", "лось", "лись")


#: D6: табачный дым — «курят в подъезде, дым на весь этаж», «сигаретный дым с
#: балкона». Слово дыма рядом с табаком снимает срабатывание, если в реплике
#: нет признака настоящего горения: глагола огня, «пожара» или объекта, где
#: дым означает возгорание («уснул с сигаретой — горит диван», «окурок в
#: мусоропроводе, горит», «дым из подвала»).
_TOBACCO = StemSet(
    (
        "курит",
        "курят",
        "курил",
        "курить",
        "курите",
        "курени",
        "накур",
        "покур",
        "перекур",
        "курильщ",
        "сигарет",
        "табак",
        "табачн",
        "кальян",
        "вейп",
        "окурк",
        "окурок",
        "бычк",
    )
)
_REAL_FIRE = StemSet(
    (
        "горит",
        "горят",
        "горел",
        "загорел",
        "возгоран",
        "полыха",
        "тлеет",
        "пламя",
        "пламен",
        "огон",
        "проводк",
        "щит",
        "кабел",
        "розетк",
        "матрас",
        "постел",
        "диван",
        "мусоропровод",
        "подвал",
        "чердак",
    )
)
_SMOKE_VERBS = ("дымит", "дымят", "дымил")
#: D6: названия систем дома — «система дымоудаления», «дымоход», «дымовой
#: извещатель» — не дым. Основа «дым» находила их как начало слова.
_SMOKE_SYSTEMS = ("дымоуд", "дымоход", "дымосос", "дымов")
#: D6: «пожарный проезд», «пожарная лестница», «пожарные краны», «правила
#: пожарной безопасности» — не сообщение о пожаре: прилагательное перед
#: названием оборудования или правил срабатывания не даёт. «Пожарные
#: приехали» остаётся оповещением оператора (памятки на него и раньше не было).
_FIRE_ADJECTIVE = "пожарн"
_FIRE_EQUIPMENT = StemSet(
    (
        "проезд",
        "лестниц",
        "кран",
        "выход",
        "безопасност",
        "щит",
        "шкаф",
        "рукав",
        "гидрант",
        "машин",
        "двер",
        "норм",
        "инспек",
        "надзор",
        "водоем",
    )
)
#: D6: «бьёт током» от ошейника, свитера, пледа, «статическое электричество» —
#: не авария электрики, если рядом нет её объекта (щиток, провод, розетка).
_SHOCK_BENIGN = StemSet(
    (
        "ошейник",
        "электроошейник",
        "шокер",
        "электрошокер",
        "свитер",
        "кофт",
        "одежд",
        "синтетик",
        "статическ",
        "статик",
        "плед",
        "волос",
        "шерст",
    )
)
_PETS = frozenset(
    {"кот", "кота", "коту", "котом", "котик", "котенок", "кошка", "кошку", "кошки", "кошкой"}
)
#: F1 (пробы §4): «бьёт током от дверной ручки, зима» — статическое
#: электричество. Памятки в чат нет, оповещение оператора остаётся: ручка под
#: напряжением бывает и настоящей аварией.
_SHOCK_STATIC = StemSet(("ручк", "поручн", "перил", "дверн"))
_ELECTRIC_HAZARD = StemSet(
    (
        "щит",
        "провод",
        "кабел",
        "розетк",
        "счетчик",
        "выключател",
        "стиральн",
        "плит",
        "бойлер",
        "водонагрев",
        "искр",
        "коротит",
        "замыкан",
    )
)
#: D6: условие и общая фраза в пределах одной фразы: «когда квартиры горят,
#: никто не думает о правилах», «при пожаре звоните 112», «в случае пожара
#: выход закрыт». Граница фразы («когда уже приедут? горит подвал») их
#: действие обрывает. Снимают право на памятку, не оповещение.
_CLAUSE_HYPOTHETICAL_WORDS = frozenset({"когда", "если"})
_CLAUSE_HYPOTHETICAL_PHRASES = StemSet(("в случае", "при пожар", "во время пожар"))
_CLAUSE_LOOKBACK = 6


def _house_across(tokens: Sequence[Token]) -> bool:
    """«В доме напротив», «дом напротив»; «квартира напротив лифта» — нет."""
    for index, token in enumerate(tokens):
        if token.text != _ACROSS:
            continue
        around = [*tokens[max(0, index - 2) : index], *tokens[index + 1 : index + 3]]
        if any(item.text.startswith("наш") for item in around):
            continue
        if any(item.text in _HOUSE_FORMS for item in around):
            return True
    return False


def _tobacco_smoke(tokens: Sequence[Token], match: StemMatch) -> bool:
    """Слово дыма в реплике о курении без признака настоящего горения."""
    token = tokens[match.first_token].text
    smoke_word = (token.startswith("дым") and not token.startswith(_SMOKE_VERBS)) or (
        token.startswith("задымл")
    )
    if not smoke_word or not _TOBACCO.find_all(tokens):
        return False
    if any(item.text in _FIRE_NOUNS for item in tokens):
        return False
    return not _REAL_FIRE.find_all(tokens)


def _fire_equipment(tokens: Sequence[Token], match: StemMatch) -> bool:
    """«Пожарный проезд», «пожарные краны» — прилагательное перед оборудованием."""
    if not tokens[match.first_token].text.startswith(_FIRE_ADJECTIVE):
        return False
    following = tokens[match.last_token + 1 : match.last_token + 2]
    return bool(following and _FIRE_EQUIPMENT.find_all(following))


def _benign_shock(tokens: Sequence[Token]) -> bool:
    """«Бьёт током» от ошейника, свитера или кота, без объекта электрики."""
    benign = bool(_SHOCK_BENIGN.find_all(tokens)) or any(item.text in _PETS for item in tokens)
    return benign and not _ELECTRIC_HAZARD.find_all(tokens)


def _clause_hypothetical(text: str, tokens: Sequence[Token], matches: Sequence[StemMatch]) -> bool:
    """Условие или общая фраза перед срабатыванием в той же фразе."""
    for match in matches:
        first = tokens[match.first_token]
        low = max(0, match.first_token - _CLAUSE_LOOKBACK)
        for index in range(low, match.first_token):
            if tokens[index].text in _CLAUSE_HYPOTHETICAL_WORDS and _same_clause(
                text, tokens[index], first
            ):
                return True
        window = tokens[low : match.first_token + 2]
        for item in _CLAUSE_HYPOTHETICAL_PHRASES.find_all(window):
            if _same_clause(text, window[item.first_token], first):
                return True
    return False


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


def _memo_exception(kind: str, tokens: Sequence[Token], combined: Sequence[StemMatch]) -> bool:
    """Памятки в чат нет, оповещение оператора остаётся (F1, пробы §4)."""
    if kind == "smoke_fire":
        if _FIRE_MATERIALS.find_all(tokens):
            return False
        for match in combined:
            if match.stem not in _BURN_STEMS:
                return False
            side = [
                tokens[i]
                for i in (match.first_token - 1, match.last_token + 1)
                if 0 <= i < len(tokens)
            ]
            if not _LIGHT_OBJECTS.find_all(side):
                return False
        return bool(combined)
    if kind == "electric":
        return bool(_SHOCK_STATIC.find_all(tokens)) and not _ELECTRIC_HAZARD.find_all(tokens)
    return False


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
    near = _near(tokens, match, _LIGHT_RADIUS)
    return bool(_FIGURATIVE_OBJECTS.find_all(near) or _FIGURATIVE_EXTRA.find_all(near))


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
        abs(first.first_token - second.first_token) <= radius for first in left for second in right
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


def _long_ago(tokens: Sequence[Token]) -> bool:
    """«Лет пять назад», «месяца три назад», «неделю назад»; «минут 5 назад» — нет."""
    for index, token in enumerate(tokens):
        if token.text != _AGO:
            continue
        if any(item.text in _LONG_UNITS for item in tokens[max(0, index - 2) : index]):
            return True
    return False


def _memo_blocked(tokens: Sequence[Token]) -> bool:
    """Гипотеза («если пахнет газом — куда звонить») или прошлое («был дым»)."""
    texts = {token.text for token in tokens}
    return bool(
        texts & _HYPOTHETICAL_WORDS
        or texts & _PAST_WORDS
        or texts & _PAST_ADJECTIVES
        or texts & _PAST_EVENT_WORDS
        or _HYPOTHETICAL_PHRASES.find_all(tokens)
        or _PAST_PHRASES.find_all(tokens)
        or _PAST_EVENT_PHRASES.find_all(tokens)
        or _long_ago(tokens)
    )


def _present(tokens: Sequence[Token], match: StemMatch) -> bool:
    """Предикат процесса не в прошедшей форме: «искрит», а не «искрило»."""
    return not tokens[match.first_token].text.endswith(_PAST_ENDINGS)


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
            or (
                (_starts(tokens, match, _PRESENT_BURN) or _starts(tokens, match, _SMOKE))
                and _present(tokens, match)
            )
        ]
        return _close(strong, places, _MEMO_RADIUS)
    if kind == "electric":
        if len(found) == 2:
            smoking = [match for match in found[1] if _starts(tokens, match, ("дымит",))]
            return _close(found[0], smoking, _MEMO_RADIUS)
        sparks = [
            match
            for match in found[0]
            if _starts(tokens, match, _SPARK) and _present(tokens, match)
        ]
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
    displaced = bool(_DISPLACED_SET.find_all(tokens)) or _house_across(tokens)
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
                    and not _tobacco_smoke(tokens, match)
                    and not _fire_equipment(tokens, match)
                    and not tokens[match.first_token].text.startswith(_SMOKE_SYSTEMS)
                ]
                for group in found
            ]
        elif kind == "electric" and _benign_shock(tokens):
            continue
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
                    not negated
                    and not memo_blocked
                    and not _clause_hypothetical(text, tokens, combined)
                    and not _memo_exception(kind, tokens, combined)
                    and _memo_pattern(kind, tokens, found)
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
    return [hit for hit in hits if hit.chat_memo_eligible and not hit.negated and not hit.displaced]
