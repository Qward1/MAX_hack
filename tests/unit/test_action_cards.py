"""ActionCard: наборы действий, отключённые переходы, памятка и запреты формулировок."""

from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from domsignal.contracts.routing import ActionCard, ResponsibilityRoute
from domsignal.core.routing import HouseRoutingContext, RoutingQuery, resolve_route, safety_block
from domsignal.services.action_cards import (
    CHAT_DISCLAIMER,
    DEMO_NOTICE,
    EXTERNAL_DISCLAIMER,
    FORBIDDEN_PHRASES,
    build_action_card,
)
from domsignal.services.routing import load_directory
from domsignal.tools import print_json
from tests.unit.test_routing_core import SUBTYPES, kazan, synthetic

TODAY = date(2026, 9, 20)
REGIONS = Path(__file__).resolve().parents[2] / "regions"


@pytest.fixture(scope="module")
def packaged() -> Any:
    return load_directory(REGIONS)


def resolve(directory: Any, subtype: str, scope: str, house: HouseRoutingContext) -> Any:
    return resolve_route(
        RoutingQuery(subtype=subtype, location_scope=scope, house=house),
        directory,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )


def card(
    route: ResponsibilityRoute,
    *,
    audience: str = "resident",
    source: str = "chat",
    danger: tuple[str, ...] = (),
    house: HouseRoutingContext | None = None,
    directory: Any = None,
    existing_ticket_ref: str | None = None,
) -> ActionCard:
    context = house or kazan()
    return build_action_card(
        route,
        audience=audience,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        danger_kinds=danger,  # type: ignore[arg-type]
        existing_ticket_ref=existing_ticket_ref,
        is_demo=context.is_demo,
        can_report_to_uk=context.has_active_connected_uk,
        safety=safety_block(directory, danger, context) if directory is not None else None,  # type: ignore[arg-type]
    )


def types(built: ActionCard) -> list[str]:
    return [action.type for action in built.actions]


def test_uk_internal_resident_and_operator_actions(packaged: Any) -> None:
    route = resolve(packaged, "elevator.doors", "house_common", kazan())
    resident = card(route, existing_ticket_ref="ticket-1")
    assert types(resident) == ["create_ticket", "join_existing", "open_official_channel"]
    assert resident.actions[0].enabled is True
    official = resident.actions[-1]
    assert official.enabled is False and official.reason
    assert resident.existing_ticket_ref == "ticket-1"
    operator = card(route, audience="operator")
    assert types(operator) == ["create_ticket", "not_a_problem"]


def test_uk_internal_without_connected_company_disables_the_ticket(packaged: Any) -> None:
    house = kazan(has_active_connected_uk=False)
    route = resolve(packaged, "elevator.doors", "house_common", house)
    built = card(route, house=house)
    assert route.route_type == "unknown"
    assert types(built) == ["report_to_uk_anyway"]
    assert built.actions[0].enabled is False
    assert built.actions[0].reason


def test_municipal_card_offers_the_official_channel_without_naming_an_authority(
    packaged: Any,
) -> None:
    route = resolve(packaged, "street_lighting.failure", "municipal_territory", kazan())
    built = card(route, source="explicit")
    assert built.title == "Проблема, вероятно, относится не к вашей УК"
    assert built.explanation == "Ответственное ведомство определит официальный сервис."
    assert types(built) == ["open_official_channel", "prepare_appeal", "report_to_uk_anyway"]
    assert built.facts and all(fact.source_title for fact in built.facts)
    assert built.disclaimer == EXTERNAL_DISCLAIMER
    operator = card(route, audience="operator")
    assert types(operator) == [
        "open_official_channel",
        "prepare_appeal",
        "route_external",
        "not_a_problem",
        "create_ticket",
    ]


def test_missing_url_disables_the_transition_with_a_reason(packaged: Any) -> None:
    route = resolve(packaged, "street_lighting.failure", "municipal_territory", kazan())
    action = card(route).actions[0]
    assert action.type == "open_official_channel"
    assert action.enabled is False
    assert action.url is None
    assert action.reason is not None
    assert "Госуслуги" in action.reason


def test_route_without_verified_channel_falls_back_to_manual_decision(packaged: Any) -> None:
    route = resolve(packaged, "waste.removal_regional", "unknown", kazan())
    assert route.channels == []
    assert types(card(route)) == ["report_to_uk_anyway"]
    assert types(card(route, audience="operator")) == ["operator_review"]


def test_moscow_house_sees_a_card_without_channels(packaged: Any) -> None:
    house = HouseRoutingContext(region_code="RU-MOW", has_active_connected_uk=True)
    route = resolve(packaged, "street_lighting.failure", "municipal_territory", house)
    built = card(route, house=house)
    assert route.channels == []
    assert types(built) == ["report_to_uk_anyway"]
    assert built.actions[0].enabled is True


