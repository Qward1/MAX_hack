"""Тихие часы домового чата (BOT-VOICE-HUMAN-2026-09-27).

Окно задаётся минутами суток по Москве: начало и конец. Окно может
переходить через полночь (22:00–08:00). Начало, равное концу, — тихих часов
нет. Москва живёт по UTC+3 без перехода на летнее время, поэтому пояс
фиксирован и не зависит от базы часовых поясов.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))

#: 22:00–08:00 МСК — значение по умолчанию для чатов и личных рассылок.
DEFAULT_QUIET_START = 22 * 60
DEFAULT_QUIET_END = 8 * 60
MINUTES_PER_DAY = 24 * 60


def minutes_label(value: int) -> str:
    """«22:00» по минутам суток."""
    return f"{value // 60:02d}:{value % 60:02d}"


def parse_minutes(value: str) -> int:
    """«22:00» → минуты суток; неверная запись — `ValueError`."""
    hours, _, minutes = value.partition(":")
    if not (hours.isdigit() and minutes.isdigit() and len(minutes) == 2 and len(hours) <= 2):
        raise ValueError("time must look like HH:MM")
    result = int(hours) * 60 + int(minutes)
    if int(hours) > 23 or int(minutes) > 59:
        raise ValueError("time must look like HH:MM")
    return result


def quiet_until(start: int, end: int, at: datetime) -> datetime | None:
    """Конец тихих часов, если `at` внутри окна, иначе `None`.

    Возвращает момент в UTC-совместимом `datetime` с поясом МСК: сравнивать
    его можно с любым осведомлённым о поясе временем.
    """
    if start == end:
        return None
    local = at.astimezone(MSK)
    minute = local.hour * 60 + local.minute
    if start < end:
        inside = start <= minute < end
    else:
        inside = minute >= start or minute < end
    if not inside:
        return None
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    candidate = day + timedelta(minutes=end)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


__all__ = [
    "DEFAULT_QUIET_END",
    "DEFAULT_QUIET_START",
    "MSK",
    "minutes_label",
    "parse_minutes",
    "quiet_until",
]
