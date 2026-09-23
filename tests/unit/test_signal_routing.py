"""P5: маршрут по виду опасности, выбор маршрута оператором, настройки и тексты очереди."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from domsignal.core.responsibility import DirectoryError, Rule
from domsignal.core.routing import RoutingQuery, resolve_route, route_of_type
from domsignal.services.routing import DirectoryLoadError, load_directory
from domsignal.services.signal_inbox import CHOOSABLE_ROUTES, route_choices
from domsignal.services.signal_texts import (
    STRENGTH_REASONS,
    TICKET_DESCRIPTION_LIMIT,
    quoted_value,
    strength_reason_text,
    ticket_description,
)
from domsignal.services.signals import PassiveConfig
from domsignal.settings import AppEnvironment, Settings
from tests.unit.test_routing_core import SUBTYPES, basis, kazan, rule, verified

ROOT = Path(__file__).resolve().parents[2]
REGIONS = ROOT / "regions"
TODAY = date(2026, 9, 23)


@pytest.fixture(scope="module")
def packaged() -> Any:
    return load_directory(REGIONS)


def resolve(directory: Any, subtype: str, scope: str, danger: tuple[str, ...] = ()) -> Any:
    return resolve_route(
        RoutingQuery(
            subtype=subtype,
            location_scope=scope,  # type: ignore[arg-type]
            danger_kinds=danger,  # type: ignore[arg-type]
            house=kazan(),
        ),
        directory,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )


# ------------------------------------------------- таблица совпадения с опасностью


@pytest.mark.parametrize(
    ("subtype", "scope", "danger", "expected"),
    [
        # Предварительный сигнал о газе ещё без подтипа — уже экстренная служба.
        ("other.unspecified", "unknown", ("gas",), "emergency_service"),
        ("gas.smell", "house_common", (), "emergency_service"),
        ("gas.smell", "house_common", ("gas",), "emergency_service"),
        # Опасность ортогональна маршруту: у других видов правил нет.
        ("other.unspecified", "unknown", ("flooding",), "unknown"),
        ("other.unspecified", "unknown", ("smoke_fire",), "unknown"),
        ("other.unspecified", "unknown", ("person_trapped",), "unknown"),
        ("water.leak", "house_common", ("flooding",), "uk_internal"),
        ("elevator.stopped", "house_common", ("person_trapped",), "uk_internal"),
        # Газ ведёт в экстренную службу и при подтипе общего имущества.
        ("elevator.stopped", "house_common", ("gas",), "emergency_service"),
    ],
)
def test_route_by_danger_kind_table(
    packaged: Any, subtype: str, scope: str, danger: tuple[str, ...], expected: str
) -> None:
    route = resolve(packaged, subtype, scope, danger)
    assert route.route_type == expected
    if expected == "emergency_service":
        assert [channel.id for channel in route.channels] == ["emergency_112"]
        assert route.basis is not None and route.basis.rule_id == "federal.gas_smell.emergency"


def test_the_federal_gas_rule_matches_by_subtype_and_by_danger(packaged: Any) -> None:
    gas = next(item for item in packaged.federal.rules if item.id == "federal.gas_smell.emergency")
    assert gas.subtypes == ("gas.smell",) and gas.danger_kinds == ("gas",)
    assert gas.matches("gas.smell", "unknown")
    assert gas.matches("other.unspecified", "unknown", ("gas",))
    assert not gas.matches("other.unspecified", "unknown", ("flooding",))
    others = [item for item in packaged.federal.rules if item.danger_kinds]
    assert [item.id for item in others] == ["federal.gas_smell.emergency"]


def test_no_smoke_fire_rule_without_a_quoted_article() -> None:
    document = yaml.safe_load((REGIONS / "_federal" / "responsibility.yaml").read_text("utf-8"))
    kinds = [kind for item in document["rules"] for kind in item["match"].get("danger_kinds", [])]
    assert kinds == ["gas"]


def test_location_scope_still_filters_a_danger_match() -> None:
    parsed = Rule.parse(
        rule(
            "r.danger",
            [],
            route_type="emergency_service",
            match={"danger_kinds": ["gas"], "location_scopes": ["house_common"]},
        ),
        "rule",
        layer_id="_federal",
        layer_depth=0,
    )
    assert parsed.matches("other.unspecified", "house_common", ("gas",))
    assert not parsed.matches("other.unspecified", "apartment", ("gas",))


@pytest.mark.parametrize(
    ("match", "route_type", "message"),
    [
        ({"danger_kinds": ["flooding"]}, "municipality", "only for emergency_service"),
        ({"subtypes": [], "danger_kinds": []}, "emergency_service", "must not be empty"),
        ({"danger_kinds": ["tsunami"]}, "emergency_service", "danger_kinds"),
    ],
)
def test_parse_rejects_danger_kinds_outside_emergency_rules(
    match: dict[str, Any], route_type: str, message: str
) -> None:
    with pytest.raises(DirectoryError, match=message):
        Rule.parse(
            rule("r.bad", [], route_type=route_type, match=match),
            "rule",
            layer_id="_federal",
            layer_depth=0,
        )


# ------------------------------------------------------------- схема и валидатор


def schema() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((REGIONS / "responsibility.schema.json").read_text("utf-8")),
        format_checker=FormatChecker(),
    )


def schema_rule(match: dict[str, Any], route_type: str = "emergency_service") -> dict[str, Any]:
    return {
        "id": "r.schema",
        "priority": 10,
        "match": match,
        "route_type": route_type,
        "basis": basis(),
        "verification": verified(),
    }


def test_schema_accepts_danger_kinds_without_subtypes() -> None:
    errors = list(
        schema().iter_errors({"rules": [schema_rule({"danger_kinds": ["gas"]})], **_layer_head()})
    )
    assert errors == []


def test_schema_needs_subtypes_or_danger_kinds() -> None:
    errors = list(
        schema().iter_errors({"rules": [schema_rule({"location_scopes": []})], **_layer_head()})
    )
    assert errors, "правило без подтипов и видов опасности не проходит схему"
    unknown = list(
        schema().iter_errors(
            {"rules": [schema_rule({"danger_kinds": ["tsunami"]})], **_layer_head()}
        )
    )
    assert unknown


def _layer_head() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "layer_id": "_federal",
        "layer": "federal",
        "version": "1",
        "updated_at": "2026-09-23",
    }


def validator_module() -> Any:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validate_region_pack

        return validate_region_pack
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_validator_allows_danger_kinds_only_on_emergency_rules() -> None:
    module = validator_module()
    assert module.danger_match_error(schema_rule({"danger_kinds": ["gas"]})) is None
    assert module.danger_match_error(schema_rule({"subtypes": ["gas.smell"]})) is None
    flooding = module.danger_match_error(
        schema_rule({"danger_kinds": ["flooding"]}, route_type="municipality")
    )
    assert flooding == "danger_kinds are allowed only for emergency_service rules"
    assert module.danger_match_error(schema_rule({})) == "match needs subtypes or danger_kinds"


def test_the_loader_rejects_a_danger_rule_for_a_non_emergency_route(tmp_path: Path) -> None:
    target = tmp_path / "regions"
    shutil.copytree(REGIONS, target)
    path = target / "_federal" / "responsibility.yaml"
    document = yaml.safe_load(path.read_text("utf-8"))
    municipal = next(item for item in document["rules"] if item["route_type"] == "municipality")
    municipal["match"]["danger_kinds"] = ["flooding"]
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(DirectoryLoadError):
        load_directory(target)


# -------------------------------------------------------- маршрут выбора оператора


def of_type(directory: Any, route_type: str, subtype: str, **house: Any) -> Any:
    return route_of_type(
        route_type,  # type: ignore[arg-type]
        RoutingQuery(subtype=subtype, location_scope="unknown", house=kazan(**house)),
        directory,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )


def test_a_chosen_type_takes_the_channel_only_from_the_directory(packaged: Any) -> None:
    lighting = of_type(packaged, "municipality", "street_lighting.failure")
    assert lighting.route_type == "municipality"
    assert [channel.id for channel in lighting.channels] == ["pos_gosuslugi"]
    assert lighting.basis is not None and lighting.match == "rule"
    unknown = of_type(packaged, "municipality", "other.unspecified")
    assert unknown.route_type == "municipality" and unknown.match == "none"
    assert unknown.organization_name is None and unknown.channels == [] and unknown.basis is None
    uk = of_type(packaged, "uk_internal", "other.unspecified")
    assert uk.route_type == "uk_internal" and uk.can_create_ticket is True
    no_uk = of_type(packaged, "uk_internal", "other.unspecified", has_active_connected_uk=False)
    assert no_uk.can_create_ticket is False


def test_route_choices_follow_the_router(packaged: Any) -> None:
    unknown = resolve(packaged, "other.unspecified", "unknown")
    assert route_choices(unknown) == list(CHOOSABLE_ROUTES)
    assert "unknown" not in CHOOSABLE_ROUTES
    choice = resolve(packaged, "playground.damaged", "house_territory")
    assert choice.requires_operator_choice
    assert route_choices(choice) == ["uk_internal", "municipality"]
    decided = resolve(packaged, "elevator.stopped", "house_common")
    assert route_choices(decided) == []


# -------------------------------------------------------- настройки вместо констант


def test_passive_timings_come_from_settings() -> None:
    defaults = PassiveConfig.from_settings(
        Settings(app_env=AppEnvironment.TEST, _env_file=None)  # type: ignore[call-arg]
    )
    assert (defaults.danger_group_minutes, defaults.memo_pause_minutes) == (30, 30)
    assert defaults.fallback_seconds == 90
    tuned = PassiveConfig.from_settings(
        Settings(  # type: ignore[call-arg]
            app_env=AppEnvironment.TEST,
            passive_danger_group_minutes=5,
            passive_chat_memo_pause_minutes=7,
            passive_analysis_fallback_seconds=40,
            _env_file=None,
        )
    )
    assert tuned.danger_group_window.total_seconds() == 300
    assert tuned.memo_pause.total_seconds() == 420
    assert tuned.fallback_seconds == 40


# --------------------------------------------------------------- тексты очереди


def test_every_core_strength_reason_has_a_template() -> None:
    for code in (
        "emergency",
        "rules_danger_preliminary",
        "all_facets_yes",
        "observed_yes",
        "facets_unclear",
        "facet_no_local",
        "facet_no_observed",
        "facet_no_current",
    ):
        assert code in STRENGTH_REASONS
    assert strength_reason_text("something_new")


def test_ticket_description_uses_only_quoted_values_and_quotes() -> None:
    text = ticket_description(
        subject="Лифт",
        report_count=4,
        author_count=3,
        place={
            "entrance": {"value": "2", "quote": "во втором подъезде"},
            "floor": {"value": "5", "quote": None},
            "since": None,
        },
        quotes=[("A", "Лифт во втором подъезде стоит"), ("B", "Да, стоит с утра")],
    )
    assert text.splitlines() == [
        "Из домового чата: лифт. Сообщений: 4, жителей: 3.",
        "Подъезд: 2.",
        "Слова жителей:",
        "— «Лифт во втором подъезде стоит» (Житель A)",
        "— «Да, стоит с утра» (Житель B)",
    ]
    assert quoted_value({"value": "5", "quote": ""}) is None
    long = ticket_description(
        subject="Лифт",
        report_count=1,
        author_count=1,
        place={},
        quotes=[("A", "x" * 3000)],
    )
    assert len(long) == TICKET_DESCRIPTION_LIMIT and long.endswith("…")
