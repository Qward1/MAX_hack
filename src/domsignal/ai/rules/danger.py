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


def _negated(tokens: Sequence[Token], matches: Sequence[StemMatch]) -> bool:
    for match in matches:
        if tokens[match.first_token].text in _NEGATION:
            continue
        for offset in (1, 2):
            index = match.first_token - offset
            if index >= 0 and tokens[index].text in _NEGATION:
                return True
        after = match.last_token + 1
        if after < len(tokens) and tokens[after].text in _NEGATION:
            return True
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
    hits: list[DangerHit] = []
    seen: set[tuple[DangerKind, str]] = set()
    for kind, groups in _COMPILED:
        found = [group.find_all(tokens) for group in groups]
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
        hits.append(
            DangerHit(
                kind=kind,
                line_id=line_id,
                quote=quote,
                negated=_negated(tokens, combined),
                displaced=displaced,
            )
        )
    return hits


def screen_message_for_danger(text: str, *, line_id: str = "") -> list[DangerHit]:
    """Признаки опасности в одной реплике, включая отменённые отрицанием.

    Возвращает все срабатывания: с `negated=True` — отменённые отрицанием
    («газом не пахнет», «никто не застрял»), с `displaced=True` — отнесённые
    к другому месту или времени («в соседнем доме», «в прошлом году»).
    Решение о том, что считать аварией, принимает Emergency Fusion, а не
    эта функция.
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
