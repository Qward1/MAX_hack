"""Черновик обращения: сборка, правка, конфликт версии, отметка подачи.

Продукт готовит текст, но не отправляет его. Отметка подачи остаётся
утверждением жителя и не превращается в подтверждение регистрации.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from domsignal.db.models import AppealDraft, RouteOutcome
from domsignal.services.action_cards import FORBIDDEN_PHRASES
from domsignal.services.appeal_drafts import (
    CHANNEL_FACTS_HEADING,
    PROBLEM_HEADING,
    SELF_FILING_NOTE,
)
from tests.integration.explicit_harness import ex  # noqa: F401

STREET_LIGHT = "на улице у остановки не горят фонари"
ELEVATOR = "опять лифт во втором подъезде стоит"


async def _external_outcome(harness) -> RouteOutcome:  # noqa: ANN001
    await harness.bind()
    await harness.report(f"/report {STREET_LIGHT}")
    await harness.drain_all()
    outcome = await harness.scalar(select(RouteOutcome))
    assert outcome is not None and outcome.decision == "external"
    return outcome


async def _create(harness, outcome, actor="resident"):  # noqa: ANN001
    return await harness.client.post(
        "/api/v1/appeal-drafts",
        json={"house_id": str(harness.ids["h1"]), "route_outcome_id": str(outcome.id)},
        headers=harness.headers[actor],
    )


@pytest.mark.integration
async def test_draft_is_composed_from_verified_data_and_the_residents_words(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    response = await _create(ex, outcome)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["version"] == 1
    assert body["route_outcome_id"] == str(outcome.id)
    # Без провайдера переформулировки нет: в черновик идут слова жителя.
    assert body["ai_assisted"] is False
    text = body["text"]
    assert PROBLEM_HEADING in text
    assert STREET_LIGHT in text
    assert "Казань, Синтетическая улица, 1" in text
    # Канал и его проверенные факты приходят со ссылкой на источник.
    assert body["channel"]["id"] == "pos_gosuslugi"
    assert CHANNEL_FACTS_HEADING in text
    assert "«рассматривается в течение 30 дней со дня регистрации письменного обращения»" in text
    assert "59-ФЗ" in text and "календарных" not in text
    assert "gosuslugi.ru" in text
    assert SELF_FILING_NOTE in text
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, phrase

    assert body["provenance"]["origin"] == "product_derived"
    actions = {item["code"]: item for item in body["allowed_actions"]}
    assert actions["copy_draft"]["enabled"] is True
    assert actions["mark_filed"]["enabled"] is True
    # Ссылка входа ПОС ещё не заполнена владельцем — действие честно отключено.
    assert actions["open_official_channel"]["enabled"] is False
    assert actions["open_official_channel"]["reason"]


@pytest.mark.integration
async def test_one_problem_gives_one_draft(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    first = await _create(ex, outcome)
    second = await _create(ex, outcome)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert await ex.scalar(select(func.count()).select_from(AppealDraft)) == 1


@pytest.mark.integration
async def test_editing_keeps_the_text_and_bumps_the_version(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    draft = (await _create(ex, outcome)).json()
    edited = await ex.client.patch(
        f"/api/v1/appeal-drafts/{draft['id']}",
        json={"text": "Мой собственный текст обращения", "version": 1},
        headers=ex.headers["resident"],
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["text"] == "Мой собственный текст обращения"
    assert edited.json()["version"] == 2
    fresh = await ex.client.get(
        f"/api/v1/appeal-drafts/{draft['id']}", headers=ex.headers["resident"]
    )
    assert fresh.json()["text"] == "Мой собственный текст обращения"


@pytest.mark.integration
async def test_a_stale_version_conflicts_without_losing_the_saved_text(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    draft = (await _create(ex, outcome)).json()
    await ex.client.patch(
        f"/api/v1/appeal-drafts/{draft['id']}",
        json={"text": "Первая правка", "version": 1},
        headers=ex.headers["resident"],
    )
    stale = await ex.client.patch(
        f"/api/v1/appeal-drafts/{draft['id']}",
        json={"text": "Правка поверх устаревшей версии", "version": 1},
        headers=ex.headers["resident"],
    )
    assert stale.status_code == 409
    assert stale.headers["content-type"].startswith("application/problem+json")
    problem = stale.json()
    assert problem["code"] == "stale_version" and problem["status"] == 409
    # Сохранённый текст не затёрт устаревшей правкой.
    fresh = await ex.client.get(
        f"/api/v1/appeal-drafts/{draft['id']}", headers=ex.headers["resident"]
    )
    assert fresh.json()["text"] == "Первая правка" and fresh.json()["version"] == 2


@pytest.mark.integration
async def test_mark_filed_records_only_the_residents_assertion(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    draft = (await _create(ex, outcome)).json()
    filed = await ex.client.post(
        f"/api/v1/appeal-drafts/{draft['id']}/mark-filed",
        json={"reference": "ПОС-12345"},
        headers=ex.headers["resident"],
    )
    assert filed.status_code == 200, filed.text
    body = filed.json()
    assert body["filed_at"] is not None
    assert body["filed_reference"] == "ПОС-12345"
    # Отметка жителя, не подтверждение внешней системы.
    assert body["provenance"]["origin"] == "user_reported"
    assert "не подтверждено" in body["provenance"]["note"]
    actions = {item["code"]: item for item in body["allowed_actions"]}
    assert actions["mark_filed"]["enabled"] is False and actions["mark_filed"]["reason"]


@pytest.mark.integration
async def test_mark_filed_without_a_reference_is_allowed(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    draft = (await _create(ex, outcome)).json()
    filed = await ex.client.post(
        f"/api/v1/appeal-drafts/{draft['id']}/mark-filed", headers=ex.headers["resident"]
    )
    assert filed.status_code == 200, filed.text
    assert filed.json()["filed_at"] is not None
    assert filed.json()["filed_reference"] is None


@pytest.mark.integration
async def test_marking_twice_keeps_the_first_mark(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    draft = (await _create(ex, outcome)).json()
    first = await ex.client.post(
        f"/api/v1/appeal-drafts/{draft['id']}/mark-filed",
        json={"reference": "первый"},
        headers=ex.headers["resident"],
    )
    second = await ex.client.post(
        f"/api/v1/appeal-drafts/{draft['id']}/mark-filed",
        json={"reference": "второй"},
        headers=ex.headers["resident"],
    )
    assert second.status_code == 200
    assert second.json()["filed_at"] == first.json()["filed_at"]
    assert second.json()["filed_reference"] == "первый"


@pytest.mark.integration
async def test_another_residents_draft_is_not_found(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    draft = (await _create(ex, outcome)).json()
    # Сосед того же дома чужой черновик не видит и не правит.
    read = await ex.client.get(
        f"/api/v1/appeal-drafts/{draft['id']}", headers=ex.headers["neighbour"]
    )
    assert read.status_code == 404
    patched = await ex.client.patch(
        f"/api/v1/appeal-drafts/{draft['id']}",
        json={"text": "чужая правка", "version": 1},
        headers=ex.headers["neighbour"],
    )
    assert patched.status_code == 404
    filed = await ex.client.post(
        f"/api/v1/appeal-drafts/{draft['id']}/mark-filed", headers=ex.headers["neighbour"]
    )
    assert filed.status_code == 404


@pytest.mark.integration
async def test_a_neighbour_can_prepare_their_own_draft(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    mine = await _create(ex, outcome, actor="resident")
    theirs = await _create(ex, outcome, actor="neighbour")
    assert mine.status_code == 201 and theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]


@pytest.mark.integration
async def test_an_outsider_cannot_reach_the_house(ex) -> None:  # noqa: F811
    outcome = await _external_outcome(ex)
    response = await _create(ex, outcome, actor="outsider")
    assert response.status_code in {403, 404}


@pytest.mark.integration
async def test_a_draft_can_be_built_from_the_report_of_a_uk_ticket(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()
    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.report_id is not None
    response = await ex.client.post(
        "/api/v1/appeal-drafts",
        json={"house_id": str(ex.ids["h1"]), "report_id": str(outcome.report_id)},
        headers=ex.headers["resident"],
    )
    assert response.status_code == 201, response.text
    text = response.json()["text"]
    assert ELEVATOR in text
    # Подъезд из цитаты попадает в текст обращения.
    assert "Подъезд: 2" in text


@pytest.mark.integration
async def test_an_unknown_outcome_is_not_found(ex) -> None:  # noqa: F811
    await ex.bind()
    response = await ex.client.post(
        "/api/v1/appeal-drafts",
        json={
            "house_id": str(ex.ids["h1"]),
            "route_outcome_id": "00000000-0000-0000-0000-0000000000ff",
        },
        headers=ex.headers["resident"],
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_a_request_without_a_source_is_not_found(ex) -> None:  # noqa: F811
    await ex.bind()
    response = await ex.client.post(
        "/api/v1/appeal-drafts",
        json={"house_id": str(ex.ids["h1"])},
        headers=ex.headers["resident"],
    )
    assert response.status_code == 404