def test_danger_puts_the_verified_safety_memo_and_112_first(packaged: Any) -> None:
    house = kazan()
    route = resolve(packaged, "gas.smell", "house_common", house)
    built = card(route, danger=("gas",), directory=packaged, house=house)
    assert built.safety is not None
    assert built.safety.phone == "112"
    assert built.safety.steps == []
    assert types(built)[0] == "call_phone"
    assert built.actions[0].phone == "112"
    assert types(built).count("call_phone") == 1


def test_danger_on_an_internal_route_still_shows_the_memo(packaged: Any) -> None:
    house = kazan()
    route = resolve(packaged, "water.leak", "house_common", house)
    built = card(route, danger=("flooding",), directory=packaged, house=house)
    assert route.route_type == "uk_internal"
    assert built.safety is not None
    assert types(built)[0] == "call_phone"
    assert "create_ticket" in types(built)


def test_no_danger_means_no_safety_block(packaged: Any) -> None:
    route = resolve(packaged, "elevator.doors", "house_common", kazan())
    assert card(route, directory=packaged).safety is None


def test_operator_choice_and_unknown_cards(packaged: Any) -> None:
    choice = resolve(packaged, "playground.damaged", "house_territory", kazan())
    assert choice.requires_operator_choice is True
    assert card(choice).title == "Нужна проверка диспетчером"
    assert types(card(choice)) == ["report_to_uk_anyway"]
    assert types(card(choice, audience="operator")) == ["operator_review"]
    unknown = resolve(packaged, "other.unspecified", "unknown", kazan())
    built = card(unknown)
    assert built.title == "Не удалось надёжно определить ответственную организацию"
    assert types(built) == ["report_to_uk_anyway"]
    assert types(card(unknown, audience="operator")) == ["operator_review"]


def test_disclaimers_and_demo_notice(packaged: Any) -> None:
    internal = resolve(packaged, "elevator.doors", "house_common", kazan())
    assert card(internal, source="chat").disclaimer == CHAT_DISCLAIMER
    assert card(internal, source="explicit").disclaimer is None
    external = resolve(packaged, "street_lighting.failure", "municipal_territory", kazan())
    assert card(external, source="chat").disclaimer == f"{CHAT_DISCLAIMER} {EXTERNAL_DISCLAIMER}"
    demo_house = kazan(is_demo=True)
    assert card(internal, house=demo_house).demo_notice == DEMO_NOTICE
    assert card(internal).demo_notice is None


def test_no_card_promises_a_filed_or_registered_appeal(packaged: Any) -> None:
    directories = [packaged, synthetic()]
    cases = [
        ("elevator.doors", "house_common", ()),
        ("water.hot_outage", "house_common", ()),
        ("street_lighting.failure", "municipal_territory", ()),
        ("road.damage", "municipal_territory", ()),
        ("snow.street", "municipal_territory", ()),
        ("landscaping.public", "municipal_territory", ()),
        ("waste.removal_regional", "unknown", ()),
        ("external_network.outage", "external_network", ()),
        ("gas.supply_outage", "unknown", ()),
        ("gas.smell", "house_common", ("gas",)),
        ("playground.damaged", "house_territory", ()),
        ("snow.yard", "unknown", ()),
        ("other.unspecified", "unknown", ()),
        ("water.quality", "unknown", ("flooding",)),
    ]
    checked = 0
    for directory in directories:
        for subtype, scope, danger in cases:
            for house in (kazan(), kazan(is_demo=True), kazan(has_active_connected_uk=False)):
                route = resolve(directory, subtype, scope, house)
                for audience in ("resident", "operator"):
                    for source in ("chat", "explicit"):
                        built = card(
                            route,
                            audience=audience,
                            source=source,
                            danger=danger,
                            house=house,
                            directory=directory,
                            existing_ticket_ref="ticket-1",
                        )
                        payload = json.dumps(
                            built.model_dump(mode="json"), ensure_ascii=False
                        ).lower()
                        for phrase in FORBIDDEN_PHRASES:
                            assert phrase not in payload, (phrase, subtype, audience, source)
                        for action in built.actions:
                            assert action.enabled or action.reason
                        checked += 1
    assert checked == len(directories) * len(cases) * 3 * 2 * 2


def test_cli_json_survives_a_single_byte_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Карточка с кириллицей и «→» печатается и в консоли Windows."""
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1251")
    monkeypatch.setattr(sys, "stdout", stream)
    print_json({"entry_hint": "Госуслуги → «Сообщите, что вас волнует»"})
    stream.flush()
    payload = stream.buffer.getvalue().decode("utf-8")  # type: ignore[attr-defined]
    assert "Госуслуги → «Сообщите, что вас волнует»" in payload
