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

Все команды принимают `--operator` и `--reason`.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bootstrap import Container, build_container
from domsignal.contracts.signals import SignalDismiss
from domsignal.contracts.tickets import ReasonCommand
from domsignal.core.tickets import TicketAction
from domsignal.db.models import House, InboxReceipt, ManagementCompany, Signal, Ticket
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
    for sub in (house, company, access, signal, ticket):
        sub.add_argument("--operator", required=True)
        sub.add_argument("--reason", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
