"""Путь жителя в mini app: форма, карточка исхода и ссылка `r_…`.

Форма проходит ту же цепочку решения, что и сообщение в домовом чате: второй
копии правила «какой маршрут → что создаём» в продукте нет. Карточка по исходу
собирается заново по текущему справочнику, а чужой исход неотличим от
несуществующего.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from domsignal.db.models import (
    AppealDraft,
    Incident,
    NotificationDelivery,
    Report,
    RouteOutcome,
    Ticket,
)
from domsignal.services.action_cards import FORBIDDEN_PHRASES
from tests.integration.explicit_harness import ex  # noqa: F401

ELEVATOR = "опять лифт во втором подъезде стоит"
STREET_LIGHT = "на улице у остановки не горят фонари"
UNKNOWN = "соседи снова громко слушают музыку по ночам"


async def _submit(
    harness: Any,
    description: str,
    *,
    actor: str = "resident",
    key: str = "submit-key-0001",
    category: str | None = None,
) -> Any:
    body: dict[str, Any] = {"description": description}
    if category is not None:
        body["category"] = category
    return await harness.client.post(
        f"/api/v1/houses/{harness.ids['h1']}/reports/submit",
        json=body,
        headers={**harness.headers[actor], "Idempotency-Key": key},
    )


async def _preview(harness: Any, description: str, actor: str = "resident") -> Any:
    return await harness.client.post(
        f"/api/v1/houses/{harness.ids['h1']}/reports/preview",
        json={"description": description},
        headers=harness.headers[actor],
    )


# ------------------------------------------------------------------- отправка


@pytest.mark.integration
async def test_form_submit_records_the_outcome_with_its_author(ex) -> None:  # noqa: F811
    response = await _submit(ex, ELEVATOR)
    assert response.status_code == 201, response.text
    body = response.json()

    outcome = await ex.scalar(select(RouteOutcome))
    assert str(outcome.id) == body["route_outcome_id"]
    assert outcome.source == "form"
    assert outcome.author_id == ex.ids["resident"]
    assert outcome.submitted_text == ELEVATOR
    assert outcome.intake_event_id is None
    assert body["decision"] == "ticket"
    assert body["analysis"]["subtype"] == "elevator.stopped"
    assert body["analysis"]["entrance"] == "2"
    assert body["action_card"]["route"]["route_type"] == "uk_internal"
    assert body["report"] is not None
    lowered = str(body).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, phrase


@pytest.mark.integration
async def test_uk_route_from_the_form_creates_the_ticket(ex) -> None:  # noqa: F811
    await _submit(ex, ELEVATOR)
    assert await ex.scalar(select(func.count()).select_from(Report)) == 1
    assert await ex.scalar(select(func.count()).select_from(Ticket)) == 1
    incident = await ex.scalar(select(Incident))
    # Подъезд взят из цитаты, а не угадан.
    assert incident.location_entrance == "2"


@pytest.mark.integration
async def test_external_route_from_the_form_creates_no_ticket(ex) -> None:  # noqa: F811
    response = await _submit(ex, STREET_LIGHT)
    body = response.json()
    assert body["decision"] == "external" and body["report"] is None
    assert await ex.scalar(select(func.count()).select_from(Report)) == 0
    assert await ex.scalar(select(func.count()).select_from(Ticket)) == 0
    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.route_type == "municipality" and outcome.report_id is None
    # Форма отвечает жителю на экране: второго личного сообщения не появляется.
    assert await ex.scalar(select(func.count()).select_from(NotificationDelivery)) == 0


@pytest.mark.integration
async def test_the_same_idempotency_key_does_not_duplicate_the_report(ex) -> None:  # noqa: F811
    first = await _submit(ex, ELEVATOR, key="submit-key-same")
    second = await _submit(ex, ELEVATOR, key="submit-key-same")
    assert first.status_code == 201 and second.status_code == 201
    assert await ex.scalar(select(func.count()).select_from(Report)) == 1
    assert await ex.scalar(select(func.count()).select_from(Incident)) == 1
    assert first.json()["report"]["report_id"] == second.json()["report"]["report_id"]


@pytest.mark.integration
async def test_a_manual_category_survives_an_unclear_description(ex) -> None:  # noqa: F811
    unclear = await _preview(ex, UNKNOWN)
    assert unclear.json()["analysis"]["confident"] is False

    response = await _submit(ex, UNKNOWN, category="waste", key="submit-key-manual")
    body = response.json()
    # Маршрут остаётся неопределённым: это решает диспетчер, а не выбор из
    # списка. Но названная человеком категория не заменяется на «другое».
    assert body["decision"] == "needs_clarification"
    report = await ex.scalar(select(Report))
    assert report.category == "waste"
    # Категорию назвал человек, и происхождение классификации это отражает.
    assert report.classification_mode == "manual"


@pytest.mark.integration
async def test_a_manual_category_overrides_the_parsed_one_in_the_uk_zone(ex) -> None:  # noqa: F811
    response = await _submit(ex, ELEVATOR, category="other", key="submit-key-override")
    assert response.json()["decision"] == "ticket"
    report = await ex.scalar(select(Report))
    assert report.category == "other"


@pytest.mark.integration
async def test_submit_is_refused_outside_the_house(ex) -> None:  # noqa: F811
    response = await _submit(ex, ELEVATOR, actor="outsider", key="submit-key-foreign")
    assert response.status_code in {403, 404}
    assert await ex.scalar(select(func.count()).select_from(RouteOutcome)) == 0


@pytest.mark.integration
async def test_submit_requires_an_idempotency_key(ex) -> None:  # noqa: F811
    response = await ex.client.post(
        f"/api/v1/houses/{ex.ids['h1']}/reports/submit",
        json={"description": ELEVATOR},
        headers=ex.headers["resident"],
    )
    assert response.status_code == 422


# --------------------------------------------------------------- черновик


@pytest.mark.integration
async def test_a_form_appeal_draft_contains_the_residents_own_words(ex) -> None:  # noqa: F811
    submitted = (await _submit(ex, STREET_LIGHT, key="submit-key-draft")).json()
    created = await ex.client.post(
        "/api/v1/appeal-drafts",
        json={
            "house_id": str(ex.ids["h1"]),
            "route_outcome_id": submitted["route_outcome_id"],
        },
        headers=ex.headers["resident"],
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    # Внешний маршрут из формы: ни записи приёма, ни заявки — текст берётся
    # из самого исхода, иначе черновик остался бы без описания проблемы.
    assert STREET_LIGHT in draft["text"]
    assert "Суть проблемы или предложения:" in draft["text"]
    assert draft["channel"]["id"] == "ru_ta_narodny_kontrol"  # D4: Казань
    assert await ex.scalar(select(func.count()).select_from(AppealDraft)) == 1


# --------------------------------------------------- чтение исхода маршрута


@pytest.mark.integration
async def test_the_author_reads_the_card_rebuilt_from_the_current_directory(ex) -> None:  # noqa: F811
    submitted = (await _submit(ex, STREET_LIGHT, key="submit-key-view")).json()
    response = await ex.client.get(
        f"/api/v1/route-outcomes/{submitted['route_outcome_id']}",
        headers=ex.headers["resident"],
    )
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["decision"] == "external"
    assert view["route_type"] == "municipality"
    assert view["incident_id"] is None and view["appeal_draft_id"] is None
    assert view["directory_changed"] is False
    assert view["action_card"]["generated_by"] == "rules"
    lowered = str(view).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, phrase


@pytest.mark.integration
async def test_the_card_links_the_created_problem_and_an_existing_draft(ex) -> None:  # noqa: F811
    submitted = (await _submit(ex, ELEVATOR, key="submit-key-link")).json()
    response = await ex.client.get(
        f"/api/v1/route-outcomes/{submitted['route_outcome_id']}",
        headers=ex.headers["resident"],
    )
    view = response.json()
    assert view["incident_id"] == submitted["report"]["incident"]["id"]


@pytest.mark.integration
async def test_a_foreign_and_a_missing_outcome_answer_the_same(ex) -> None:  # noqa: F811
    submitted = (await _submit(ex, ELEVATOR, key="submit-key-foreign-read")).json()
    foreign = await ex.client.get(
        f"/api/v1/route-outcomes/{submitted['route_outcome_id']}",
        headers=ex.headers["neighbour"],
    )
    missing = await ex.client.get(
        f"/api/v1/route-outcomes/{uuid4()}", headers=ex.headers["resident"]
    )
    assert foreign.status_code == 404 and missing.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"]


@pytest.mark.integration
async def test_a_changed_directory_is_admitted_instead_of_a_stale_card(ex) -> None:  # noqa: F811
    submitted = (await _submit(ex, STREET_LIGHT, key="submit-key-changed")).json()
    # Справочник перестал быть доступен: маршрут честно становится `unknown`.
    ex.container.routing.directory = None
    response = await ex.client.get(
        f"/api/v1/route-outcomes/{submitted['route_outcome_id']}",
        headers=ex.headers["resident"],
    )
    view = response.json()
    assert view["directory_changed"] is True
    assert view["route_type"] == "unknown"
    # Сохранённое решение не переписывается задним числом.
    assert view["decision"] == "external"


@pytest.mark.integration
async def test_the_card_keeps_the_safety_block_of_a_dangerous_report(ex) -> None:  # noqa: F811
    submitted = (await _submit(ex, "в третьем подъезде пахнет газом", key="submit-key-gas")).json()
    assert submitted["action_card"]["safety"]["phone"] == "112"
    response = await ex.client.get(
        f"/api/v1/route-outcomes/{submitted['route_outcome_id']}",
        headers=ex.headers["resident"],
    )
    card = response.json()["action_card"]
    # Признаки опасности не хранятся отдельным столбцом: те же слова и те же
    # правила дают ту же памятку при повторном чтении.
    assert card["safety"] is not None and card["safety"]["phone"] == "112"
    assert card["actions"][0]["phone"] == "112"


# ------------------------------------------------------------- резолвер r_


@pytest.mark.integration
async def test_the_route_card_link_opens_the_card_for_its_recipient(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()
    delivery = await ex.scalar(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "route_action_card")
    )
    assert delivery.launch_ref.startswith("r_")

    response = await ex.client.get(
        f"/api/v1/notification-launch/{delivery.launch_ref}",
        headers=ex.headers["resident"],
    )
    assert response.status_code == 200, response.text
    launch = response.json()
    assert launch["kind"] == "route_card"
    assert launch["incident_id"] is None
    assert launch["route_outcome_id"] == str(delivery.route_outcome_id)
    assert launch["house_id"] == str(ex.ids["h1"])
    assert launch["stale"] is False

    # Карточка открывается по тому же исходу и принадлежит получателю.
    card = await ex.client.get(
        f"/api/v1/route-outcomes/{launch['route_outcome_id']}",
        headers=ex.headers["resident"],
    )
    assert card.status_code == 200


@pytest.mark.integration
async def test_another_resident_cannot_use_the_route_card_link(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()
    delivery = await ex.scalar(
        select(NotificationDelivery).where(NotificationDelivery.purpose == "route_action_card")
    )
    for actor in ("neighbour", "outsider"):
        response = await ex.client.get(
            f"/api/v1/notification-launch/{delivery.launch_ref}",
            headers=ex.headers[actor],
        )
        assert response.status_code == 404, actor


@pytest.mark.integration
async def test_a_malformed_launch_reference_is_not_found(ex) -> None:  # noqa: F811
    for ref in ("r_short", "x_" + "a" * 32, "r_" + "!" * 32):
        response = await ex.client.get(
            f"/api/v1/notification-launch/{ref}", headers=ex.headers["resident"]
        )
        assert response.status_code == 404, ref


# ------------------------------------------------------------ дубли в форме


@pytest.mark.integration
async def test_preview_offers_open_candidates_and_creates_nothing(ex) -> None:  # noqa: F811
    first = (await _submit(ex, ELEVATOR, key="submit-key-dup-1")).json()
    reports_before = await ex.scalar(select(func.count()).select_from(Report))

    response = await _preview(ex, "лифт опять не едет", actor="neighbour")
    assert response.status_code == 200, response.text
    body = response.json()
    candidates = body["duplicates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["incident_id"] == first["report"]["incident"]["id"]
    assert candidate["category"] == "elevator"
    assert candidate["status"] == "open"
    assert candidate["report_count"] == 1 and candidate["participant_count"] == 1
    assert candidate["match_reason"]

    # Карточка получает действие «присоединиться», но идентификатор остаётся
    # в `duplicates`: интерфейс не берёт его из заголовка.
    types = [action["type"] for action in body["action_card"]["actions"]]
    assert "join_existing" in types
    assert body["action_card"]["existing_ticket_ref"] == candidate["title"]

    # Предпросмотр по-прежнему ничего не создаёт.
    assert await ex.scalar(select(func.count()).select_from(Report)) == reports_before
    assert await ex.scalar(select(func.count()).select_from(RouteOutcome)) == 1


@pytest.mark.integration
async def test_candidates_ignore_another_category_and_an_old_problem(ex) -> None:  # noqa: F811
    await _submit(ex, ELEVATOR, key="submit-key-dup-old")
    async with ex.container.session_factory() as session, session.begin():
        await session.execute(
            update(Incident).values(created_at=datetime.now(UTC) - timedelta(days=15))
        )
    aged = await _preview(ex, "лифт опять не едет", actor="neighbour")
    assert aged.json()["duplicates"] == []

    other = await _preview(ex, "во дворе не вывезли мусор", actor="neighbour")
    assert other.json()["duplicates"] == []


@pytest.mark.integration
async def test_a_closed_problem_is_not_offered_as_a_candidate(ex) -> None:  # noqa: F811
    await _submit(ex, ELEVATOR, key="submit-key-dup-closed")
    async with ex.container.session_factory() as session, session.begin():
        await session.execute(update(Incident).values(status="resolved"))
    response = await _preview(ex, "лифт опять не едет", actor="neighbour")
    assert response.json()["duplicates"] == []


@pytest.mark.integration
async def test_at_most_three_candidates_are_offered(ex) -> None:  # noqa: F811
    for index in range(4):
        await _submit(ex, ELEVATOR, key=f"submit-key-many-{index}")
    response = await _preview(ex, "лифт опять не едет", actor="neighbour")
    assert len(response.json()["duplicates"]) == 3


@pytest.mark.integration
async def test_joining_a_candidate_adds_a_participant_not_a_second_ticket(ex) -> None:  # noqa: F811
    first = (await _submit(ex, ELEVATOR, key="submit-key-join")).json()
    incident_id = first["report"]["incident"]["id"]
    tickets_before = await ex.scalar(select(func.count()).select_from(Ticket))

    joined = await ex.client.post(
        f"/api/v1/incidents/{incident_id}/join",
        headers={**ex.headers["neighbour"], "Idempotency-Key": "join-from-form-0001"},
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["participant_count"] == 2
    assert await ex.scalar(select(func.count()).select_from(Ticket)) == tickets_before
    # Присоединение не создаёт второго исхода маршрутизации.
    assert await ex.scalar(select(func.count()).select_from(RouteOutcome)) == 1
