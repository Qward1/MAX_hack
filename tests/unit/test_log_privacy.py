"""P7b §2: в журналах нет полных IP-адресов клиентов.

Источник, найденный живым прогоном P7a, — журнал доступа uvicorn с
`--proxy-headers`: он писал адрес клиента из `X-Forwarded-For`. Теперь запрос
журналирует приложение (`http_request` с `request_id` и сетью /24 или /48), а
форматтер и фильтр усекают адрес в любой строке журнала.
"""

from __future__ import annotations

import io
import ipaddress
import logging
import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from uvicorn.logging import AccessFormatter, DefaultFormatter

from domsignal.logs import (
    IpScrubFilter,
    PrivateFormatter,
    configure_logging,
    mask_ip,
    safe_path,
    scrub_ips,
)
from domsignal.main import create_app
from domsignal.settings import Settings

ROOT = Path(__file__).resolve().parents[2]

CLIENT_V4 = "203.0.113.77"
CLIENT_V6 = "2001:db8:abcd:12:3456:7890:abcd:ef01"

_CANDIDATES = re.compile(
    r"(?<![\w.:])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])"
    r"|(?<![\w:.])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:.])"
)


def full_addresses(text: str) -> list[str]:
    """IP-адреса в тексте, кроме усечённых сетей вида `a.b.c.0/24`, `x:y:z::/48`."""
    found = []
    for match in _CANDIDATES.finditer(text):
        try:
            ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        if text[match.end() : match.end() + 1] == "/":
            continue
        found.append(match.group(0))
    return found


@pytest.fixture
def journal() -> Iterator[io.StringIO]:
    handler = configure_logging()
    buffer = io.StringIO()
    handler.setStream(buffer)
    try:
        yield buffer
    finally:
        handler.setStream(sys.stderr)


def test_mask_keeps_only_the_network() -> None:
    assert mask_ip(CLIENT_V4) == "203.0.113.0/24"
    assert mask_ip(f"{CLIENT_V4}:51234") == "203.0.113.0/24"
    assert mask_ip(CLIENT_V6) == "2001:db8:abcd::/48"
    assert mask_ip(f"[{CLIENT_V6}]:443") == "2001:db8:abcd::/48"
    assert mask_ip("::ffff:198.51.100.23") == "198.51.100.0/24"
    assert mask_ip("testclient") == "unknown"
    assert mask_ip(None) == "unknown"


def test_scrub_replaces_every_address_and_leaves_other_tokens() -> None:
    text = (
        f"from {CLIENT_V4}:40000 and [{CLIENT_V6}]:443 and {CLIENT_V6}, "
        "id 1f0c6a2e-1d2b-4c3d-9e8f-0a1b2c3d4e5f at 10:18:01.562, "
        "caddy 2.10.2, already 198.51.100.0/24"
    )
    scrubbed = scrub_ips(text)
    assert full_addresses(scrubbed) == []
    assert "203.0.113.0/24" in scrubbed and "2001:db8:abcd::/48" in scrubbed
    for kept in ("1f0c6a2e-1d2b-4c3d-9e8f-0a1b2c3d4e5f", "10:18:01.562", "2.10.2"):
        assert kept in scrubbed
    assert "198.51.100.0/24" in scrubbed and "/24/24" not in scrubbed
    assert scrub_ips(scrubbed) == scrubbed


def test_server_bind_and_loopback_addresses_are_not_client_data() -> None:
    line = "Uvicorn running on http://0.0.0.0:8000; probe 127.0.0.1:51234 and [::1]:8000"
    assert scrub_ips(line) == line


def test_secret_path_segments_are_not_logged() -> None:
    assert safe_path("/admin/invite/secret-token?x=1") == "/admin/invite/[redacted]"
    assert (
        safe_path("/api/v1/notification-launch/w_0123456789abcdefghijklmnopqrstuv")
        == "/api/v1/notification-launch/[redacted]"
    )
    assert safe_path("/api/v1/signals/1?section=signals") == "/api/v1/signals/1"


@pytest.mark.parametrize(
    ("client", "network"),
    [(CLIENT_V4, "203.0.113.0/24"), (CLIENT_V6, "2001:db8:abcd::/48")],
)
def test_application_access_log_has_request_id_and_truncated_network(
    journal: io.StringIO, client: str, network: str
) -> None:
    app = create_app(Settings(static_dir="missing", _env_file=None))
    with TestClient(app, client=(client, 50123), raise_server_exceptions=False) as http:
        response = http.get("/api/v1/me?token=private-query")
        quiet = http.get("/health")
    assert response.status_code == 401 and quiet.status_code == 200
    lines = [line for line in journal.getvalue().splitlines() if "http_request" in line]
    assert len(lines) == 1, "успешная проверка живости не журналируется"
    line = lines[0]
    assert f'request_id="{response.headers["X-Request-ID"]}"' in line
    assert f'client_net="{network}"' in line
    assert 'path="/api/v1/me"' in line and "private-query" not in line
    assert 'status=401' in line and 'method="GET"' in line
    assert client not in journal.getvalue()
    assert full_addresses(journal.getvalue()) == []


