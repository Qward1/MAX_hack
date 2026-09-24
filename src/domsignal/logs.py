"""Журналы процессов без полных IP-адресов.

Полный адрес клиента в журналы не попадает ни из какого источника:

- журнал доступа uvicorn в production выключен (`--no-access-log`); запрос
  журналирует само приложение одной строкой `http_request` с `request_id`
  (тот же, что в заголовке `X-Request-ID`) и сетью клиента, усечённой до /24
  (IPv4) или /48 (IPv6);
- форматтер журналов приложения и фильтр на обработчиках uvicorn усекают любой
  IP-адрес в готовой строке — в том числе в тексте исключения;
- `domsignal.*` пишет с уровня INFO, всё остальное — с WARNING: журналы
  запросов HTTP-клиента (в адресе `POST /messages` стоит идентификатор
  получателя в MAX) не выводятся.

Ограничитель попыток входа хранит не адрес, а номер ячейки — HMAC-SHA256 от
адреса с `SESSION_SECRET`, взятый по модулю 65 536 (`EmployeeAuthService.rate`).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import sys
from typing import IO, Any

#: Кандидаты в адреса; окончательно решает `ipaddress`. Уже усечённая сеть
#: (`203.0.113.0/24`) повторно не трогается.
_IPV4 = re.compile(r"(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?(?![\w.]|/\d)")
_IPV6 = re.compile(
    r"\[([0-9A-Fa-f:.]*:[0-9A-Fa-f:.]*)\](?::\d{1,5})?"
    r"|(?<![\w:.])([0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:\.\d{1,3}){0,3})(?![\w:.]|/\d)"
)

IPV4_PREFIX = 24
IPV6_PREFIX = 48

_ACCESS_LOGGER = "uvicorn.access"

#: Поля записи журнала, которые есть у любой записи; всё прочее — `extra`.
_STANDARD = frozenset(
    {
        *logging.LogRecord("", 0, "", 0, "", None, None).__dict__,
        "message",
        "asctime",
        "taskName",
    }
)


def mask_ip(value: str | None) -> str:
    """Сеть адреса: IPv4 — /24, IPv6 — /48; не адрес — `unknown`."""
    host = (value or "").strip()
    if host.startswith("[") and "]" in host:
        host = host[1 : host.index("]")]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]  # «адрес:порт» у IPv4
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    prefix = IPV4_PREFIX if address.version == 4 else IPV6_PREFIX
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def _masked_or_same(match: re.Match[str], candidate: str) -> str:
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return match.group(0)
    if address.is_loopback or address.is_unspecified:
        # Адрес привязки сервера («running on http://0.0.0.0:8000») и
        # локальные проверки — не адрес клиента: строка остаётся как есть.
        return match.group(0)
    return mask_ip(candidate)


def scrub_ips(text: str) -> str:
    """Заменить каждый полный IP-адрес (с портом или без) его сетью."""
    text = _IPV6.sub(lambda m: _masked_or_same(m, m.group(1) or m.group(2)), text)
    return _IPV4.sub(lambda m: _masked_or_same(m, m.group(1)), text)


class IpScrubFilter(logging.Filter):
    """Фильтр обработчика: адрес в записи усекается до форматирования.

    У журнала доступа uvicorn аргументы — кортеж, первый элемент — адрес
    клиента: его формат читает `AccessFormatter`, поэтому меняется только он.
    Остальные записи получают уже подставленный и очищенный текст.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == _ACCESS_LOGGER and isinstance(record.args, tuple) and record.args:
            first, *rest = record.args
            record.args = (mask_ip(str(first)), *rest)
            return True
        message = record.getMessage()
        record.msg = scrub_ips(message)
        record.args = None
        return True


class PrivateFormatter(logging.Formatter):
    """Строка журнала с полями `extra` в виде `ключ=значение`, без IP."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD and not key.startswith("_")
        }
        if extras:
            line += " " + " ".join(
                f"{key}={json.dumps(value, ensure_ascii=False, default=str)}"
                for key, value in sorted(extras.items())
            )
        return scrub_ips(line)


class PrivateHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Пишет в текущий `sys.stderr`: его подменяют и uvicorn, и pytest."""

    def __init__(self) -> None:
        self._override: IO[str] | None = None
        super().__init__()
        self.setFormatter(PrivateFormatter())
        self.addFilter(IpScrubFilter())

    @property
    def stream(self) -> IO[str]:
        return self._override or sys.stderr

    @stream.setter
    def stream(self, value: IO[str] | None) -> None:
        self._override = None if value is None or value is sys.stderr else value


def _guard(handler: logging.Handler) -> None:
    if not any(isinstance(item, IpScrubFilter) for item in handler.filters):
        handler.addFilter(IpScrubFilter())


def configure_logging() -> PrivateHandler:
    """Один обработчик корня без IP; повторный вызов его не дублирует.

    Корень остаётся на WARNING, `domsignal.*` пишет с INFO. Обработчики
    uvicorn (он настраивает журналы раньше, чем импортирует приложение)
    получают тот же фильтр.
    """
    root = logging.getLogger()
    handler = next((item for item in root.handlers if isinstance(item, PrivateHandler)), None)
    if handler is None:
        handler = PrivateHandler()
        root.addHandler(handler)
    logging.getLogger("domsignal").setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", _ACCESS_LOGGER):
        for item in logging.getLogger(name).handlers:
            _guard(item)
    return handler


#: Пути, где сегмент — одноразовый секрет или ссылка-приглашение.
_SECRET_PATHS = re.compile(
    r"^(/admin/invite|/admin/reset|/company/apply/status|/join|/api/v1/notification-launch)"
    r"/[^/?]+"
)


def safe_path(path: str) -> str:
    """Путь запроса для журнала: без строки запроса и без секретных сегментов."""
    return _SECRET_PATHS.sub(lambda match: f"{match.group(1)}/[redacted]", path.split("?", 1)[0])


def access_fields(
    *,
    request_id: str,
    method: str,
    path: str,
    status: int,
    duration_ms: int,
    client_host: str | None,
) -> dict[str, Any]:
    """Поля строки `http_request`: без строки запроса и без полного адреса."""
    return {
        "request_id": request_id,
        "method": method,
        "path": safe_path(path),
        "status": status,
        "duration_ms": duration_ms,
        "client_net": mask_ip(client_host),
    }


__all__ = [
    "IPV4_PREFIX",
    "IPV6_PREFIX",
    "IpScrubFilter",
    "PrivateFormatter",
    "PrivateHandler",
    "access_fields",
    "configure_logging",
    "mask_ip",
    "safe_path",
    "scrub_ips",
]
