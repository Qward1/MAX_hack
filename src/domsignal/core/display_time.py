"""Время в сообщениях сотрудникам — в часовом поясе показа, а не в UTC.

Оповещение оператора в MAX пишет «23.09.2026 13:18 МСК» — в поясе дома из
пакета его региона (D4, `HouseZones`), для Владивостока — «… ВЛАД». Пояс по
умолчанию задаёт `DISPLAY_TIMEZONE` (`Europe/Moscow`); хранение и сравнение
времени остаются в UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DISPLAY_TIMEZONE = "Europe/Moscow"

#: Подпись пояса там, где у него есть общепринятое сокращение.
_LABELS = {"Europe/Moscow": "МСК", "Asia/Vladivostok": "ВЛАД"}

#: Пояса, которые нужны и без базы часовых поясов (Windows без `tzdata`).
#: Москва живёт по UTC+3 без перехода на летнее время с 26.10.2014.
_FIXED = {"Europe/Moscow": timezone(timedelta(hours=3))}


@lru_cache(maxsize=8)
def display_zone(name: str) -> tzinfo:
    """Пояс показа по имени IANA; неизвестное имя — `ValueError`."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        fixed = _FIXED.get(name)
        if fixed is None:
            raise ValueError(f"unknown time zone: {name}") from exc
        return fixed


def zone_label(name: str, moment: datetime) -> str:
    """«МСК» для Москвы, иначе смещение вида «UTC+05:00»."""
    label = _LABELS.get(name)
    if label is not None:
        return label
    offset = moment.utcoffset() or timedelta(0)
    sign = "+" if offset >= timedelta(0) else "-"
    minutes = abs(int(offset.total_seconds())) // 60
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def staff_moment(value: datetime, zone_name: str = DEFAULT_DISPLAY_TIMEZONE) -> str:
    """«23.09.2026 13:18 МСК» — момент в поясе показа с его подписью."""
    local = value.astimezone(display_zone(zone_name))
    return f"{local.strftime('%d.%m.%Y %H:%M')} {zone_label(zone_name, local)}"


__all__ = ["DEFAULT_DISPLAY_TIMEZONE", "display_zone", "staff_moment", "zone_label"]
