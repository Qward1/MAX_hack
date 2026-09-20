"""Explicit operational tools; imports have no side effects."""

from __future__ import annotations

import io
import json
import sys
from typing import Any


def print_json(payload: Any) -> None:
    """Печать JSON с кириллицей.

    Вывод карточки содержит кириллицу и «→», а консоль Windows по умолчанию
    работает в однобайтовой кодировке: без явного UTF-8 инструмент падал бы на
    печати вместо того, чтобы показать маршрут.
    """
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
