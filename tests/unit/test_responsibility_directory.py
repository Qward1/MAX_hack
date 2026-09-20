"""Справочник ответственности: схема, перекрёстные ссылки и безопасная деградация."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from domsignal.ai.taxonomy import load_taxonomy
from domsignal.bootstrap import build_container
from domsignal.contracts.routing import LOCATION_SCOPES
from domsignal.core.responsibility import STALE_AFTER_DAYS
from domsignal.core.routing import UNAVAILABLE_DIRECTORY_VERSION, HouseRoutingContext
from domsignal.services.routing import (
    DirectoryLoadError,
    RoutingService,
    load_directory,
    load_directory_or_none,
)
from domsignal.settings import AppEnvironment, Settings

REGIONS = Path(__file__).resolve().parents[2] / "regions"
FEDERAL = REGIONS / "_federal" / "responsibility.yaml"


@pytest.fixture
def regions_copy(tmp_path: Path) -> Path:
    target = tmp_path / "regions"
    shutil.copytree(REGIONS, target)
    return target


def federal_document() -> Any:
    return yaml.safe_load(FEDERAL.read_text(encoding="utf-8"))


def test_packaged_directory_loads_with_layers() -> None:
    directory = load_directory(REGIONS)
    effective = directory.effective("RU-TA", "kazan")
    assert effective.version.startswith("_federal@")
    assert "RU-TA/kazan@" in effective.version
    assert effective.uk_default is not None
    assert effective.safety
    assert STALE_AFTER_DAYS == 180


def test_every_verified_record_names_its_source_and_date() -> None:
    directory = load_directory(REGIONS)
    effective = directory.effective("RU-TA", "kazan")
    records = [
        *effective.channels.values(),
        *effective.organizations.values(),
        *effective.rules,
    ]
    assert records
    for record in records:
        verification = record.verification
        if verification.status != "verified":
            continue
        assert verification.verified_at is not None
        assert verification.source_title


def test_rule_subtypes_and_scopes_stay_inside_the_shared_contract() -> None:
    codes = set(load_taxonomy().codes)
    effective = load_directory(REGIONS).effective("RU-TA", "kazan")
    for rule in effective.rules:
        assert set(rule.subtypes) <= codes, rule.id
        assert set(rule.location_scopes) <= set(LOCATION_SCOPES), rule.id
        if rule.organization_id is not None:
            assert rule.organization_id in effective.organizations
        for channel_id in rule.channel_ids:
            assert channel_id in effective.channels
    default = effective.uk_default
    assert default is not None
    assert set(default.subtypes) <= codes
    assert set(default.resource_supplier_alternatives) <= set(default.subtypes)


def test_unverified_channels_exist_in_data_but_never_in_a_route() -> None:
    directory = load_directory(REGIONS)
    effective = directory.effective("RU-TA", "kazan")
    unverified = [
        channel
        for channel in effective.channels.values()
        if channel.verification.status != "verified"
    ]
    assert unverified, "непроверенные каналы должны оставаться в данных"
    service = RoutingService(directory, known_subtypes=load_taxonomy().codes)
    house = HouseRoutingContext(
        region_code="RU-TA", municipality_code="kazan", has_active_connected_uk=True
    )
    hidden_ids = {channel.id for channel in unverified}
    for subtype in load_taxonomy().codes:
        for scope in LOCATION_SCOPES:
            route = service.route(subtype=subtype, location_scope=scope, house=house)
            assert hidden_ids.isdisjoint({channel.id for channel in route.channels})


def test_broken_layer_is_reported_and_never_crashes_the_service(regions_copy: Path) -> None:
    (regions_copy / "_federal" / "responsibility.yaml").write_text(
        "schema_version: 1\nlayer_id: _federal\n", encoding="utf-8"
    )
    with pytest.raises(DirectoryLoadError):
        load_directory(regions_copy)
    assert load_directory_or_none(regions_copy) is None
    service = RoutingService(None)
    route = service.route(
        subtype="elevator.doors",
        location_scope="house_common",
        house=HouseRoutingContext(has_active_connected_uk=True),
    )
    assert service.available is False
    assert route.route_type == "unknown"
    assert route.match == "none"
    assert route.directory_version == UNAVAILABLE_DIRECTORY_VERSION
    assert service.safety(HouseRoutingContext(), ("gas",)) is None


def test_unparsable_yaml_degrades_to_unknown(regions_copy: Path) -> None:
    (regions_copy / "_federal" / "safety.yaml").write_text("blocks: [", encoding="utf-8")
    assert load_directory_or_none(regions_copy) is None


def test_missing_layer_file_degrades_to_unknown(regions_copy: Path) -> None:
    (regions_copy / "_federal" / "responsibility.yaml").unlink()
    assert load_directory_or_none(regions_copy) is None


def test_verified_record_without_a_date_is_rejected(regions_copy: Path) -> None:
    document = federal_document()
    document["channels"][0]["verification"]["verified_at"] = None
    (regions_copy / "_federal" / "responsibility.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(DirectoryLoadError):
        load_directory(regions_copy)


def test_unknown_channel_reference_is_rejected(regions_copy: Path) -> None:
    document = federal_document()
    document["rules"][0]["channel_ids"] = ["does_not_exist"]
    (regions_copy / "_federal" / "responsibility.yaml").write_text(
        yaml.safe_dump(document, allow_unicode=True), encoding="utf-8"
    )
    directory = load_directory(regions_copy)
    service = RoutingService(directory, known_subtypes=load_taxonomy().codes)
    route = service.route(
        subtype="gas.smell",
        location_scope="unknown",
        house=HouseRoutingContext(region_code="RU-TA"),
    )
    assert route.channels == []
    assert route.hidden_unverified_channels == 1


def settings_for(regions_dir: Path) -> Settings:
    return Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+asyncpg://routing:routing@localhost/routing",
        static_dir="missing",
        regions_dir=str(regions_dir),
        _env_file=None,
    )


def test_container_starts_with_a_valid_and_with_a_missing_directory(tmp_path: Path) -> None:
    container = build_container(settings_for(REGIONS))
    assert container.routing.available is True
    empty = build_container(settings_for(tmp_path / "absent"))
    assert empty.routing.available is False
    route = empty.routing.route(
        subtype="elevator.doors",
        location_scope="house_common",
        house=HouseRoutingContext(has_active_connected_uk=True),
    )
    assert route.route_type == "unknown"
    card = empty.action_cards.build(
        route,
        HouseRoutingContext(has_active_connected_uk=True),
        audience="resident",
        source="chat",
    )
    assert card.safety is None
    assert [action.type for action in card.actions] == ["report_to_uk_anyway"]
