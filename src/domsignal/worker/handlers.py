from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.transport import MaxTransport, OutboundNotification
from domsignal.contracts.incidents import ReportCreate
from domsignal.contracts.jobs import DiagnosticJobRequest, NormalizedInboundEvent
from domsignal.db.repositories.access import AccessRepository
from domsignal.services.errors import AccessDenied
from domsignal.services.reports import ReportService

JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class WorkerHandlers:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        report_service: ReportService,
        transport: MaxTransport,
    ) -> None:
        self.session_factory = session_factory
        self.report_service = report_service
        self.transport = transport

    @property
    def mapping(self) -> dict[str, JobHandler]:
        return {
            "diagnostic.record": self.diagnostic_record,
            "inbound.report": self.inbound_report,
        }

    async def diagnostic_record(self, payload: dict[str, Any]) -> None:
        request = DiagnosticJobRequest.model_validate(payload)
        await self.transport.send(
            OutboundNotification(destination=request.destination, text=request.text)
        )

    async def inbound_report(self, payload: dict[str, Any]) -> None:
        event = NormalizedInboundEvent.model_validate(payload)
        async with self.session_factory() as lookup_session:
            actor = await AccessRepository(lookup_session).user_by_max_id(event.external_user_id)
            if actor is None:
                raise AccessDenied("Inbound actor has no linked DomSignal user")
            actor_id = actor.id
        async with self.session_factory() as report_session:
            result = await self.report_service.create(
                report_session,
                actor_id=actor_id,
                payload=ReportCreate(
                    house_id=event.house_id,
                    category=event.category,
                    description=event.description,
                    classification_mode="manual",
                ),
                idempotency_key=f"inbound:{event.event_id}",
                provenance="max_replay",
            )
        await self.transport.send(
            OutboundNotification(
                destination=event.external_user_id,
                text=f"Диагностическое событие сохранено: {result.incident.title}",
            )
        )
