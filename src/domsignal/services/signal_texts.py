"""Тексты очереди сигналов оператора — только шаблоны продукта.

Причина силы, подписи территории, причин закрытия и событий, описание заявки
по умолчанию. Текст модели сюда не попадает: описание заявки собирается из
дословных цитат жителей и полей с цитатой, а не из пересказа разбора.
Запрещённые формулировки (`FORBIDDEN_PHRASES`) проверяет контрактный тест.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from domsignal.core.signals import author_label

#: Причина силы человеческими словами по коду ядра или продукта.
STRENGTH_REASONS: dict[str, str] = {
    "emergency": "В сообщениях жителей есть признаки опасности — сигнал критический.",
    "rules_danger_preliminary": (
        "Правила ДомСигнала нашли признак опасности в сообщении жителя; переписку ещё разбирают."
    ),
    "all_facets_yes": ("Жители пишут, что проблема есть сейчас, в этом доме и они видят её сами."),
    "observed_yes": (
        "Житель видит проблему сам; есть ли она сейчас и в этом ли доме — не до конца ясно."
    ),
    "facets_unclear": (
        "Из переписки не ясно, есть ли проблема сейчас и в этом ли доме — это возможный сигнал."
    ),
    "facet_no_local": "Переписка указывает, что проблема не в этом доме.",
    "facet_no_observed": "Переписка указывает, что жители не видели проблему сами.",
    "facet_no_current": "Переписка указывает, что проблема уже в прошлом.",
}
_STRENGTH_FALLBACK = "Сила определена разбором переписки по правилам продукта."

TERRITORY_LABELS: dict[str, str] = {
    "apartment": "Квартира",
    "house_common": "Общее имущество дома",
    "house_territory": "Придомовая территория",
    "municipal_territory": "Муниципальная территория",
    "external_network": "Внешние сети",
    "other_building": "Другое здание",
    "unknown": "Территория не определена",
}

DISMISS_REASON_LABELS: dict[str, str] = {
    "not_a_problem": "Не проблема",
    "duplicate": "Дубликат",
    "resolved": "Уже решено",
    "out_of_scope": "Не относится к дому",
    "spam": "Спам или флуд",
}

#: События, которые видит оператор. Остальные события ядра — внутренние.
EVENT_LABELS: dict[str, str] = {
    "preliminary_critical": "Правила нашли признак опасности",
    "danger_grouped": "Повторное сообщение об опасности присоединено к сигналу",
    "chat_memo_queued": "Памятка безопасности поставлена в очередь в чат",
    "chat_memo_suppressed": "Памятка не повторена: недавно уже была",
    "operator_alert_requested": "Запрошено оповещение операторов",
    "operator_alert_queued": "Оповещение операторов поставлено в очередь",
    "operator_alert_skipped": "Оповещение не отправлено: нет получателей с MAX",
    "signal_created": "Сигнал создан по разбору переписки",
    "signal_grouped": "Новые сообщения о той же проблеме",
    "route_assigned": "Маршрут определён по справочнику",
    "preliminary_reconciled": "Предварительный сигнал уточнён разбором переписки",
    "emergency_kept": "Опасность сохранена: разбор её не опроверг",
    "emergency_downgraded": "Опасность понижена: переписка её опровергла",
    "open_incident_match": "Похоже на уже открытую проблему дома",
    "window_after_decision": "Сообщения пришли после решения оператора",
    "signal_converted": "Оператор создал заявку",
    "signal_joined": "Оператор присоединил сигнал к проблеме",
    "signal_routed_external": "Оператор отметил внешний маршрут",
    "signal_route_chosen": "Оператор выбрал маршрут",
    "signal_dismissed": "Оператор закрыл сигнал",
}

#: Почему открытая проблема предложена для присоединения.
RELATED_CONVERSION_REASON = "По такому же сигналу уже создана заявка"

_TICKET_LEAD = "Из домового чата"
_QUOTES_HEADING = "Слова жителей:"
_PLACE_LABELS = (("entrance", "Подъезд"), ("floor", "Этаж"), ("since", "Наблюдается с"))
TICKET_DESCRIPTION_LIMIT = 2000


def strength_reason_text(code: str) -> str:
    return STRENGTH_REASONS.get(code, _STRENGTH_FALLBACK)


def subtype_title(label: str) -> str:
    """Подпись подтипа таксономии с заглавной буквы."""
    cleaned = label.strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Проблема"


def quoted_value(raw: Mapping[str, Any] | None) -> tuple[str, str] | None:
    """Значение места или времени — только если у него есть дословная цитата."""
    if not raw:
        return None
    value, quote = raw.get("value"), raw.get("quote")
    if not isinstance(value, str) or not value.strip():
        return None
    if not isinstance(quote, str) or not quote.strip():
        return None
    return value.strip(), quote.strip()


def ticket_description(
    *,
    subject: str,
    report_count: int,
    author_count: int,
    place: Mapping[str, Mapping[str, Any] | None],
    quotes: Sequence[tuple[str, str]],
) -> str:
    """Описание заявки по умолчанию: подпись подтипа, счётчики, место, цитаты.

    `quotes` — пары (псевдоним автора, дословная цитата). Текст модели сюда
    не передаётся: оператор видит ровно то, что сказали жители, и может
    поправить описание до отправки.
    """
    lines = [
        f"{_TICKET_LEAD}: {subject.lower()}. Сообщений: {report_count}, жителей: {author_count}."
    ]
    for key, label in _PLACE_LABELS:
        found = quoted_value(place.get(key))
        if found is not None:
            lines.append(f"{label}: {found[0]}.")
    if quotes:
        lines.append(_QUOTES_HEADING)
        lines.extend(f"— «{text}» ({author_label(author)})" for author, text in quotes)
    text = "\n".join(lines)
    if len(text) <= TICKET_DESCRIPTION_LIMIT:
        return text
    return text[: TICKET_DESCRIPTION_LIMIT - 1].rstrip() + "…"


__all__ = [
    "DISMISS_REASON_LABELS",
    "EVENT_LABELS",
    "RELATED_CONVERSION_REASON",
    "STRENGTH_REASONS",
    "TERRITORY_LABELS",
    "TICKET_DESCRIPTION_LIMIT",
    "quoted_value",
    "strength_reason_text",
    "subtype_title",
    "ticket_description",
]
