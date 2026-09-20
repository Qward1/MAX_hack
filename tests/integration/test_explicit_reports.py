"""Явный путь целиком: свободный текст → разбор → маршрут → следующий шаг.

Проверяется то, из-за чего срез вообще нужен: сообщение обычными словами
доходит до правильного следующего шага, и результат не зависит от того, жив ли
AI-пул. Заявка УК создаётся только для зоны УК; внешнее обращение отправляет
человек сам, и продукт этого не подделывает.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select, update

from domsignal.ai.providers.fake import FakeProvider
from domsignal.db.models import (
    ExplicitIntake,
    Incident,
    Job,
    NotificationDelivery,
    Report,
    RouteOutcome,
)
from domsignal.services.action_cards import FORBIDDEN_PHRASES
from domsignal.services.explicit_reports import DISPATCHER_REVIEW_NOTE
from tests.integration.explicit_harness import ex  # noqa: F401

ELEVATOR = "опять лифт во втором подъезде стоит"
STREET_LIGHT = "на улице у остановки не горят фонари"
NOISE = "спасибо всем за помощь вчера"
GAS = "в третьем подъезде пахнет газом"
FLOOD = "в подвале прорвало трубу, вода поднимается"


async def _past_due(harness: Any) -> None:
    """Сдвинуть сторожевую задачу в прошлое: 30 секунд «прошли»."""
    async with harness.container.session_factory() as session, session.begin():
        await session.execute(
            update(Job)
            .where(Job.kind == "report.fallback")
            .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
        )


async def _cards(harness: Any) -> list[NotificationDelivery]:
    return await harness.all(
        select(NotificationDelivery).where(
            NotificationDelivery.purpose == "route_action_card"
        )
    )


# --------------------------------------------------------------- зона УК


@pytest.mark.integration
async def test_uk_zone_with_a_confident_location_creates_a_ticket(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()

    report = await ex.scalar(select(Report))
    assert report is not None
    assert report.description == ELEVATOR
    assert report.category == "elevator"
    # Провайдера нет, разобрали правила — режим классификации честный.
    assert report.classification_mode == "rules"
    assert report.provenance == "max_group"
    assert report.analysis is not None
    assert report.analysis["subtype"] == "elevator.stopped"
    assert report.analysis["confident"] is True
    assert report.analysis["route_type"] == "uk_internal"
    # Текста реплики в провенансе разбора нет.
    assert ELEVATOR not in str(report.analysis)

    incident = await ex.scalar(select(Incident))
    # Подъезд взят из цитаты, а не угадан.
    assert incident.location_entrance == "2"
    assert incident.location_floor is None

    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.decision == "ticket" and outcome.report_id == report.id
    assert outcome.route_type == "uk_internal" and outcome.source == "group_report"

    intake = await ex.scalar(select(ExplicitIntake))
    assert intake.state == "done" and intake.result_kind == "ticket"
    # Без опасности личная карточка не нужна: житель уже в обычном потоке заявки.
    assert await _cards(ex) == []


@pytest.mark.integration
async def test_ticket_is_visible_through_the_incident_read_model(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()
    incident = await ex.scalar(select(Incident))
    response = await ex.client.get(
        f"/api/v1/incidents/{incident.id}", headers=ex.headers["resident"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["location"] == {
        "entrance": "2",
        "floor": None,
        "label": None,
        "observed_since": None,
    }


# ------------------------------------------------------------ внешний маршрут


@pytest.mark.integration
async def test_external_route_creates_no_ticket_but_sends_a_card(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()

    # Заявка УК не создаётся: за уличное освещение отвечает не УК.
    assert await ex.scalar(select(func.count()).select_from(Report)) == 0
    assert await ex.scalar(select(func.count()).select_from(Incident)) == 0

    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.decision == "external" and outcome.report_id is None
    assert outcome.route_type == "municipality"
    assert outcome.channel_id == "pos_gosuslugi"
    assert outcome.intake_event_id is not None

    intake = await ex.scalar(select(ExplicitIntake))
    assert intake.state == "done" and intake.result_kind == "external_route"

    cards = await _cards(ex)
    assert len(cards) == 1
    assert cards[0].route_outcome_id == outcome.id and cards[0].ticket_id is None
    assert cards[0].launch_ref.startswith("r_")
    assert cards[0].status == "accepted"

    destination, _, message = ex.messaging.sent[-1]
    assert destination == "502"
    assert "Проблема, вероятно, относится не к вашей УК" in message.text
    assert "ДомСигнал не отправляет обращения за вас" in message.text
    lowered = message.text.lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, phrase


@pytest.mark.integration
async def test_external_card_never_claims_the_message_was_forwarded(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {STREET_LIGHT}")
    await ex.drain_all()
    text = ex.messaging.sent[-1][2].text
    for claim in ("заявка отправлена", "обращение зарегистрировано", "передано в"):
        assert claim not in text.lower()


# ----------------------------------------------------------------- unknown


@pytest.mark.integration
async def test_unknown_route_creates_an_other_report_for_the_dispatcher(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {NOISE}")
    await ex.drain_all()

    report = await ex.scalar(select(Report))
    assert report is not None and report.category == "other"
    assert report.analysis["confident"] is False
    assert report.analysis["reason"] == "no_signals"

    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.decision == "needs_clarification" and outcome.route_type == "unknown"

    intake = await ex.scalar(select(ExplicitIntake))
    assert intake.result_kind == "needs_clarification"

    # Житель получает честную формулировку, а не молчание.
    assert len(await _cards(ex)) == 1
    assert DISPATCHER_REVIEW_NOTE in ex.messaging.sent[-1][2].text


# ------------------------------------------------------------------ опасность


@pytest.mark.integration
async def test_danger_always_sends_the_safety_block_first(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {GAS}")
    await ex.drain_all()

    message = ex.messaging.sent[-1][2]
    # Памятка и телефон 112 стоят раньше всего остального.
    assert "112" in message.text
    assert message.text.index("112") < message.text.index("Похоже на ситуацию")
    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.route_type == "emergency_service" and outcome.decision == "external"


@pytest.mark.integration
async def test_danger_inside_the_uk_zone_gets_both_a_ticket_and_a_safety_message(
    ex,  # noqa: F811
) -> None:
    await ex.bind()
    await ex.report(f"/report {FLOOD}")
    await ex.drain_all()

    report = await ex.scalar(select(Report))
    assert report is not None and report.category == "water"
    assert report.analysis["danger_kinds"] == ["flooding"]
    outcome = await ex.scalar(select(RouteOutcome))
    assert outcome.route_type == "uk_internal" and outcome.decision == "ticket"
    # Опасность даёт личное сообщение при любом маршруте.
    cards = await _cards(ex)
    assert len(cards) == 1
    assert "112" in ex.messaging.sent[-1][2].text


# ------------------------------------------------------------------- гонка


@pytest.mark.integration
async def test_both_jobs_produce_exactly_one_result(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    # Сначала разбор ядром, затем сторож на том же событии.
    await ex.drain("ai")
    await _past_due(ex)
    await ex.drain_all()

    assert await ex.scalar(select(func.count()).select_from(Report)) == 1
    assert await ex.scalar(select(func.count()).select_from(RouteOutcome)) == 1
    assert await ex.scalar(select(func.count()).select_from(Incident)) == 1
    jobs = {
        job.kind: job.status
        for job in await ex.all(
            select(Job).where(Job.kind.in_(["ai.report.analyze", "report.fallback"]))
        )
    }
    # Обе задачи успешны: вторая честно ничего не сделала.
    assert jobs == {"ai.report.analyze": "succeeded", "report.fallback": "succeeded"}


@pytest.mark.integration
async def test_repeated_webhook_delivery_yields_one_ticket(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}", mid="dup")
    await ex.report(f"/report {ELEVATOR}", mid="dup")
    await _past_due(ex)
    await ex.drain_all()
    assert await ex.scalar(select(func.count()).select_from(Report)) == 1
    assert await ex.scalar(select(func.count()).select_from(RouteOutcome)) == 1


# ----------------------------------------------- AI-пул не работает


@pytest.mark.integration
async def test_a_stopped_ai_pool_still_gives_the_resident_a_result(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}")
    # AI-пул не запущен: работает только операционный.
    await ex.drain("operational")
    assert await ex.scalar(select(func.count()).select_from(Report)) == 0

    # Проходит задержка сторожа — и правила разбирают то же сообщение.
    await _past_due(ex)
    await ex.drain("operational")

    report = await ex.scalar(select(Report))
    assert report is not None and report.classification_mode == "rules"
    intake = await ex.scalar(select(ExplicitIntake))
    assert intake.state == "done" and intake.claimed_by == "report.fallback"


@pytest.mark.integration
async def test_an_unavailable_provider_degrades_to_rules(ex) -> None:  # noqa: F811
    await ex.bind()
    broken = FakeProvider("error")
    ex.container.explicit_reports.analyzer.provider = broken
    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()

    report = await ex.scalar(select(Report))
    assert report is not None
    assert broken.requests, "провайдер должен был получить вызов"
    assert report.analysis["state"] == "fallback_provider_error"
    assert report.analysis["provider_called"] is True
    assert report.classification_mode == "rules"
    assert report.category == "elevator"


# -------------------------------------------------------------------- бюджет


@pytest.mark.integration
async def test_an_exhausted_budget_analyses_with_rules_and_makes_no_call(ex) -> None:  # noqa: F811
    from domsignal.ai import CircuitBreaker, ConcurrencyLimiter, ResilientProvider, WindowAnalyzer
    from domsignal.services.ai_budget import PostgresBudgetGuard

    await ex.bind()
    provider = FakeProvider("ok")
    budget = PostgresBudgetGuard(ex.container.session_factory, daily_calls=0)
    ex.container.explicit_reports.analyzer = WindowAnalyzer(
        ResilientProvider(
            provider,
            breaker=CircuitBreaker(),
            limiter=ConcurrencyLimiter(2),
            budget=budget,
        )
    )
    ex.container.explicit_reports.budget = budget

    await ex.report(f"/report {ELEVATOR}")
    await ex.drain_all()

    report = await ex.scalar(select(Report))
    assert report is not None
    # Бюджет исчерпан: обращения к провайдеру не было вовсе.
    assert provider.requests == []
    assert report.analysis["state"] == "fallback_budget"
    assert report.analysis["provider_called"] is False
    assert report.classification_mode == "rules"


# ------------------------------------------------------------ чужие и стале


@pytest.mark.integration
async def test_an_author_outside_the_house_produces_nothing(ex) -> None:  # noqa: F811
    await ex.bind()
    # 504 — житель другого дома, в этом доме прав нет.
    await ex.report(f"/report {ELEVATOR}", actor=504)
    await ex.drain_all()
    assert await ex.scalar(select(func.count()).select_from(Report)) == 0
    assert await ex.scalar(select(func.count()).select_from(RouteOutcome)) == 0
    intake = await ex.scalar(select(ExplicitIntake))
    assert intake.state == "done" and intake.result_kind == "ignored"


@pytest.mark.integration
async def test_an_unknown_max_author_produces_nothing(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report(f"/report {ELEVATOR}", actor=999)
    await ex.drain_all()
    assert await ex.scalar(select(func.count()).select_from(Report)) == 0
    intake = await ex.scalar(select(ExplicitIntake))
    assert intake.result_kind == "ignored"
