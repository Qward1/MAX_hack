"""REGION-MOW-2026-09-26: второй регион данными, не кодом.

10 подтипов × {Казань, Москва}: один код роутера, разные пакеты `regions/`
дают разные каналы и основания там, где различаются данные, и одинаковый
маршрут там, где действует общий федеральный слой.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from domsignal.services.routing import RoutingService, load_directory
from domsignal.tools.route_preview import REGION_COMPARISON, compare_regions, region_context

ROOT = Path(__file__).resolve().parents[2]
ROUTING = RoutingService(load_directory(ROOT / "regions"))

Cell = tuple[str, str | tuple[str, ...] | None, str | None]
#: Ожидание по строкам сравнения: (Казань, Москва) — тип маршрута, канал(ы), правило.
#: D4: в Казани у освещения, дорог и благоустройства — «Народный контроль» и ПОС.
KAZAN_BOTH = ("ru_ta_narodny_kontrol", "pos_gosuslugi")
EXPECTED: dict[str, tuple[Cell, Cell]] = {
    "street_lighting.failure": (
        ("municipality", KAZAN_BOTH, "ru_ta.street_lighting.narodny_kontrol"),
        ("municipality", "ru_mow_nash_gorod", "ru_mow.street_lighting.nash_gorod"),
    ),
    "road.damage": (
        ("municipality", KAZAN_BOTH, "ru_ta.road_damage.narodny_kontrol"),
        ("municipality", "ru_mow_nash_gorod", "ru_mow.road_damage.nash_gorod"),
    ),
    "snow.street": (
        ("municipality", "pos_gosuslugi", "federal.municipal_territory.default"),
        ("municipality", "ru_mow_nash_gorod", "ru_mow.snow_street.nash_gorod"),
    ),
    "landscaping.public": (
        ("municipality", KAZAN_BOTH, "ru_ta.landscaping.narodny_kontrol"),
        ("municipality", "ru_mow_nash_gorod", "ru_mow.landscaping.nash_gorod"),
    ),
    "waste.removal_regional": (
        ("regional_operator", None, "federal.waste_removal.regional_operator"),
        ("regional_operator", "ru_mow_nash_gorod", "ru_mow.waste_removal.nash_gorod"),
    ),
    # D4: заявку в УК житель может направить и сам — через «Госуслуги Дом».
    "elevator.stopped": (
        ("uk_internal", "gosuslugi_dom", None),
        ("uk_internal", "gosuslugi_dom", None),
    ),
    "water.hot_outage": (
        ("resource_supplier", None, "federal.external_network.resource_supplier"),
        ("resource_supplier", None, "federal.external_network.resource_supplier"),
    ),
    "gas.smell": (
        ("emergency_service", "emergency_112", "federal.gas_smell.emergency"),
        ("emergency_service", "emergency_112", "federal.gas_smell.emergency"),
    ),
    "playground.damaged": (("unknown", None, None), ("unknown", None, None)),
    "other.unspecified": (("unknown", None, None), ("unknown", None, None)),
}


def test_the_table_covers_ten_subtypes_in_two_regions() -> None:
    assert len(REGION_COMPARISON) == 10
    assert {row[0] for row in REGION_COMPARISON} == set(EXPECTED)


@pytest.mark.parametrize(("subtype", "scope", "routes"), compare_regions(ROUTING))
def test_same_code_different_data(subtype: str, scope: str, routes: dict[str, Any]) -> None:
    pair = (routes["RU-TA"], routes["RU-MOW"])
    for route, (route_type, channel, rule) in zip(pair, EXPECTED[subtype], strict=True):
        assert route.route_type == route_type, (subtype, route)
        expected = [channel] if isinstance(channel, str) else list(channel or ())
        assert [c.id for c in route.channels] == expected, subtype
        assert (route.basis.rule_id if route.basis else None) == rule, subtype
        # Ни один маршрут не называет непроверенную организацию.
        assert route.organization_name is None


def test_moscow_never_offers_the_pos_and_kazan_never_offers_nash_gorod() -> None:
    for _, _, routes in compare_regions(ROUTING):
        kazan, moscow = routes["RU-TA"], routes["RU-MOW"]
        assert "ru_mow_nash_gorod" not in {c.id for c in kazan.channels}
        assert "pos_gosuslugi" not in {c.id for c in moscow.channels}


def test_moscow_channel_facts_are_verbatim_and_sourced() -> None:
    route = ROUTING.route(
        subtype="road.damage",
        location_scope="municipal_territory",
        house=region_context("RU-MOW", "moscow"),
    )
    channel = route.channels[0]
    assert channel.url == "https://gorod.mos.ru/"
    assert channel.verification_status == "verified" and channel.verified_at
    assert all(fact.source_url and fact.source_url.startswith("https://") for fact in channel.facts)
    assert all("«" in fact.text for fact in channel.facts)  # дословные цитаты
    assert route.can_prepare_appeal is True
    assert "gorod.mos.ru" in (route.basis.source_url or "")
    assert "«Повреждение дорожного покрытия на проезжей части/тротуаре" in route.basis.text


def test_unavailability_is_a_federal_data_field_not_a_region_branch() -> None:
    federal = yaml.safe_load((ROOT / "regions/_federal/responsibility.yaml").read_text("utf-8"))
    pos = next(c for c in federal["channels"] if c["id"] == "pos_gosuslugi")
    assert pos["unavailable_regions"] == ["RU-MOW"]
    source = (ROOT / "src/domsignal/core/routing.py").read_text("utf-8")
    assert "RU-MOW" not in source and "moscow" not in source.lower()


def validator() -> Any:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validate_region_pack

        return validate_region_pack
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def layers() -> list[dict[str, Any]]:
    return [
        yaml.safe_load((ROOT / "regions" / name / "responsibility.yaml").read_text("utf-8"))
        for name in ("_federal", "RU-TA", "RU-MOW")
    ]


def test_validator_accepts_the_real_packs() -> None:
    documents = layers()
    assert all(validator().unavailable_channel_errors(documents, d) == [] for d in documents)


def test_validator_refuses_a_pack_offering_a_channel_unavailable_in_its_region() -> None:
    documents = layers()
    moscow = copy.deepcopy(documents[2])
    moscow["rules"][0]["channel_ids"] = ["pos_gosuslugi"]
    errors = validator().unavailable_channel_errors([documents[0], documents[1], moscow], moscow)
    assert errors == [("<root>.rules.0", "channel pos_gosuslugi is unavailable in RU-MOW")]
    # То же в муниципальной секции и для собственного канала слоя.
    moscow = copy.deepcopy(documents[2])
    moscow["municipalities"][0]["rules"] = [
        {**documents[2]["rules"][1], "id": "local", "channel_ids": ["pos_gosuslugi"]}
    ]
    moscow["channels"][0]["unavailable_regions"] = ["RU-MOW"]
    errors = validator().unavailable_channel_errors([documents[0], moscow], moscow)
    assert {location for location, _ in errors} == {
        "<root>.channels.0",
        "<root>.rules.0",
        "<root>.rules.1",
        "<root>.rules.2",
        "<root>.rules.3",
        "<root>.rules.4",
        "municipalities.0.rules.0",
    }


def test_csv_export_neutralises_formula_cells() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from domsignal.contracts.dashboards import CompanyDashboard, HouseStats
    from domsignal.contracts.quota import ChatQuotaView
    from domsignal.services.dashboards import company_csv

    house = HouseStats(
        house_id=uuid4(),
        address="=HYPERLINK(\"http://x\")",
        signals=1,
        tickets_open=0,
        tickets_created=0,
        tickets_closed=0,
        median_accept_minutes=None,
        verification_confirmed=0,
        verification_returned=0,
        top_categories=[],
    )
    dashboard = CompanyDashboard(
        period_days=7,
        generated_at=datetime.now(UTC),
        timezone="Europe/Moscow",
        scope="company",
        quota=ChatQuotaView(limit=None, used=0, remaining=None, over_limit=False, exhausted=False),
        houses=[house],
        activity=[],
    )
    text = company_csv(dashboard)
    assert text.startswith("﻿Адрес;")
    assert "\n'=HYPERLINK" in text.replace('"', "")
