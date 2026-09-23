"""P7b: расхождения роутера с эталоном маршрутов P6 и выключатель модели окон.

Эталон `datasets/routing/route_reference.v1.jsonl` (DEV-A, P6) — «подтип ×
территория × опасность → тип маршрута». Роутер давал 68/76; здесь закреплены
75/76 с одним осознанным расхождением и каждая исправленная строка. Экстренные правила — только с дословной
цитатой официальной публикации (Правила, утв. ПП РФ № 2071, п. 21).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from domsignal.bootstrap import build_container
from domsignal.core.routing import HouseRoutingContext, RoutingQuery, resolve_route
from domsignal.services.routing import load_directory
from domsignal.settings import Settings
from tests.contract.test_production_compose import MODEL, SYNTHETIC_VPS, environment
from tests.unit.test_routing_core import SUBTYPES

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "datasets" / "routing" / "route_reference.v1.jsonl"
TODAY = date(2026, 9, 23)
PP2071 = "http://publication.pravo.gov.ru/document/0001202111300024"


@pytest.fixture(scope="module")
def directory() -> Any:
    return load_directory(ROOT / "regions")


def house(territory: str = "mixed", uk: bool = True) -> HouseRoutingContext:
    return HouseRoutingContext(
        is_demo=False,
        has_active_connected_uk=uk,
        region_code="RU-TA",
        municipality_code="kazan",
        territory_policy=territory,  # type: ignore[arg-type]
    )


def route_type(
    directory: Any, subtype: str, scope: str, danger: tuple[str, ...] = (), **kw: Any
) -> str:
    route = resolve_route(
        RoutingQuery(
            subtype=subtype,
            location_scope=scope,  # type: ignore[arg-type]
            house=house(**kw),
            danger_kinds=danger,  # type: ignore[arg-type]
        ),
        directory,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )
    return "operator_choice" if route.requires_operator_choice else str(route.route_type)


#: Осознанное расхождение с эталоном: форма с категорией создаёт заявку УК без
#: подтипа (`other.unspecified`), и её карточка остаётся картой УК.
KNOWN_DEVIATIONS = {("other.unspecified", "house_common", None, "unknown")}


def test_the_router_matches_the_p6_route_reference(directory: Any) -> None:
    rows = [json.loads(line) for line in REFERENCE.read_text("utf-8").splitlines() if line]
    assert len(rows) == 76
    wrong = [
        (row["subtype"], row["location_scope"], row["danger_kind"], row["expected_route_type"])
        for row in rows
        if route_type(
            directory,
            row["subtype"],
            row["location_scope"],
            (row["danger_kind"],) if row["danger_kind"] else (),
        )
        != row["expected_route_type"]
    ]
    assert set(wrong) == KNOWN_DEVIATIONS


@pytest.mark.parametrize(
    ("subtype", "scope", "danger", "expected"),
    [
        # Правило ресурсоснабжающей организации знает и отключение воды.
        ("water.hot_outage", "external_network", (), "resource_supplier"),
        ("water.supply_outage", "external_network", (), "resource_supplier"),
        # Правило по подтипу точнее «общего имущества + УК» и политики двора.
        ("gas.supply_outage", "house_common", (), "resource_supplier"),
        ("waste.removal_regional", "house_territory", (), "regional_operator"),
        # Неопределённый подтип в общем имуществе — УК (осознанное расхождение).
        ("other.unspecified", "house_common", (), "uk_internal"),
        # Прочие подтипы общего имущества по-прежнему у УК.
        ("power.grid_outage", "house_common", (), "uk_internal"),
        ("elevator.stopped", "house_common", (), "uk_internal"),
        # Холодные батареи в квартире — общедомовая система, течь — уточнение.
        ("heating.cold_radiators", "apartment", (), "uk_internal"),
        ("water.leak", "apartment", (), "unknown"),
        # Опасность обрушения и иная угроза жизни — 112 по п. 21 «б» и «г».
        ("structure.damage", "house_common", ("structural",), "emergency_service"),
        ("other.unspecified", "house_common", ("other_hazard",), "emergency_service"),
    ],
)
def test_each_fixed_reference_row(
    directory: Any, subtype: str, scope: str, danger: tuple[str, ...], expected: str
) -> None:
    assert route_type(directory, subtype, scope, danger) == expected


def test_apartment_radiators_need_a_connected_company(directory: Any) -> None:
    assert route_type(directory, "heating.cold_radiators", "apartment", uk=False) == "unknown"


@pytest.mark.parametrize(
    ("rule_id", "danger", "item", "quote"),
    [
        (
            "federal.structural.emergency",
            "structural",
            "б",
            "«привлечение службы реагирования в чрезвычайных ситуациях осуществляется при "
            "необходимости проведения аварийно-спасательных работ",
        ),
        (
            "federal.other_hazard.emergency",
            "other_hazard",
            "г",
            "«привлечение службы скорой медицинской помощи осуществляется при сообщениях об "
            "угрозе жизни и (или) здоровью",
        ),
    ],
)
def test_new_emergency_rules_quote_the_official_publication(
    directory: Any, rule_id: str, danger: str, item: str, quote: str
) -> None:
    effective = directory.effective("RU-TA", "kazan")
    rule = next(rule for rule in effective.rules if rule.id == rule_id)
    assert rule.route_type == "emergency_service" and rule.danger_kinds == (danger,)
    assert rule.subtypes == ()
    assert quote in rule.basis.text
    assert f"п. 21 «{item}»" in rule.basis.source_title
    assert rule.basis.source_url == PP2071
    assert rule.verification.status == "verified"


# ------------------------------------------------------------ выключатель модели


def _container(**overrides: Any) -> Any:
    settings = Settings(
        _env_file=None,
        static_dir="missing",
        llm_provider="openai_compatible",
        llm_api_key="synthetic-model-key",
        llm_model="openai/gpt-5-mini",
        **overrides,
    )
    return build_container(settings)


def test_passive_windows_use_the_model_by_default() -> None:
    container = _container()
    assert container.settings.passive_llm_enabled is True
    assert container.passive_analysis.analyzer.provider is not None
    assert container.passive_analysis.budget is not None


def test_the_switch_sends_windows_to_rules_and_keeps_the_report_model() -> None:
    container = _container(passive_llm_enabled=False)
    assert container.passive_analysis.analyzer.provider is None
    assert container.passive_analysis.budget is None
    # Явный путь `/report` модель сохраняет.
    assert container.explicit_reports.analyzer.provider is not None


def test_production_compose_passes_the_switch_on_by_default() -> None:
    env = environment("ai-worker", {**SYNTHETIC_VPS, **MODEL})
    assert env["PASSIVE_LLM_ENABLED"] == "true"
    off = environment("ai-worker", {**SYNTHETIC_VPS, **MODEL, "PASSIVE_LLM_ENABLED": "false"})
    assert off["PASSIVE_LLM_ENABLED"] == "false"
