"""Печать ActionCard для дома, подтипа и территории — без HTTP и без модели.

Инструмент владельца и подготовки демонстрации: показывает ровно то, что
увидит житель или оператор, включая скрытые непроверенные каналы как счётчик.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import cast
from uuid import UUID

from domsignal.bootstrap import build_container
from domsignal.contracts.routing import (
    DANGER_KINDS,
    LOCATION_SCOPES,
    Audience,
    CardSource,
    DangerKind,
    LocationScope,
)
from domsignal.settings import get_settings
from domsignal.tools import print_json


async def run(args: argparse.Namespace) -> None:
    container = build_container(get_settings())
    danger = tuple(cast(DangerKind, kind) for kind in args.danger)
    try:
        async with container.session_factory() as session:
            route, house = await container.routing.route_for_house(
                session,
                house_id=args.house_id,
                subtype=args.subtype,
                location_scope=cast(LocationScope, args.scope),
                danger_kinds=danger,
            )
        card = container.action_cards.build(
            route,
            house,
            audience=cast(Audience, args.audience),
            source=cast(CardSource, args.source),
            danger_kinds=danger,
            existing_ticket_ref=args.existing_ticket,
        )
        print_json(card.model_dump(mode="json"))
    finally:
        await container.engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the ActionCard for a house and subtype")
    parser.add_argument("--house-id", dest="house_id", type=UUID, required=True)
    parser.add_argument("--subtype", required=True)
    parser.add_argument("--scope", choices=list(LOCATION_SCOPES), default="unknown")
    parser.add_argument("--danger", action="append", choices=list(DANGER_KINDS), default=[])
    parser.add_argument("--audience", choices=["resident", "operator"], default="resident")
    parser.add_argument("--source", choices=["chat", "explicit"], default="explicit")
    parser.add_argument("--existing-ticket", dest="existing_ticket", default=None)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
