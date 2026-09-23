"""Выгрузка реплик сессии D2 из буфера пассивного чтения (только чтение).

Формат задан P6 (`datasets/d2/README.md`, «Формат выгрузки (P7b → DEV-A)»):
JSONL, одна строка на реплику, без идентификаторов MAX и людей — `mid` и
`reply_to` заменены хэшем, автор — псевдоним буфера («A»), время — в поясе
показа. Каждая строка помечена `synthetic: true` и `origin: "d2_roleplay"`:
это ролевая игра по карточкам с согласия участников, а не переписка жителей.

Буфер живёт не дольше 72 часов, поэтому выгрузка делается сразу после сессии.
Транзакция объявляется `READ ONLY`; оператор и основание обязательны.

    python -m domsignal.tools.d2_export --binding <id> --session S1 \\
        --since 2026-09-24T19:00:00+03:00 --until 2026-09-24T19:40:00+03:00 \\
        --operator <name> --reason <authorization-reference> > export.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import sys
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.core.display_time import display_zone
from domsignal.db.models import ChatMessage
from domsignal.db.session import create_engine, create_session_factory
from domsignal.settings import get_settings

ORIGIN = "d2_roleplay"


def message_hash(binding_id: UUID, mid: str) -> str:
    """Стабильный хэш реплики внутри привязки: `reply_to` совпадает с `mid`."""
    digest = hashlib.sha256(f"{binding_id}:{mid}".encode()).hexdigest()
    return f"h:{digest[:16]}"


async def export(
    session: AsyncSession,
    *,
    binding_id: UUID,
    session_label: str,
    since: datetime,
    until: datetime,
    display_timezone: str,
) -> list[dict[str, Any]]:
    """Реплики привязки за интервал сессии в формате D2, по времени."""
    await session.execute(text("SET TRANSACTION READ ONLY"))
    zone = display_zone(display_timezone)
    rows = await session.execute(
        select(
            ChatMessage.mid,
            ChatMessage.author_ref,
            ChatMessage.text,
            ChatMessage.sent_at,
            ChatMessage.reply_to_mid,
        )
        .where(
            ChatMessage.chat_binding_id == binding_id,
            ChatMessage.sent_at >= since,
            ChatMessage.sent_at <= until,
        )
        .order_by(ChatMessage.sent_at, ChatMessage.id)
    )
    return [
        {
            "session": session_label,
            "mid": message_hash(binding_id, row.mid),
            "sent_at": row.sent_at.astimezone(zone).isoformat(timespec="seconds"),
            "author": row.author_ref,
            "reply_to": message_hash(binding_id, row.reply_to_mid) if row.reply_to_mid else None,
            "text": row.text,
            "synthetic": True,
            "origin": ORIGIN,
        }
        for row in rows
    ]


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with create_session_factory(engine)() as session:
            try:
                lines = await export(
                    session,
                    binding_id=args.binding,
                    session_label=args.session,
                    since=args.since,
                    until=args.until,
                    display_timezone=settings.display_timezone,
                )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    for line in lines:
        print(json.dumps(line, ensure_ascii=False))
    # Итог — в stderr: stdout остаётся чистым JSONL. Без текста и без людей.
    print(
        json.dumps(
            {
                "exported": len(lines),
                "session": args.session,
                "operator": args.operator,
                "reason": args.reason,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 0


def _moment(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise argparse.ArgumentTypeError("time needs an explicit offset, e.g. +03:00")
    return moment


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a D2 session from the chat buffer")
    parser.add_argument("--binding", type=UUID, required=True)
    parser.add_argument("--session", required=True, choices=["S1", "S2"])
    parser.add_argument("--since", type=_moment, required=True)
    parser.add_argument("--until", type=_moment, required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.until <= args.since:
        parser.error("--until must be later than --since")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
