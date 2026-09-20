"""Табличные проверки Responsibility Router: маршрут, видимость и честный unknown."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from domsignal.ai.contracts import DANGER_KINDS as AI_DANGER_KINDS
from domsignal.ai.contracts import LOCATION_SCOPES as AI_LOCATION_SCOPES
from domsignal.ai.taxonomy import UNSPECIFIED, load_taxonomy
from domsignal.contracts.routing import DANGER_KINDS, LOCATION_SCOPES
from domsignal.core.responsibility import build_directory
from domsignal.core.routing import (
    UNSPECIFIED_SUBTYPE,
    HouseRoutingContext,
    RoutingQuery,
    resolve_route,
    safety_block,
)
from domsignal.services.routing import load_directory

TODAY = date(2026, 9, 20)
SUBTYPES = tuple(load_taxonomy().codes)
REGIONS = Path(__file__).resolve().parents[2] / "regions"


def verified(day: str = "2026-09-20") -> dict[str, Any]:
    return {
        "status": "verified",
        "verified_at": day,
        "verified_by": "тест",
        "source_title": "Тестовый источник",
        "source_url": None,
    }


def unverified() -> dict[str, Any]:
    return {"status": "needs_verification", "source_title": "Не сверено"}


def basis(text: str = "Тестовое основание") -> dict[str, Any]:
    return {"text": text, "source_title": "Тестовый источник", "source_url": None}


def channel(identifier: str, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": identifier,
        "organization_id": None,
        "channel_type": "official_web",
        "label": f"Канал {identifier}",
        "url": "https://example.invalid/channel",
        "phone": None,
        "entry_hint": None,
        "routes_to_competent_authority": False,
        "facts": [],
        "unavailable_regions": [],
        "verification": verified(),
    }
    entry.update(overrides)
    return entry


def rule(identifier: str, subtypes: list[str], **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": identifier,
        "priority": 100,
        "match": {"subtypes": subtypes, "location_scopes": []},
        "route_type": "municipality",
        "organization_id": None,
        "channel_ids": [],
        "can_prepare_appeal": False,
        "basis": basis(),
        "verification": verified(),
    }
    entry.update(overrides)
    return entry


def layer(layer_id: str, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "schema_version": 1,
        "layer_id": layer_id,
        "layer": "federal" if layer_id == "_federal" else "region",
        "region": None if layer_id == "_federal" else layer_id,
        "version": "1",
        "updated_at": "2026-09-20",
        "organizations": [],
        "channels": [],
        "rules": [],
        "municipalities": [],
    }
    entry.update(overrides)
    return entry


UK_DEFAULT = {
    "subtypes": ["elevator.doors", "water.hot_outage", "lighting.stairwell"],
    "resource_supplier_alternatives": ["water.hot_outage"],
    "basis": basis("Общее имущество дома"),
    "verification": unverified(),
}


def synthetic() -> Any:
    federal = layer(
        "_federal",
        organizations=[
            {
                "id": "verified_org",
                "name": "Проверенная организация",
                "kind": "municipality",
                "region": None,
                "municipality": None,
                "verification": verified(),
            },
            {
                "id": "unverified_org",
                "name": "Непроверенный орган",
                "kind": "other_authority",
                "region": None,
                "municipality": None,
                "verification": unverified(),
            },
        ],
        channels=[
            channel("open_web", routes_to_competent_authority=True),
            channel("hidden_web", verification=unverified()),
            channel("demo_web", verification={"status": "demo", "source_title": "Демо"}),
            channel("stale_web", verification=verified("2020-01-01")),
            channel("regional_web", unavailable_regions=["RU-MOW"]),
            channel(
                "no_url_web",
                url=None,
                entry_hint="Госуслуги → «Сообщите, что вас волнует»",
                routes_to_competent_authority=True,
            ),
        ],
        rules=[
            rule(
                "lighting",
                ["street_lighting.failure"],
                match={
                    "subtypes": ["street_lighting.failure"],
                    "location_scopes": ["municipal_territory"],
                },
                channel_ids=["regional_web"],
                can_prepare_appeal=True,
            ),
            rule("hidden", ["road.damage"], channel_ids=["hidden_web"]),
            rule("demo", ["snow.street"], channel_ids=["demo_web"]),
            rule("stale", ["landscaping.public"], channel_ids=["stale_web"]),
            rule("named", ["waste.container_site"], organization_id="verified_org"),
            rule("unnamed", ["playground.damaged"], organization_id="unverified_org"),
            rule(
                "emergency",
                ["gas.smell"],
                priority=10,
                route_type="emergency_service",
                channel_ids=["open_web"],
            ),
            rule("regional_operator", ["waste.removal_regional"], route_type="regional_operator"),
            rule("override_me", ["intercom.broken"], route_type="municipality"),
            rule("conflict_a", ["snow.yard"], route_type="municipality"),
            rule("conflict_b", ["snow.yard"], route_type="resource_supplier"),
            rule("appeal", ["water.quality"], channel_ids=["no_url_web"], can_prepare_appeal=True),
        ],
        uk_default=UK_DEFAULT,
    )
    region = layer(
        "RU-TA",
        rules=[rule("override_me", ["intercom.broken"], route_type="other_authority")],
        municipalities=[{"code": "kazan", "name": "Казань", "rules": [], "channels": []}],
    )
    return build_directory(federal=federal, regions={"RU-TA": region})


@pytest.fixture(scope="module")
def directory() -> Any:
    return synthetic()


@pytest.fixture(scope="module")
def packaged() -> Any:
    return load_directory(REGIONS)


def kazan(**overrides: Any) -> HouseRoutingContext:
    values: dict[str, Any] = {
        "is_demo": False,
        "has_active_connected_uk": True,
        "region_code": "RU-TA",
        "municipality_code": "kazan",
        "territory_policy": "unknown",
    }
    values.update(overrides)
    return HouseRoutingContext(**values)


def route(directory: Any, subtype: str, scope: str, house: HouseRoutingContext) -> Any:
    return resolve_route(
        RoutingQuery(subtype=subtype, location_scope=scope, house=house),
        directory,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )


def test_product_scopes_match_the_ai_contract() -> None:
    assert LOCATION_SCOPES == AI_LOCATION_SCOPES
    assert DANGER_KINDS == AI_DANGER_KINDS
    assert UNSPECIFIED_SUBTYPE == UNSPECIFIED


@pytest.mark.parametrize(
    ("subtype", "scope", "house", "expected", "choice"),
    [
        ("elevator.doors", "house_common", kazan(), "uk_internal", False),
        ("elevator.doors", "house_common", kazan(has_active_connected_uk=False), "unknown", False),
        ("street_lighting.failure", "municipal_territory", kazan(), "municipality", False),
        ("road.damage", "municipal_territory", kazan(), "municipality", False),
        ("gas.smell", "house_common", kazan(), "emergency_service", False),
        ("gas.smell", "unknown", kazan(), "emergency_service", False),
        ("waste.removal_regional", "unknown", kazan(), "regional_operator", False),
        ("snow.yard", "unknown", kazan(), "unknown", True),
        ("intercom.broken", "unknown", kazan(), "other_authority", False),
        ("intercom.broken", "unknown", kazan(region_code=None), "municipality", False),
        (
            "playground.damaged",
            "house_territory",
            kazan(territory_policy="uk"),
            "uk_internal",
            False,
        ),
        (
            "street_lighting.failure",
            "house_territory",
            kazan(territory_policy="municipal"),
            "municipality",
            False,
        ),
        ("playground.damaged", "house_territory", kazan(territory_policy="mixed"), "unknown", True),
        (
            "playground.damaged",
            "house_territory",
            kazan(territory_policy="unknown"),
            "unknown",
            True,
        ),
        (
            "playground.damaged",
            "house_territory",
            kazan(territory_policy="municipal"),
            "municipality",
            False,
        ),
        (
            "cleaning.stairwell",
            "house_territory",
            kazan(territory_policy="municipal"),
            "unknown",
            False,
        ),
        ("made.up.code", "unknown", kazan(), "unknown", False),
        ("other.unspecified", "house_common", kazan(), "uk_internal", False),
        ("water.hot_outage", "house_common", kazan(), "uk_internal", False),
        ("water.quality", "unknown", kazan(), "municipality", False),
    ],
)
def test_route_table(
    directory: Any,
    subtype: str,
    scope: str,
    house: HouseRoutingContext,
    expected: str,
    choice: bool,
) -> None:
    resolved = route(directory, subtype, scope, house)
    assert resolved.route_type == expected
    assert resolved.requires_operator_choice is choice


def test_unknown_subtype_collapses_to_unspecified(directory: Any) -> None:
    resolved = route(directory, "не существует", "unknown", kazan())
    assert resolved.route_type == "unknown"
    assert resolved.match == "none"
    assert resolved.organization_name is None
    assert resolved.channels == []


def test_needs_verification_channel_is_hidden_and_counted(directory: Any) -> None:
    resolved = route(directory, "road.damage", "municipal_territory", kazan())
    assert resolved.channels == []
    assert resolved.hidden_unverified_channels == 1


def test_demo_channel_is_visible_only_for_a_demo_house(directory: Any) -> None:
    ordinary = route(directory, "snow.street", "municipal_territory", kazan())
    demo = route(directory, "snow.street", "municipal_territory", kazan(is_demo=True))
    assert ordinary.channels == [] and ordinary.hidden_unverified_channels == 1
    assert [item.id for item in demo.channels] == ["demo_web"]
    assert demo.hidden_unverified_channels == 0


def test_old_verification_is_marked_stale(directory: Any) -> None:
    resolved = route(directory, "landscaping.public", "municipal_territory", kazan())
    assert resolved.stale is True
    assert resolved.channels[0].stale is True


def test_unavailable_region_removes_the_channel(directory: Any) -> None:
    kazan_route = route(directory, "street_lighting.failure", "municipal_territory", kazan())
    moscow = route(
        directory,
        "street_lighting.failure",
        "municipal_territory",
        kazan(region_code="RU-MOW", municipality_code=None),
    )
    assert [item.id for item in kazan_route.channels] == ["regional_web"]
    assert kazan_route.can_prepare_appeal is True
    assert moscow.channels == []
    assert moscow.hidden_unverified_channels == 0
    assert moscow.can_prepare_appeal is False


def test_unverified_organization_is_never_named(directory: Any) -> None:
    named = route(directory, "waste.container_site", "unknown", kazan())
    unnamed = route(directory, "playground.damaged", "unknown", kazan())
    assert named.organization_name == "Проверенная организация"
    assert unnamed.organization_id is None and unnamed.organization_name is None


def test_lower_layer_overrides_a_rule_with_the_same_id(directory: Any) -> None:
    assert route(directory, "intercom.broken", "unknown", kazan()).route_type == "other_authority"
    without_region = route(directory, "intercom.broken", "unknown", kazan(region_code=None))
    assert without_region.route_type == "municipality"


def test_equal_rules_ask_the_operator(directory: Any) -> None:
    resolved = route(directory, "snow.yard", "unknown", kazan())
    assert resolved.requires_operator_choice is True
    assert {item.route_type for item in resolved.alternatives} == {
        "municipality",
        "resource_supplier",
    }
    assert resolved.organization_name is None


def test_house_territory_choice_lists_both_routes(directory: Any) -> None:
    resolved = route(directory, "playground.damaged", "house_territory", kazan())
    assert resolved.requires_operator_choice is True
    assert [item.route_type for item in resolved.alternatives] == ["uk_internal", "municipality"]
    without_uk = route(
        directory,
        "playground.damaged",
        "house_territory",
        kazan(has_active_connected_uk=False),
    )
    assert [item.route_type for item in without_uk.alternatives] == ["municipality"]


def test_hot_water_keeps_the_resource_supplier_alternative(directory: Any) -> None:
    resolved = route(directory, "water.hot_outage", "house_common", kazan())
    assert resolved.route_type == "uk_internal"
    assert [item.route_type for item in resolved.alternatives] == ["resource_supplier"]
    assert resolved.can_create_ticket is True
    assert resolved.automatic_integration is True


def test_packaged_directory_routes_the_five_demo_behaviours(packaged: Any) -> None:
    house = kazan(is_demo=True)
    assert route(packaged, "elevator.doors", "house_common", house).route_type == "uk_internal"
    municipal = route(packaged, "street_lighting.failure", "municipal_territory", house)
    assert municipal.route_type == "municipality"
    assert [item.id for item in municipal.channels] == ["pos_gosuslugi"]
    assert municipal.organization_id is None
    emergency = route(packaged, "gas.smell", "house_common", house)
    assert emergency.route_type == "emergency_service"
    assert [item.phone for item in emergency.channels] == ["112"]
    assert route(packaged, "playground.damaged", "house_territory", house).requires_operator_choice
    assert route(packaged, "other.unspecified", "unknown", house).route_type == "unknown"


def test_packaged_directory_hides_moscow_channel_and_unverified_records(packaged: Any) -> None:
    moscow = resolve_route(
        RoutingQuery(
            subtype="street_lighting.failure",
            location_scope="municipal_territory",
            house=HouseRoutingContext(region_code="RU-MOW", has_active_connected_uk=True),
        ),
        packaged,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )
    assert moscow.route_type == "municipality"
    assert moscow.channels == []
    waste = route(packaged, "waste.removal_regional", "unknown", kazan())
    assert waste.route_type == "regional_operator"
    assert waste.channels == []
    assert waste.basis is not None and waste.basis.verification_status == "needs_verification"


def test_packaged_safety_block_is_verified(packaged: Any) -> None:
    block = safety_block(packaged, ("gas",), kazan())
    assert block is not None
    assert block.phone == "112"
    assert block.steps == []
    assert block.verified_at == date(2026, 9, 20)
    assert safety_block(packaged, (), kazan()) is not None
