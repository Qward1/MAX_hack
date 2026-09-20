"""Предпросмотр маршрута для формы и присоединение к уже созданной проблеме.

Предпросмотр обязан быть безобидным: он отвечает синхронно, работает только
правилами и не создаёт ни одной записи. Присоединение добавляет участника, но
не вторую заявку в очередь УК.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, update

from domsignal.db.models import Incident, Job, OutboxMessage, Report, RouteOutcome, Ticket
from domsignal.services.action_cards import FORBIDDEN_PHRASES
from tests.integration.explicit_harness import ex  # noqa: F401

ELEVATOR = "опять лифт во втором подъезде стоит"
STREET_LIGHT = "на улице у остановки не горят фонари"


async def _preview(harness, description: str, actor: str = "resident"):  # noqa: ANN001
    return await harness.client.post(
        f"/api/v1/houses/{harness.ids['h1']}/reports/preview",
        json={"description": description},
        headers=harness.headers[actor],
    )


# ------------------------------------------------------------------ предпросмотр


@pytest.mark.integration
async def test_preview_explains_the_uk_route_without_touching_anything(ex) -> None:  # noqa: F811
    response = await _preview(ex, ELEVATOR)
    assert response.status_code == 200, response.text
    body = response.json()

    analysis = body["analysis"]
    assert analysis["subtype"] == "elevator.stopped"
    assert analysis["category"] == "elevator"
    assert analysis["location_scope"] == "house_common"
    assert analysis["entrance"] == "2"
    assert analysis["floor"] is None and analysis["since"] is None
    assert analysis["danger_kinds"] == []
    assert analysis["mode"] == "rules"
    assert analysis["confident"] is True

    card = body["action_card"]
    assert card["route"]["route_type"] == "uk_internal"
    assert card["generated_by"] == "rules"
    assert [action["type"] for action in card["actions"]][0] == "create_ticket"

    # Ни одной записи: предпросмотр не имеет побочных эффектов.
    for model in (Report, Incident, RouteOutcome, Ticket, Job, OutboxMessage):
        assert await ex.scalar(select(func.count()).select_from(model)) == 0, model


@pytest.mark.integration
async def test_preview_shows_the_external_route_and_its_channel(ex) -> None:  # noqa: F811
    response = await _preview(ex, STREET_LIGHT)
    assert response.status_code == 200, response.text
    card = response.json()["action_card"]
    assert card["route"]["route_type"] == "municipality"
    assert [channel["id"] for channel in card["route"]["channels"]] == ["pos_gosuslugi"]
    assert card["route"]["can_prepare_appeal"] is True
    assert "prepare_appeal" in [action["type"] for action in card["actions"]]
    lowered = str(card).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, phrase


@pytest.mark.integration
async def test_preview_never_calls_the_provider(ex) -> None:  # noqa: F811
    from domsignal.ai.providers.fake import FakeProvider

    provider = FakeProvider("ok")
    ex.container.explicit_reports.analyzer.provider = provider
    response = await _preview(ex, ELEVATOR)
    assert response.status_code == 200
    # Форма отвечает человеку синхронно, поэтому модель здесь не участвует.
    assert provider.requests == []
    assert response.json()["analysis"]["mode"] == "rules"


@pytest.mark.integration
async def test_preview_marks_danger_and_keeps_the_safety_block(ex) -> None:  # noqa: F811
    response = await _preview(ex, "в третьем подъезде пахнет газом")
    body = response.json()
    assert body["analysis"]["danger_kinds"] == ["gas"]
    card = body["action_card"]
    assert card["safety"] is not None and card["safety"]["phone"] == "112"
    assert card["actions"][0]["phone"] == "112"


@pytest.mark.integration
async def test_preview_is_refused_outside_the_house(ex) -> None:  # noqa: F811
    response = await _preview(ex, ELEVATOR, actor="outsider")
    assert response.status_code in {403, 404}


@pytest.mark.integration
async def test_preview_rejects_a_too_short_description(ex) -> None:  # noqa: F811
    response = await _preview(ex, "ой")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


# ------------------------------------------------------------------ создание


@pytest.mark.integration
async def test_report_creation_answers_with_the_same_card(ex) -> None:  # noqa: F811
    response = await ex.client.post(
        "/api/v1/reports",
        json={
            "house_id": str(ex.ids["h1"]),
            "category": "elevator",
            "description": "Лифт не работает",
        },
        headers={**ex.headers["resident"], "Idempotency-Key": "form-key-0001"},
    )
    assert response.status_code == 201, response.text
    card = response.json()["action_card"]
    assert card is not None
    assert card["route"]["route_type"] == "uk_internal"
    assert card["generated_by"] == "rules"


# ---------------------------------------------------------------- join


@pytest.mark.integration
async def test_join_adds_a_participant_without_a_second_ticket(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()
    incident = await ex.scalar(select(Incident))
    tickets_before = await ex.scalar(select(func.count()).select_from(Ticket))

    response = await ex.client.post(
        f"/api/v1/incidents/{incident.id}/join",
        headers={**ex.headers["neighbour"], "Idempotency-Key": "join-key-0001"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report_count"] == 2
    assert body["participant_count"] == 2
    assert await ex.scalar(select(func.count()).select_from(Report)) == 2
    # Заявка уже есть; вторая не нужна.
    assert await ex.scalar(select(func.count()).select_from(Ticket)) == tickets_before


@pytest.mark.integration
async def test_join_is_idempotent_for_the_same_key(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()
    incident = await ex.scalar(select(Incident))
    headers = {**ex.headers["neighbour"], "Idempotency-Key": "join-key-0002"}
    first = await ex.client.post(f"/api/v1/incidents/{incident.id}/join", headers=headers)
    second = await ex.client.post(f"/api/v1/incidents/{incident.id}/join", headers=headers)
    assert first.status_code == 200 and second.status_code == 200
    assert await ex.scalar(select(func.count()).select_from(Report)) == 2
    assert second.json()["report_count"] == 2


@pytest.mark.integration
async def test_join_refuses_a_closed_incident(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()
    incident = await ex.scalar(select(Incident))
    async with ex.container.session_factory() as session, session.begin():
        await session.execute(
            update(Incident).where(Incident.id == incident.id).values(status="resolved")
        )
    response = await ex.client.post(
        f"/api/v1/incidents/{incident.id}/join",
        headers={**ex.headers["neighbour"], "Idempotency-Key": "join-key-0003"},
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "incident_closed"
    assert await ex.scalar(select(func.count()).select_from(Report)) == 1


@pytest.mark.integration
async def test_join_hides_another_houses_incident(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()
    incident = await ex.scalar(select(Incident))
    response = await ex.client.post(
        f"/api/v1/incidents/{incident.id}/join",
        headers={**ex.headers["outsider"], "Idempotency-Key": "join-key-0004"},
    )
    assert response.status_code in {403, 404}
    assert await ex.scalar(select(func.count()).select_from(Report)) == 1


@pytest.mark.integration
async def test_join_of_an_unknown_incident_is_not_found(ex) -> None:  # noqa: F811
    response = await ex.client.post(
        "/api/v1/incidents/00000000-0000-0000-0000-0000000000ff/join",
        headers={**ex.headers["resident"], "Idempotency-Key": "join-key-0005"},
    )
    assert response.status_code == 404
