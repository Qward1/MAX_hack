"""Штатные аудируемые операции платформы из консоли (D4, порядок в production).

Каждая операция требует оператора и основание и оставляет квитанцию
`operator.platform_ops` с прежним и новым значением. Решения по сигналам и
заявкам идут через те же сервисы, что и кабинет, от имени указанного сотрудника
(`--actor`, у него должны быть права на дом): их собственный аудит не меняется.

    python -m domsignal.tools.platform_ops rename-house --house-id … --name … --address …
    python -m domsignal.tools.platform_ops rename-company --company-id … --name …
    python -m domsignal.tools.platform_ops open-access --house-id … --enable
    python -m domsignal.tools.platform_ops dismiss-signal --signal-id … --actor …
    python -m domsignal.tools.platform_ops cancel-ticket --ticket-id … --actor …
    python -m domsignal.tools.platform_ops redact-report --report-id …
    python -m domsignal.tools.platform_ops rename-staff --user-id … --name …
    python -m domsignal.tools.platform_ops refresh-chat --binding-id …

Все команды принимают `--operator` и `--reason`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bootstrap import Container, build_container
from domsignal.contracts.signals import SignalDismiss
from domsignal.contracts.tickets import ReasonCommand
from domsignal.core.tickets import TicketAction
from domsignal.db.models import (
    ChatBinding,
    House,
    InboxReceipt,
    Incident,
    ManagementCompany,
    MAXChat,
    Report,
    Signal,
    Ticket,
    User,
)
from domsignal.services.onboarding import audit
from domsignal.services.resident_access import ResidentAccessService
from domsignal.settings import get_settings
from domsignal.tools import print_json

AUDIT_PREFIX = "operator:platform-ops:v1"
AUDIT_TYPE = "operator.platform_ops"


def receipt(
    session: AsyncSession,
    *,
    action: str,
    object_id: UUID,
    before: Any,
    after: Any,
    operator: str,
    reason: str,
) -> None:
    now = datetime.now(UTC)
    session.add(
        InboxReceipt(
            event_id=f"{AUDIT_PREFIX}:{action}:{object_id}:{now:%Y%m%dT%H%M%S%fZ}",
            event_type=AUDIT_TYPE,
            payload={
                "action": action,
                "object_id": str(object_id),
                "before": before,
                "after": after,
                "operator": operator,
                "reason": reason,
                "at": now.isoformat(),
            },
        )
    )


def check_operator(operator: str, reason: str) -> None:
    if not operator.strip() or not reason.strip() or max(len(operator), len(reason)) > 300:
        raise ValueError("A bounded --operator and --reason are required")


async def rename_house(
    session: AsyncSession, *, house_id: UUID, name: str, address: str, operator: str, reason: str
) -> dict[str, Any]:
    house = await session.get(House, house_id, with_for_update=True)
    if house is None:
        raise ValueError("House was not found")
    before = {"name": house.name, "address": house.address}
    house.name, house.address = name.strip()[:200], address.strip()
    after = {"name": house.name, "address": house.address}
    receipt(
        session,
        action="rename-house",
        object_id=house_id,
        before=before,
        after=after,
        operator=operator,
        reason=reason,
    )
    return {"house_id": str(house_id), **after}


async def rename_company(
    session: AsyncSession, *, company_id: UUID, name: str, operator: str, reason: str
) -> dict[str, Any]:
    company = await session.get(ManagementCompany, company_id, with_for_update=True)
    if company is None:
        raise ValueError("Company was not found")
    before = {"name": company.name}
    company.name = name.strip()[:200]
    receipt(
        session,
        action="rename-company",
        object_id=company_id,
        before=before,
        after={"name": company.name},
        operator=operator,
        reason=reason,
    )
    return {"company_id": str(company_id), "name": company.name}


async def rename_staff(
    session: AsyncSession, *, user_id: UUID, name: str, operator: str, reason: str
) -> dict[str, Any]:
    """Отображаемое имя сотрудника — без входа, прав и назначений."""
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise ValueError("User was not found")
    if not name.strip():
        raise ValueError("A non-empty --name is required")
    before = {"display_name": user.display_name}
    user.display_name = name.strip()[:200]
    receipt(
        session,
        action="rename-staff",
        object_id=user_id,
        before=before,
        after={"display_name": user.display_name},
        operator=operator,
        reason=reason,
    )
    return {"user_id": str(user_id), "display_name": user.display_name}


async def refresh_chat(
    container: Container, *, binding_id: UUID, operator: str, reason: str
) -> dict[str, Any]:
    """Сверить подключённый чат с MAX: название, бот и его права.

    Та же проверка, что после `/report` в чате (`verify_binding_health`): название
    берётся из MAX, без нужных прав привязка приостанавливается.
    """

    async def state(session: AsyncSession) -> dict[str, Any]:
        binding = await session.get(ChatBinding, binding_id)
        if binding is None:
            raise ValueError("Binding was not found")
        title = await session.scalar(
            select(MAXChat.title).where(MAXChat.max_chat_id == binding.max_chat_id)
        )
        return {"title": title, "status": binding.status}

    async with container.session_factory() as session, session.begin():
        before = await state(session)
        await container.chat_connections.verify_binding_health(session, binding_id)
    async with container.session_factory() as session, session.begin():
        after = await state(session)
        receipt(
            session,
            action="refresh-chat",
            object_id=binding_id,
            before=before,
            after=after,
            operator=operator,
            reason=reason,
        )
    return {"binding_id": str(binding_id), **after}


async def open_access(
    session: AsyncSession, *, house_id: UUID, enabled: bool, operator: str, reason: str
) -> dict[str, Any]:
    house = await session.get(House, house_id, with_for_update=True)
    if house is None:
        raise ValueError("House was not found")
    before = house.open_resident_access
    ended = await ResidentAccessService.set_open_access(
        session, house=house, enabled=enabled, actor_id=None
    )
    if before != enabled:
        audit(
            session,
            "house.open_access_enabled" if enabled else "house.open_access_disabled",
            None,
            house.id,
            reason,
        )
    receipt(
        session,
        action="open-access",
        object_id=house_id,
        before=before,
        after=enabled,
        operator=operator,
        reason=reason,
    )
    return {"house_id": str(house_id), "open_resident_access": enabled, "ended": ended}


#: Текст вместо скрытого описания проблемы (D4: снятие проверочных записей).
REDACTED = "Описание скрыто оператором платформы"


async def redact_report(
    session: AsyncSession, *, report_id: UUID, operator: str, reason: str
) -> dict[str, Any]:
    """Скрыть описание сообщения о проблеме и совпадающее описание проблемы.

    В квитанции — длина и хеш прежнего текста, не сам текст.
    """
    report = await session.get(Report, report_id, with_for_update=True)
    if report is None:
        raise ValueError("Report was not found")
    before = report.description
    digest = hashlib.sha256(before.encode("utf-8")).hexdigest()
    report.description = REDACTED
    incident = await session.get(Incident, report.incident_id, with_for_update=True)
    if incident is not None and incident.description == before:
        incident.description = REDACTED
    receipt(
        session,
        action="redact-report",
        object_id=report_id,
        before={"length": len(before), "sha256": digest},
        after=REDACTED,
        operator=operator,
        reason=reason,
    )
    return {"report_id": str(report_id), "incident_redacted": bool(incident)}


async def dismiss_signal(
    container: Container, *, signal_id: UUID, actor: UUID, operator: str, reason: str
) -> dict[str, Any]:
    async with container.session_factory() as session:
        signal = await session.get(Signal, signal_id)
        if signal is None:
            raise ValueError("Signal was not found")
        version = signal.version
    async with container.session_factory() as session:
        result = await container.signal_inbox.dismiss(
            session,
            actor_id=actor,
            signal_id=signal_id,
            payload=SignalDismiss(expected_version=version, reason="resolved", note=reason),
            idempotency_key=f"platform-ops:{uuid4()}",
        )
    async with container.session_factory() as session, session.begin():
        receipt(
            session,
            action="dismiss-signal",
            object_id=signal_id,
            before="open",
            after="dismissed",
            operator=operator,
            reason=reason,
        )
    return {"signal_id": str(signal_id), "status": result.signal.status}


async def cancel_ticket(
    container: Container, *, ticket_id: UUID, actor: UUID, operator: str, reason: str
) -> dict[str, Any]:
    async with container.session_factory() as session:
        ticket = await session.get(Ticket, ticket_id)
        if ticket is None:
            raise ValueError("Ticket was not found")
        version, before = ticket.version, ticket.status
    async with container.session_factory() as session:
        result = await container.ticket_service.command(
            session,
            actor_id=actor,
            ticket_id=ticket_id,
            action=TicketAction.CANCEL,
            payload=ReasonCommand(expected_version=version, reason=reason),
            idempotency_key=f"platform-ops:{uuid4()}",
        )
    async with container.session_factory() as session, session.begin():
        receipt(
            session,
            action="cancel-ticket",
            object_id=ticket_id,
            before=before,
            after=result.ticket.status,
            operator=operator,
            reason=reason,
        )
    return {"ticket_id": str(ticket_id), "status": result.ticket.status}


async def run(args: argparse.Namespace) -> None:
    check_operator(args.operator, args.reason)
    container = build_container(get_settings())
    try:
        common = {"operator": args.operator, "reason": args.reason}
        if args.command == "dismiss-signal":
            result = await dismiss_signal(
                container, signal_id=args.signal_id, actor=args.actor, **common
            )
        elif args.command == "cancel-ticket":
            result = await cancel_ticket(
                container, ticket_id=args.ticket_id, actor=args.actor, **common
            )
        elif args.command == "refresh-chat":
            result = await refresh_chat(container, binding_id=args.binding_id, **common)
        else:
            async with container.session_factory() as session, session.begin():
                if args.command == "rename-house":
                    result = await rename_house(
                        session,
                        house_id=args.house_id,
                        name=args.name,
                        address=args.address,
                        **common,
                    )
                elif args.command == "redact-report":
                    result = await redact_report(session, report_id=args.report_id, **common)
                elif args.command == "rename-staff":
                    result = await rename_staff(
                        session, user_id=args.user_id, name=args.name, **common
                    )
                elif args.command == "rename-company":
                    result = await rename_company(
                        session, company_id=args.company_id, name=args.name, **common
                    )
                else:
                    result = await open_access(
                        session, house_id=args.house_id, enabled=args.enable, **common
                    )
        print_json(result)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audited platform operations")
    commands = parser.add_subparsers(dest="command", required=True)
    house = commands.add_parser("rename-house")
    house.add_argument("--house-id", dest="house_id", type=UUID, required=True)
    house.add_argument("--name", required=True)
    house.add_argument("--address", required=True)
    company = commands.add_parser("rename-company")
    company.add_argument("--company-id", dest="company_id", type=UUID, required=True)
    company.add_argument("--name", required=True)
    access = commands.add_parser("open-access")
    access.add_argument("--house-id", dest="house_id", type=UUID, required=True)
    access.add_argument("--enable", action=argparse.BooleanOptionalAction, required=True)
    signal = commands.add_parser("dismiss-signal")
    signal.add_argument("--signal-id", dest="signal_id", type=UUID, required=True)
    signal.add_argument("--actor", type=UUID, required=True)
    ticket = commands.add_parser("cancel-ticket")
    ticket.add_argument("--ticket-id", dest="ticket_id", type=UUID, required=True)
    ticket.add_argument("--actor", type=UUID, required=True)
    redact = commands.add_parser("redact-report")
    redact.add_argument("--report-id", dest="report_id", type=UUID, required=True)
    staff = commands.add_parser("rename-staff")
    staff.add_argument("--user-id", dest="user_id", type=UUID, required=True)
    staff.add_argument("--name", required=True)
    chat = commands.add_parser("refresh-chat")
    chat.add_argument("--binding-id", dest="binding_id", type=UUID, required=True)
    for sub in (house, company, access, signal, ticket, redact, staff, chat):
        sub.add_argument("--operator", required=True)
        sub.add_argument("--reason", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
