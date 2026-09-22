"""Столбцы, добавленные срезами P3b и P4 к уже существующим таблицам.

Проверки миграций сравнивают строки до и после обновления до head. Новые
столбцы перечислены здесь явно, чтобы сравнение оставалось осмысленным: оно
доказывает, что миграция аддитивна и ни одно существующее значение не
переписано, а не просто игнорирует расхождение.
"""

from __future__ import annotations

P3B_COLUMNS: dict[str, tuple[str, ...]] = {
    "incidents": (
        "location_entrance",
        "location_floor",
        "location_label",
        "observed_since",
    ),
    "reports": ("analysis",),
    "notification_deliveries": ("route_outcome_id", "signal_id", "chat_binding_id"),
    # P4: пассивное чтение чата.
    "chat_bindings": ("passive_capture_enabled",),
    "route_outcomes": ("signal_id",),
}


#: Значение, которое миграция ставит существующим строкам. Столбцы, которых
#: здесь нет, обязаны остаться пустыми. Чтение чата у прежних привязок
#: выключено — это и есть значение по умолчанию.
ADDED_DEFAULTS: dict[str, object] = {"passive_capture_enabled": False}


def added_default(column: str) -> object:
    """Что миграция обязана оставить в добавленном столбце прежней строки."""
    return ADDED_DEFAULTS.get(column)


def added_by_p3b(table: str) -> tuple[str, ...]:
    """Столбцы, которых в этой таблице до среза P3b не было (включая P4)."""
    return P3B_COLUMNS.get(table, ())


def without_added_columns(table: str, *extra: str) -> str:
    """SQL-выражение строки таблицы без столбцов, добавленных после базы сравнения.

    Вычитание отсутствующего ключа в `jsonb` — не ошибка, поэтому одно и то же
    выражение работает и до обновления, и после.
    """
    columns = (*added_by_p3b(table), *extra)
    if not columns:
        return "row_to_json(t)"
    return "to_jsonb(t)" + "".join(f" - '{name}'" for name in columns)
