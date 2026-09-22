"""Сигналы дома без HTTP: сила, подтип, территория, маршрут, цитаты, причина.

Инструмент проверки и показа до среза P5 (Signal Inbox). Только чтение:
транзакция объявляется `READ ONLY`, ничего не создаётся и не меняется.

    python -m domsignal.tools.signals_preview --house <id> [--pool inbox|audit]
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.core.signals import STRENGTH_RANK, author_label
from domsignal.db.models import RouteOutcome, Signal, SignalEvent, SignalQuote
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import get_settings
from domsignal.tools import print_json

Pool = Literal["inbox", "audit"]

_DISPOSITION: dict[str, str] = {"inbox": "inbox", "audit": "audit_pool"}

#: Сколько последних событий аудита печатается на сигнал.
MAX_EVENTS = 12


def _place(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not value or value.get("value") in (None, "unknown"):
        return None
    return {"value": value.get("value"), "quote": value.get("quote")}


async def preview(session: AsyncSession, *, house_id: UUID, pool: Pool) -> list[dict[str, Any]]:
    """Сигналы дома в выбранном пуле: сначала сильные, затем свежие."""
    await session.execute(text("SET TRANSACTION READ ONLY"))
    signals = list(
        await session.scalars(
            select(Signal).where(
                Signal.house_id == house_id, Signal.disposition == _DISPOSITION[pool]
            )
        )
    )
    signals.sort(
        key=lambda item: (-STRENGTH_RANK.get(item.strength, 0), -item.last_seen_at.timestamp())
    )
    result: list[dict[str, Any]] = []
    for signal in signals:
        outcome = (
            await session.get(RouteOutcome, signal.route_outcome_id)
            if signal.route_outcome_id
            else None
        )
        quotes = list(
            await session.scalars(
                select(SignalQuote)
                .where(SignalQuote.signal_id == signal.id)
                .order_by(SignalQuote.sent_at, SignalQuote.id)
            )
        )
        events = list(
            await session.scalars(
                select(SignalEvent)
                .where(SignalEvent.signal_id == signal.id)
                .order_by(SignalEvent.created_at, SignalEvent.id)
            )
        )
        emergency = signal.emergency or {}
        result.append(
            {
                "id": str(signal.id),
                "status": signal.status,
                "strength": signal.strength,
                "strength_reason": signal.strength_reason,
                "disposition": signal.disposition,
                "audit_reason": signal.audit_reason,
                "subtype": signal.subtype,
                "category": signal.product_category,
                "object": signal.object_label,
                "territory": {
                    "location_scope": signal.location_scope,
                    "quote": (signal.location or {}).get("quote"),
                },
                "entrance": _place(signal.entrance),
                "floor": _place(signal.floor),
                "since": _place(signal.since),
                "emergency": {
                    "kinds": emergency.get("kinds", []),
                    "sources": emergency.get("sources", []),
                    "preliminary": emergency.get("preliminary", False),
                    "downgrades": emergency.get("downgrades", []),
                },
                "route": (
                    {
                        "route_type": outcome.route_type,
                        "organization_id": outcome.organization_id,
                        "channel_id": outcome.channel_id,
                        "decision": outcome.decision,
                    }
                    if outcome
                    else None
                ),
                "counters": {"lines": signal.report_count, "authors": signal.author_count},
                "first_seen_at": signal.first_seen_at.isoformat(),
                "last_seen_at": signal.last_seen_at.isoformat(),
                "flags": list(signal.flags or []),
                "quotes": [
                    {
                        "author": author_label(quote.author_ref),
                        "sent_at": quote.sent_at.isoformat(),
                        "text": quote.text,
                    }
                    for quote in quotes
                ],
                "events": [
                    {"kind": event.kind, "details": event.details}
                    for event in events[-MAX_EVENTS:]
                ],
            }
        )
    return result


async def run(house_id: UUID, pool: Pool) -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            try:
                payload = await preview(session, house_id=house_id, pool=pool)
            finally:
                await session.rollback()
        print_json({"house_id": str(house_id), "pool": pool, "signals": payload})
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print passive signals of a house (read-only)")
    parser.add_argument("--house", type=UUID, required=True)
    parser.add_argument("--pool", choices=["inbox", "audit"], default="inbox")
    args = parser.parse_args()
    asyncio.run(run(args.house, args.pool))


if __name__ == "__main__":
    main()
