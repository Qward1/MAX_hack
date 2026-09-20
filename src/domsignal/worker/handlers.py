from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.bot.chat_provider import MaxProviderError
from domsignal.bot.transport import MaxTransport, OutboundNotification
from domsignal.contracts.chat_connections import GroupMessage
from domsignal.contracts.incidents import ReportCreate
from domsignal.contracts.jobs import DiagnosticJobRequest, NormalizedInboundEvent
from domsignal.core.chat_connections import TERMINAL
from domsignal.db.repositories.access import AccessRepository
from domsignal.services.chat_connections import ChatConnectionError, ChatConnectionService
from domsignal.services.errors import AccessDenied, ResourceNotFound
from domsignal.services.explicit_reports import ExplicitReportService
from domsignal.services.notifications import TicketNotificationHandler
from domsignal.services.reports import ReportService

JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class WorkerHandlers:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        report_service: ReportService,
        transport: MaxTransport,
        chat_connections: ChatConnectionService | None = None,
        notifications: TicketNotificationHandler | None = None,
        explicit_reports: ExplicitReportService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.report_service = report_service
        self.transport = transport
        self.chat_connections = chat_connections
        self.notifications = notifications
        self.explicit_reports = explicit_reports

    @property
    def mapping(self) -> dict[str, JobHandler]:
        handlers: dict[str, JobHandler] = {
            "diagnostic.record": self.diagnostic_record,
            "inbound.report": self.inbound_report,
            "max.connection.verify": self.verify_connection,
            "max.binding.health": self.verify_binding_health,
            "max.group.report": self.group_report,
        }
        if self.notifications:
            handlers["max.ticket.callback"] = self.notifications.callback
            handlers["max.ticket.answer"] = self.notifications.answer
        if self.explicit_reports:
            # Разбор ядром живёт в AI-пуле, сторож правил — в операционном.
            handlers["ai.report.analyze"] = self.explicit_reports.analyze_with_core
            handlers["report.fallback"] = self.explicit_reports.analyze_with_rules
        return handlers

    async def verify_connection(self, payload: dict[str, Any]) -> None:
        assert self.chat_connections is not None
        async with self.session_factory() as session, session.begin():
            request = await self.chat_connections.verify(
                session,
                UUID(payload["connection_request_id"]),
            )
            error = request.last_error_code if request.status not in TERMINAL else None
        if error in {"max_temporarily_unavailable", "max_not_configured"}:
            # Persist chat_detected before retrying with the existing durable worker.
            raise MaxProviderError(error, temporary=True)

    async def verify_binding_health(self, payload: dict[str, Any]) -> None:
        assert self.chat_connections is not None
        async with self.session_factory() as session, session.begin():
            await self.chat_connections.verify_binding_health(
                session,
                UUID(payload["chat_binding_id"]),
            )

    async def group_report(self, payload: dict[str, Any]) -> None:
        assert self.chat_connections is not None
        event = GroupMessage.model_validate(payload)
        # Permission freshness is checked before each actual group side effect.
        async with self.session_factory() as session, session.begin():
            await self.chat_connections.verify_binding_health(session, event.chat_binding_id)
        async with self.session_factory() as session, session.begin():
            actor = await AccessRepository(session).user_by_max_id(event.external_user_id)
            if actor is None:
                return
            try:
                context = await self.chat_connections.resolve_context(
                    session,
                    actor_id=actor.id,
                    chat_id=event.chat_id,
                    binding_id=event.chat_binding_id,
                    version=event.binding_version,
                    occurred_at=event.occurred_at,
                )
            except (ChatConnectionError, AccessDenied, ResourceNotFound):
                return  # Stale/unauthorized is terminal, not a retry in another context.
            parts = event.text.split(maxsplit=2)
            if len(parts) != 3 or parts[0] != "/report":
                return
            try:
                report = ReportCreate(
                    house_id=context.house_id,
                    category=parts[1],
                    description=parts[2],
                    classification_mode="manual",
                )
            except ValidationError:
                return
            await self.report_service.create_in_context(
                session,
                context=context,
                payload=report,
                idempotency_key=f"group:{event.event_id}",
            )
        # No automatic broadcast/cross-chat forwarding or new outbound transport.

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
