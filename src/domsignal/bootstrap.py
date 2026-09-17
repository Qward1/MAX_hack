from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from domsignal.bot.ingress import InboundService
from domsignal.bot.transport import MaxTransport, OffTransport, RecordingTransport
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.membership import MembershipService
from domsignal.services.reports import DemoRule, ReportService
from domsignal.services.sessions import SessionService
from domsignal.settings import MaxTransportMode, Settings
from domsignal.worker.handlers import WorkerHandlers


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    session_service: SessionService
    membership_service: MembershipService
    report_service: ReportService
    inbound_service: InboundService
    transport: MaxTransport
    worker_handlers: WorkerHandlers


def build_container(settings: Settings) -> Container:
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    transport: MaxTransport
    if settings.max_transport is MaxTransportMode.RECORDING:
        transport = RecordingTransport()
    else:
        # Live MAX HTTP transport is deliberately not part of FND-01.
        transport = OffTransport()
    report_service = ReportService(
        demo_rule=DemoRule(
            source_url="https://example.invalid/domsignal-demo-source",
            source_title="Демонстрационный пакет ДомСигнала",
            verification_status="demo",
            note="Правило не проверено; нормативный срок не рассчитан.",
        )
    )
    worker_handlers = WorkerHandlers(
        session_factory=session_factory,
        report_service=report_service,
        transport=transport,
    )
    return Container(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        session_service=SessionService(
            secret=settings.session_secret,
            ttl_seconds=settings.session_ttl_seconds,
        ),
        membership_service=MembershipService(),
        report_service=report_service,
        inbound_service=InboundService(),
        transport=transport,
        worker_handlers=worker_handlers,
    )
