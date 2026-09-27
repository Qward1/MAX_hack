"""Проблема закрывается вместе со своей заявкой (INCIDENT-CLOSE-WITH-TICKET-2026-09-28).

Решение владельца по аудиту 27.09 меняет контракт A-16.1 («Incident.status не
меняется»): заявка закрыта подтверждением жителей — проблема «Решена»; заявка
отменена с причиной — проблема закрыта с этой причиной; «Проблема осталась»
к закрытой заявке — та же заявка в работу и проблема снова «Открыта».
Проблемы без заявки (внешний маршрут, черновик жителя) не меняются.

Вызывающий держит транзакцию и блокировку строки проблемы (порядок A-16:
дом → проблема → заявка), поэтому гонка подтверждения и возражения
сериализуется, а повтор не создаёт второго события.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import Incident, IncidentEvent, Ticket
from domsignal.db.repositories.incidents import OPEN_STATUSES

Closure = Literal["residents_confirmed", "ticket_cancelled"]

#: Статус проблемы после закрытия заявки: подтверждение жителей — «Решена»,
#: отмена заявки — закрыта без подтверждения.
CLOSED_STATUS: dict[Closure, str] = {
    "residents_confirmed": "resolved",
    "ticket_cancelled": "dismissed",
}
CLOSED_STATUSES = frozenset(CLOSED_STATUS.values())


async def close_with_ticket(
    session: AsyncSession,
    ticket: Ticket,
    *,
    closure: Closure,
    actor_id: UUID | None,
    reason: str | None = None,
) -> bool:
    """Закрыть открытую проблему заявки. `False`, если закрывать нечего."""
    incident = await session.get(Incident, ticket.incident_id)
    if incident is None or incident.status not in OPEN_STATUSES:
        return False
    now = datetime.now(UTC)
    previous = incident.status
    incident.status = CLOSED_STATUS[closure]
    incident.resolved_at = now
    incident.closure = closure
    incident.closure_reason = reason
    incident.status_changed_at = now
    session.add(
        IncidentEvent(
            incident_id=incident.id,
            kind="resolved" if closure == "residents_confirmed" else "closed_cancelled",
            from_status=previous,
            to_status=incident.status,
            ticket_id=ticket.id,
            actor_id=actor_id,
            reason=reason,
        )
    )
    return True


async def reopen_with_ticket(session: AsyncSession, ticket: Ticket, *, actor_id: UUID) -> bool:
    """«Проблема осталась» к закрытой заявке: проблема снова открыта."""
    incident = await session.get(Incident, ticket.incident_id)
    if incident is None or incident.status != CLOSED_STATUS["residents_confirmed"]:
        return False
    now = datetime.now(UTC)
    previous = incident.status
    incident.status = "open"
    incident.resolved_at = None
    incident.closure = None
    incident.closure_reason = None
    incident.status_changed_at = now
    session.add(
        IncidentEvent(
            incident_id=incident.id,
            kind="reopened",
            from_status=previous,
            to_status="open",
            ticket_id=ticket.id,
            actor_id=actor_id,
        )
    )
    return True


__all__ = ["CLOSED_STATUSES", "Closure", "close_with_ticket", "reopen_with_ticket"]
