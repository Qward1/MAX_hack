"""D4, П-9: штатные аудируемые операции платформы из консоли."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from domsignal.db.models import (
    House,
    InboxReceipt,
    Incident,
    ManagementCompany,
    Report,
    Signal,
    Ticket,
)
from domsignal.tools import platform_ops
from tests.integration.explicit_harness import ex  # noqa: F401
from tests.integration.passive_harness import pv  # noqa: F401

OPS = {"operator": "pytest", "reason": "проверка завершена"}


async def receipts(harness: Any, action: str) -> list[dict[str, Any]]:
    rows = await harness.all(
        select(InboxReceipt).where(InboxReceipt.event_type == platform_ops.AUDIT_TYPE)
    )
    return [row.payload for row in rows if row.payload["action"] == action]


def test_every_operation_needs_an_operator_and_a_reason() -> None:
    for operator, reason in (("", "x"), ("x", " "), ("x" * 301, "x")):
        with pytest.raises(ValueError, match="--operator and --reason"):
            platform_ops.check_operator(operator, reason)


@pytest.mark.integration
async def test_rename_and_open_access_leave_receipts_with_before_and_after(ex) -> None:  # noqa: F811
    factory = ex.container.session_factory
    async with factory() as session, session.begin():
        await platform_ops.rename_house(
            session,
            house_id=ex.ids["h1"],
            name="Казань, ул. Проверочная, 17",
            address="Казань, ул. Проверочная, 17",
            **OPS,
        )
        await platform_ops.rename_company(
            session, company_id=ex.ids["tenant"], name="УК «Проверочная, 17»", **OPS
        )
        await platform_ops.open_access(session, house_id=ex.ids["h1"], enabled=True, **OPS)
    house = await ex.scalar(select(House).where(House.id == ex.ids["h1"]))
    assert (house.name, house.address, house.open_resident_access) == (
        "Казань, ул. Проверочная, 17",
        "Казань, ул. Проверочная, 17",
        True,
    )
    company = await ex.scalar(
        select(ManagementCompany).where(ManagementCompany.id == ex.ids["tenant"])
    )
    assert company.name == "УК «Проверочная, 17»"
    [renamed] = await receipts(ex, "rename-house")
    assert renamed["before"]["address"] == "Казань, Синтетическая улица, 1"
    assert renamed["after"]["name"] == "Казань, ул. Проверочная, 17"
    assert (renamed["operator"], renamed["reason"]) == ("pytest", "проверка завершена")
    [company_receipt] = await receipts(ex, "rename-company")
    assert company_receipt["before"] == {"name": "Явный путь УК"}
    [access] = await receipts(ex, "open-access")
    assert (access["before"], access["after"]) == (False, True)


@pytest.mark.integration
async def test_cancel_ticket_goes_through_the_ticket_service(ex) -> None:  # noqa: F811
    await ex.bind()
    await ex.report("/report опять лифт во втором подъезде стоит")
    await ex.drain_all()
    ticket = await ex.scalar(select(Ticket))
    assert ticket is not None and ticket.status == "new"
    result = await platform_ops.cancel_ticket(
        ex.container, ticket_id=ticket.id, actor=ex.ids["admin"], **OPS
    )
    assert result["status"] == "cancelled"
    [cancelled] = await receipts(ex, "cancel-ticket")
    assert (cancelled["before"], cancelled["after"]) == ("new", "cancelled")
    report = await ex.scalar(select(Report))
    async with ex.container.session_factory() as session, session.begin():
        await platform_ops.redact_report(session, report_id=report.id, **OPS)
    redacted = await ex.scalar(select(Report).where(Report.id == report.id))
    incident = await ex.scalar(select(Incident).where(Incident.id == report.incident_id))
    assert redacted.description == incident.description == platform_ops.REDACTED
    [hidden] = await receipts(ex, "redact-report")
    assert hidden["before"]["length"] > 0 and "лифт" not in str(hidden)
    # Посторонний сотрудник заявку не отменит: права проверяет сервис заявок.
    with pytest.raises(Exception):  # noqa: B017 - любой отказ сервиса
        await platform_ops.cancel_ticket(
            ex.container, ticket_id=ticket.id, actor=ex.ids["outsider"], **OPS
        )


@pytest.mark.integration
async def test_dismiss_signal_goes_through_the_signal_inbox(pv) -> None:  # noqa: F811
    from tests.integration.test_signal_inbox import lift

    await pv.bind()
    signal = await lift(pv)
    result = await platform_ops.dismiss_signal(
        pv.container, signal_id=signal.id, actor=pv.ids["admin1"], **OPS
    )
    assert result["status"] == "dismissed"
    stored = await pv.scalar(select(Signal).where(Signal.id == signal.id))
    assert (stored.decision_reason, stored.decision_note) == ("resolved", "проверка завершена")
    [dismissed] = await receipts(pv, "dismiss-signal")
    assert dismissed["after"] == "dismissed"
