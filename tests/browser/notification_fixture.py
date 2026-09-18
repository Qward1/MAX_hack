"""Read-only delivery inspection for opted-in local browser tests; no API fixture route."""

import asyncio
import json
import os
import sys
from uuid import UUID

from sqlalchemy import select

from domsignal.db.models import NotificationDelivery, Ticket
from domsignal.db.session import create_engine, create_session_factory
from domsignal.tools.seed_tickets import seed_id


async def main():
    if os.getenv("APP_ENV") != "test" or os.getenv("ND_FIXTURES") != "1":
        raise RuntimeError("ND fixture opt-in required")
    engine = create_engine(os.environ["DATABASE_URL"])
    async with create_session_factory(engine)() as s:
        ticket = await s.get(Ticket, UUID(sys.argv[1]))
        row = await s.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.ticket_id == ticket.id,
                NotificationDelivery.work_attempt_id == ticket.latest_attempt_id,
                NotificationDelivery.recipient_user_id == seed_id("resident"),
            )
        )
        print(
            json.dumps(
                None
                if row is None
                else {
                    "ref": row.launch_ref,
                    "status": row.status,
                    "attempt": str(row.work_attempt_id),
                    "reconciled": row.applied_version == ticket.version,
                    "message_id": row.provider_message_id,
                }
            )
        )
    await engine.dispose()


asyncio.run(main())