def test_application_records_and_tracebacks_are_scrubbed(journal: io.StringIO) -> None:
    logger = logging.getLogger("domsignal.test_log_privacy")
    logger.warning("upstream %s refused", f"{CLIENT_V4}:8000", extra={"peer": CLIENT_V6})
    try:
        raise ConnectionError(f"connect to {CLIENT_V4} failed")
    except ConnectionError:
        logger.exception("delivery_failed")
    output = journal.getvalue()
    assert "upstream 203.0.113.0/24 refused" in output
    assert 'peer="2001:db8:abcd::/48"' in output
    assert "connect to 203.0.113.0/24 failed" in output
    assert full_addresses(output) == []


def test_uvicorn_access_and_error_records_are_scrubbed() -> None:
    access = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        (f"{CLIENT_V4}:51234", "GET", "/api/v1/me", "1.1", 200),
        None,
    )
    assert IpScrubFilter().filter(access)
    access_line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s').format(
        access
    )
    assert access_line.startswith("203.0.113.0/24 - ")
    error = logging.LogRecord(
        "uvicorn.error", logging.WARNING, "", 0, "Invalid request from %s", (CLIENT_V6,), None
    )
    assert IpScrubFilter().filter(error)
    error_line = DefaultFormatter("%(message)s").format(error)
    assert error_line == "Invalid request from 2001:db8:abcd::/48"
    assert full_addresses(access_line + error_line) == []


def test_configure_logging_guards_uvicorn_handlers_and_is_idempotent() -> None:
    uvicorn_handler = logging.StreamHandler(io.StringIO())
    uvicorn_logger = logging.getLogger("uvicorn.error")
    uvicorn_logger.addHandler(uvicorn_handler)
    try:
        first = configure_logging()
        second = configure_logging()
        assert first is second
        assert sum(isinstance(h, type(first)) for h in logging.getLogger().handlers) == 1
        assert any(isinstance(f, IpScrubFilter) for f in uvicorn_handler.filters)
        assert logging.getLogger("domsignal").level == logging.INFO
        # Журналы HTTP-клиента (адрес с идентификатором получателя MAX) не выводятся.
        assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    finally:
        uvicorn_logger.removeHandler(uvicorn_handler)


def test_private_formatter_output_has_no_full_address() -> None:
    record = logging.LogRecord(
        "domsignal.x", logging.INFO, "", 0, "peer %s", (CLIENT_V4,), None
    )
    assert full_addresses(PrivateFormatter().format(record)) == []


# ------------------------------------------------------------ развёртывание


def test_production_api_has_no_uvicorn_access_log() -> None:
    compose = yaml.safe_load((ROOT / "compose.prod.yaml").read_text("utf-8"))
    command = compose["services"]["api"]["command"]
    assert "--proxy-headers" in command and "--no-access-log" in command
    dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
    assert '"--no-access-log"]' in dockerfile.splitlines()[-1]


def test_every_production_container_rotates_its_log() -> None:
    compose = yaml.safe_load((ROOT / "compose.prod.yaml").read_text("utf-8"))
    base = yaml.safe_load((ROOT / "compose.yaml").read_text("utf-8"))
    services = set(base["services"]) | set(compose["services"])
    assert services >= {"db", "migrate", "seed", "api", "worker", "ai-worker", "caddy"}
    for name in services:
        logging_config = compose["services"][name].get("logging")
        assert logging_config == {
            "driver": "json-file",
            "options": {"max-size": "10m", "max-file": "5"},
        }, name


def test_caddy_masks_client_addresses_in_its_own_log() -> None:
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text("utf-8")
    assert "request>remote_ip ip_mask 24 48" in caddyfile
    assert "request>client_ip ip_mask 24 48" in caddyfile
    assert "request>headers>X-Forwarded-For delete" in caddyfile
    # Журнала доступа у сайта нет: директива `log` есть только в глобальном блоке.
    site = caddyfile.split("{$PUBLIC_DOMAIN}", 1)[1]
    assert "\tlog" not in site and "log {" not in site
