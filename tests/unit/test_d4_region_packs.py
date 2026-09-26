"""D4, В-3/В-4: каждый пакет из `regions/` проходит одни и те же проверки.

Новый регион подключается пакетом данных: тест находит пакеты сам, поэтому
регион, добавленный без изменения кода, проверяется так же, как Казань и Москва.
"""

from __future__ import annotations

import sys
import zoneinfo
from pathlib import Path
from typing import Any

import pytest
import yaml

from domsignal.services.routing import FEDERAL_DIR, RoutingService, load_directory
from domsignal.tools.route_preview import REGION_COMPARISON, compare_regions, regions

ROOT = Path(__file__).resolve().parents[2]
ROUTING = RoutingService(load_directory(ROOT / "regions"))
PACKS = sorted(
    path.parent.name
    for path in (ROOT / "regions").glob("*/responsibility.yaml")
    if path.parent.name != FEDERAL_DIR
)
ROUTE_TYPES = {
    "uk_internal",
    "municipality",
    "resource_supplier",
    "emergency_service",
    "regional_operator",
    "other_authority",
    "unknown",
}


def document(code: str) -> dict[str, Any]:
    path = ROOT / "regions" / code / "responsibility.yaml"
    loaded: dict[str, Any] = yaml.safe_load(path.read_text("utf-8"))
    return loaded


def unavailable() -> dict[str, set[str]]:
    """Канал → регионы, где он недоступен (данные всех слоёв)."""
    result: dict[str, set[str]] = {}
    for code in [FEDERAL_DIR, *PACKS]:
        layer = document(code)
        sections = [layer, *(layer.get("municipalities") or [])]
        for section in sections:
            for channel in section.get("channels") or []:
                result[channel["id"]] = set(channel.get("unavailable_regions") or [])
    return result


def test_the_validator_is_green_for_every_pack() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validate_region_pack
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    assert validate_region_pack.main() == 0


def test_every_pack_is_offered_for_comparison() -> None:
    assert len(PACKS) >= 2
    assert [code for _, code, _ in regions(ROUTING)] == PACKS


@pytest.mark.parametrize("code", PACKS)
def test_the_pack_names_its_region_and_an_existing_time_zone(code: str) -> None:
    layer = document(code)
    assert layer["region"] == code and layer["name"]
    assert layer["timezone"] in zoneinfo.available_timezones()
    assert ROUTING.directory is not None
    assert ROUTING.directory.timezone_for(code) == layer["timezone"]


@pytest.mark.parametrize(("subtype", "scope", "routes"), compare_regions(ROUTING))
def test_ten_subtypes_route_or_stay_honestly_unknown(
    subtype: str, scope: str, routes: dict[str, Any]
) -> None:
    assert set(routes) == set(PACKS)
    closed = unavailable()
    for code, route in routes.items():
        assert route.route_type in ROUTE_TYPES, (code, subtype)
        # Непроверенная организация не называется ни в одном регионе.
        assert route.organization_name is None, (code, subtype)
        for channel in route.channels:
            assert channel.verification_status == "verified", (code, subtype, channel.id)
            # Недоступный в регионе канал не предлагается.
            assert code not in closed.get(channel.id, set()), (code, subtype, channel.id)
        if route.route_type == "unknown":
            assert route.channels == [], (code, subtype)


def test_the_comparison_has_ten_subtypes() -> None:
    assert len(REGION_COMPARISON) == 10
