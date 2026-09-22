"""Выключатель пассивного чтения подключённого чата — без HTTP.

Действие выполняет сотрудник с правом `chat.connect` в текущем периоде
управления — то же право, что и подключение чата. Включение ставит сообщение
о чтении чата (один раз на привязку и её версию); выключение сразу прекращает
приём реплик и оставляет уже собранные сигналы. HTTP-граница появится вместе
с экранами оператора (срез P5).

    python -m domsignal.tools.passive_capture --binding <id> --actor <user id> --enable
    python -m domsignal.tools.passive_capture --binding <id> --actor <user id> --disable
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from domsignal.bootstrap import build_container
from domsignal.services.errors import ServiceError
from domsignal.settings import get_settings
from domsignal.tools import print_json


async def run(binding_id: UUID, actor_id: UUID, enabled: bool) -> int:
    container = build_container(get_settings())
    try:
        async with container.session_factory() as session, session.begin():
            result = await container.passive.set_capture(
                session, binding_id=binding_id, actor_id=actor_id, enabled=enabled
            )
        print_json(
            {
                "binding_id": str(result.binding_id),
                "binding_version": result.binding_version,
                "passive_capture_enabled": result.passive_capture_enabled,
                "reading_notice_queued": result.notice_queued,
            }
        )
        return 0
    except ServiceError as exc:
        print_json({"error": getattr(exc, "code", "service_error")})
        return 2
    finally:
        await container.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Turn passive chat reading on or off")
    parser.add_argument("--binding", type=UUID, required=True)
    parser.add_argument("--actor", type=UUID, required=True)
    switch = parser.add_mutually_exclusive_group(required=True)
    switch.add_argument("--enable", action="store_true")
    switch.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.binding, args.actor, bool(args.enable))))


if __name__ == "__main__":
    main()
