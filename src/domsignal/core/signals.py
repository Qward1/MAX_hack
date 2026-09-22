"""Чистые правила продукта для пассивного чтения чата. Без БД и без сети.

Здесь нет ни правил опасности, ни политики окна, ни расчёта силы сигнала: всё
это решает AI-ядро (`domsignal.ai`). Продукт решает только своё — какую
реплику вообще можно сохранить, как склеить ветку об одном дефекте, сколько
слабых сигналов показать оператору и куда положить остальное.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

#: Предел текста реплики в буфере. Совпадает с пределом реплики окна ядра.
TEXT_LIMIT = 4000

#: Сколько цитат сигнала переживает буфер.
MAX_QUOTES = 3

#: Предел одной цитаты сигнала. Цитата — дословное начало реплики.
QUOTE_LIMIT = 300

#: Команда боту — служебное сообщение, а не разговор: у `/report` свой путь.
_COMMAND = re.compile(r"^/[A-Za-z][A-Za-z0-9_]*(?:@\S+)?(?:\s|$)")

DropReason = Literal[
    "capture_disabled",
    "not_a_message",
    "no_binding",
    "binding_inactive",
    "before_activation",
    "binding_capture_disabled",
    "no_text",
    "no_message_id",
    "command",
]

Strength = Literal["critical", "strong", "medium", "weak", "filtered"]
Disposition = Literal["inbox", "audit_pool"]

#: Сила по убыванию. Сила сигнала при склейке ветки только растёт.
STRENGTH_RANK: dict[str, int] = {
    "critical": 4,
    "strong": 3,
    "medium": 2,
    "weak": 1,
    "filtered": 0,
}

#: Подписи видов опасности для оператора. Шаблон продукта, не текст модели.
DANGER_LABELS: dict[str, str] = {
    "gas": "запах газа",
    "smoke_fire": "дым или огонь",
    "electric": "искрение или электричество",
    "person_trapped": "человек не может выйти",
    "flooding": "затопление",
    "structural": "обрушение или трещины",
    "other_hazard": "иная опасность",
}


@dataclass(frozen=True)
class BindingState:
    """Что структурному фильтру нужно знать о привязке чата."""

    status: str
    activated_at: datetime | None
    passive_capture_enabled: bool


def is_command(text: str) -> bool:
    """Команда боту (`/report …`, `/start`) в буфер не попадает."""
    return bool(_COMMAND.match(text.lstrip()))


def structural_drop_reason(
    *,
    capture_enabled: bool,
    kind: str,
    chat_id: str | None,
    actor: str | None,
    mid: str | None,
    text: str | None,
    occurred_at: datetime,
    binding: BindingState | None,
) -> DropReason | None:
    """Почему реплику нельзя положить в буфер, или `None`, если можно.

    Текст реплики приходит уже пустым, если отправитель — бот, если это не
    групповой чат или если тела сообщения нет: так его нормализует разбор
    обновления MAX. Отброшенная реплика не оставляет следа.
    """
    if not capture_enabled:
        return "capture_disabled"
    if kind != "message_created" or not chat_id or not actor:
        return "not_a_message"
    if binding is None:
        return "no_binding"
    if binding.status != "active":
        return "binding_inactive"
    if binding.activated_at is None or occurred_at < binding.activated_at:
        return "before_activation"
    if not binding.passive_capture_enabled:
        return "binding_capture_disabled"
    if text is None or not text.strip():
        return "no_text"
    if not mid:
        return "no_message_id"
    if is_command(text):
        return "command"
    return None


def buffer_text(text: str) -> tuple[str, bool]:
    """Текст для буфера и признак обрезки."""
    if len(text) <= TEXT_LIMIT:
        return text, False
    return text[:TEXT_LIMIT], True


def quote_text(text: str) -> str:
    """Дословная цитата реплики для сигнала: начало реплики без изменений."""
    stripped = text.strip()
    if len(stripped) <= QUOTE_LIMIT:
        return stripped
    return stripped[: QUOTE_LIMIT - 1].rstrip() + "…"


def _normalize_place(value: str | None) -> str:
    if value is None:
        return "-"
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    return cleaned or "-"


def dedupe_key(subtype: str, dedupe_scope: str, entrance: str | None) -> str:
    """Ключ склейки ветки: подтип + `dedupe_scope` таксономии + подъезд.

    Для проблем всего дома подъезд не важен. Для проблем объекта (лифт,
    подъезд) подъезд различает объекты; «лифт не работает» без подъезда не
    склеивается с лифтом во втором подъезде — так же, как ядро не привязывает
    такую реплику к открытому элементу без подъезда.
    """
    if dedupe_scope == "house":
        return f"{subtype}|house"
    return f"{subtype}|object|{_normalize_place(entrance)}"


def danger_key(kinds: tuple[str, ...]) -> str:
    """Ключ предварительного критического сигнала: подтипа до разбора ещё нет."""
    return "danger|" + "+".join(sorted(set(kinds)))


def stronger(current: str, incoming: str) -> bool:
    """Сильнее ли пришедшая сила текущей."""
    return STRENGTH_RANK.get(incoming, 0) > STRENGTH_RANK.get(current, 0)


def place_signal(
    strength: str,
    core_disposition: str,
    *,
    audit_sample: bool,
    weak_today: int,
    weak_limit: int,
) -> tuple[Disposition, str | None]:
    """Inbox или Audit Pool и причина. Силу продукт не пересчитывает.

    `filtered` и выборка аудита уходят в Audit Pool по решению ядра.
    Слабый сигнал сверх дневного лимита дома — тоже в Audit Pool, с причиной
    `weak_overflow`: оператор не обязан разбирать бесконечный хвост догадок.
    """
    if core_disposition == "audit_pool" or strength == "filtered":
        return "audit_pool", "audit_sample" if audit_sample else "filtered"
    if strength == "weak" and weak_today >= weak_limit:
        return "audit_pool", "weak_overflow"
    return "inbox", None


def author_label(author_ref: str) -> str:
    """Как оператор видит автора цитаты."""
    return f"Житель {author_ref}"


__all__ = [
    "DANGER_LABELS",
    "MAX_QUOTES",
    "QUOTE_LIMIT",
    "STRENGTH_RANK",
    "TEXT_LIMIT",
    "BindingState",
    "Disposition",
    "DropReason",
    "Strength",
    "author_label",
    "buffer_text",
    "danger_key",
    "dedupe_key",
    "is_command",
    "place_signal",
    "quote_text",
    "stronger",
    "structural_drop_reason",
]
