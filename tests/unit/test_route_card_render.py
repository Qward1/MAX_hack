"""Личное сообщение с карточкой маршрута: детерминированный текст без модели.

Продукт не подаёт обращение за человека, поэтому сообщение не может сказать,
что заявка отправлена или обращение зарегистрировано. Текст модели
(`clean_description`) сюда не попадает: он нужен только в черновике, где его
правит человек.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from domsignal.contracts.routing import ActionCard
from domsignal.core.routing import HouseRoutingContext, RoutingQuery, resolve_route, safety_block
from domsignal.services.action_cards import FORBIDDEN_PHRASES, build_action_card
from domsignal.services.route_card_render import (
    OPEN_CARD_LABEL,
    RouteCardIntent,
    build_route_card_intent,
    render_route_card,
)
from domsignal.services.routing import load_directory
from tests.unit.test_routing_core import SUBTYPES, federal_house, kazan

TODAY = date(2026, 9, 20)
REGIONS = Path(__file__).resolve().parents[2] / "regions"
REF = "r_" + "a" * 32
HOUSE = UUID("00000000-0000-0000-0000-000000000101")
RECIPIENT = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="module")
def packaged() -> Any:
    return load_directory(REGIONS)


def _card(
    directory: Any,
    subtype: str,
    scope: str,
    *,
    danger: tuple[str, ...] = (),
    house: HouseRoutingContext | None = None,
) -> tuple[ActionCard, HouseRoutingContext]:
    context = house or kazan()
    route = resolve_route(
        RoutingQuery(subtype=subtype, location_scope=scope, danger_kinds=danger, house=context),  # type: ignore[arg-type]
        directory,
        known_subtypes=SUBTYPES,
        today=TODAY,
    )
    card = build_action_card(
        route,
        audience="resident",
        source="explicit",
        danger_kinds=danger,  # type: ignore[arg-type]
        is_demo=context.is_demo,
        can_report_to_uk=context.has_active_connected_uk,
        safety=safety_block(directory, danger, context),  # type: ignore[arg-type]
    )
    return card, context


def _intent(card: ActionCard, danger: tuple[str, ...] = ()) -> RouteCardIntent:
    return build_route_card_intent(
        card,
        route_outcome_id=uuid4(),
        house_id=HOUSE,
        recipient_user_id=RECIPIENT,
        danger_kinds=danger,  # type: ignore[arg-type]
    )


def test_external_route_message_names_the_route_and_its_basis(packaged: Any) -> None:
    card, _ = _card(packaged, "street_lighting.failure", "municipal_territory")
    assert card.route.route_type == "municipality"
    message = render_route_card(_intent(card), ref=REF)
    assert card.title in message.text
    # Основание видно жителю; общее пояснение, которое оно пересказывает, — нет.
    assert card.route.basis is not None
    assert card.route.basis.text in message.text
    assert card.explanation not in message.text


def test_message_is_short_with_one_source_link_at_the_end(packaged: Any) -> None:
    """P6b, владелец: без «Источник: …», «Проверено без входа …» и повторов."""
    card, _ = _card(
        packaged, "street_lighting.failure", "municipal_territory", house=federal_house()
    )
    message = render_route_card(_intent(card), ref=REF)
    assert "Источник:" not in message.text
    assert "Проверено" not in message.text
    assert message.text.endswith("Информация взята с: pos.gosuslugi.ru/landing")
    assert message.text.count("рассмотрит профильный орган власти") == 1
    assert any(fact.text in message.text for fact in card.facts)


def test_appeal_message_walks_through_the_mini_app_buttons(packaged: Any) -> None:
    """P6b, владелец: инструкция «что нажать» по кнопкам карточки и черновика."""
    card, _ = _card(
        packaged, "street_lighting.failure", "municipal_territory", house=federal_house()
    )
    text = render_route_card(_intent(card), ref=REF).text
    steps = text[text.index("Что делать:") : text.index("ДомСигнал не отправляет")]
    for label in (
        "«Открыть карточку»",
        "«Подготовить текст обращения»",
        "«Сохранить правку»",
        "«Скопировать текст»",
        "«Открыть официальный сервис»",
        "«Я отправил(а) обращение»",
    ):
        assert label in steps, label
    assert steps.index("«Подготовить текст обращения»") < steps.index("«Скопировать текст»")
    assert text.endswith("Информация взята с: pos.gosuslugi.ru/landing")


def test_routes_without_an_appeal_get_no_appeal_steps(packaged: Any) -> None:
    for subtype, scope, danger in (
        ("gas.smell", "house_common", ("gas",)),
        ("elevator.stopped", "house_common", ()),
    ):
        card, _ = _card(packaged, subtype, scope, danger=danger)
        text = render_route_card(_intent(card, danger=danger), ref=REF).text
        assert "Что делать:" not in text, subtype


def test_at_most_two_facts_reach_the_message(packaged: Any) -> None:
    card, _ = _card(packaged, "street_lighting.failure", "municipal_territory")
    intent = _intent(card)
    assert len(intent.facts) <= 2


def test_danger_puts_the_safety_block_first_with_the_emergency_phone(
    packaged: Any,
) -> None:
    card, _ = _card(packaged, "gas.smell", "house_common", danger=("gas",))
    intent = _intent(card, danger=("gas",))
    assert intent.safety is not None and intent.safety.phone == "112"
    message = render_route_card(intent, ref=REF)
    assert message.text.startswith(intent.safety.title)
    assert "112" in message.text
    # Памятка стоит раньше заголовка маршрута, а не после него.
    assert message.text.index(intent.safety.title) < message.text.index(card.title)


def test_message_carries_the_disclaimer_and_opens_the_app(packaged: Any) -> None:
    card, _ = _card(packaged, "street_lighting.failure", "municipal_territory")
    message = render_route_card(_intent(card), ref=REF)
    assert card.disclaimer is not None and card.disclaimer in message.text
    button = message.buttons[0][0]
    assert button.kind == "open_app" and button.payload == REF
    assert button.text == OPEN_CARD_LABEL


def test_demo_house_message_is_marked_as_test_data(packaged: Any) -> None:
    demo = HouseRoutingContext(
        is_demo=True,
        has_active_connected_uk=True,
        region_code="RU-TA",
        municipality_code="kazan",
    )
    card, _ = _card(packaged, "street_lighting.failure", "municipal_territory", house=demo)
    message = render_route_card(_intent(card), ref=REF)
    assert "Пример данных" in message.text


def test_no_forbidden_phrase_in_any_rendered_route_card(packaged: Any) -> None:
    cases = [
        ("elevator.doors", "house_common", ()),
        ("street_lighting.failure", "municipal_territory", ()),
        ("gas.smell", "house_common", ("gas",)),
        ("waste.container_site", "house_territory", ()),
        ("other.unspecified", "unknown", ()),
        ("water.leak", "house_common", ("flooding",)),
    ]
    houses = [
        kazan(),
        HouseRoutingContext(
            is_demo=True,
            has_active_connected_uk=True,
            region_code="RU-TA",
            municipality_code="kazan",
        ),
        HouseRoutingContext(),
    ]
    checked = 0
    for subtype, scope, danger in cases:
        for house in houses:
            card, _ = _card(packaged, subtype, scope, danger=danger, house=house)
            message = render_route_card(_intent(card, danger), ref=REF)
            payload = message.text + " ".join(
                button.text for row in message.buttons for button in row
            )
            lowered = payload.lower()
            for phrase in FORBIDDEN_PHRASES:
                assert phrase not in lowered, (phrase, subtype, scope, house)
            checked += 1
    assert checked == len(cases) * len(houses)


def test_route_card_never_claims_the_message_is_an_appeal(packaged: Any) -> None:
    cases = (("street_lighting.failure", "municipal_territory"), ("elevator.doors", "house_common"))
    for subtype, scope in cases:
        card, _ = _card(packaged, subtype, scope)
        text = render_route_card(_intent(card), ref=REF).text.lower()
        # Допустимо только отрицание или инструкция жителю, что делает он сам
        # (P6b: «проверьте текст», «отправьте», кнопка «Я отправил(а)»).
        for sentence in text.split("."):
            if "обращение" in sentence or "обращения" in sentence:
                allowed = (
                    "не является",
                    "подготовить",
                    "отправляете",
                    "отправьте",
                    "проверьте текст",
                    "я отправил(а)",
                )
                assert any(word in sentence for word in allowed), sentence
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, phrase


def test_model_prose_is_never_part_of_the_intent(packaged: Any) -> None:
    card, _ = _card(packaged, "street_lighting.failure", "municipal_territory")
    intent = _intent(card)
    # У интента нет поля для текста модели — он физически не может туда попасть.
    assert "clean_description" not in RouteCardIntent.model_fields
    assert "description" not in RouteCardIntent.model_fields
    dumped = intent.model_dump_json()
    assert "clean_description" not in dumped


def test_intent_round_trips_through_the_outbox_payload(packaged: Any) -> None:
    card, _ = _card(packaged, "gas.smell", "house_common", danger=("gas",))
    intent = _intent(card, danger=("gas",))
    restored = RouteCardIntent.model_validate(intent.model_dump(mode="json"))
    assert render_route_card(restored, ref=REF) == render_route_card(intent, ref=REF)
