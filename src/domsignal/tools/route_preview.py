"""Печать ActionCard для дома, подтипа и территории — без HTTP и без модели.

Инструмент владельца и подготовки демонстрации: показывает ровно то, что
увидит житель или оператор, включая скрытые непроверенные каналы как счётчик.

`--compare-regions` печатает колонку на каждый пакет региона из `regions/`
(D4; в D2 — только Казань и Москва) для одних и тех же подтипов: один код
роутера, разные пакеты данных, разные каналы и основания.
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
    ResponsibilityRoute,
)
from domsignal.core.routing import HouseRoutingContext
from domsignal.services.routing import RoutingService
from domsignal.settings import get_settings
from domsignal.tools import print_json

#: Десять подтипов сравнения: подтип, территория и опасность.
REGION_COMPARISON: tuple[tuple[str, LocationScope, tuple[DangerKind, ...]], ...] = (
    ("street_lighting.failure", "municipal_territory", ()),
    ("road.damage", "municipal_territory", ()),
    ("snow.street", "municipal_territory", ()),
    ("landscaping.public", "municipal_territory", ()),
    ("waste.removal_regional", "unknown", ()),
    ("elevator.stopped", "house_common", ()),
    ("water.hot_outage", "external_network", ()),
    ("gas.smell", "house_common", ("gas",)),
    ("playground.damaged", "house_territory", ()),
    ("other.unspecified", "unknown", ()),
)


def regions(routing: RoutingService) -> list[tuple[str, str, str | None]]:
    """Все загруженные пакеты регионов: (подпись, регион, первый муниципалитет)."""
    directory = routing.directory
    if directory is None:
        return []
    result: list[tuple[str, str, str | None]] = []
    for code, layer in sorted(directory.regions.items()):
        sections = sorted(directory.municipalities.get(code, {}).items())
        municipality = sections[0] if sections else None
        place = (municipality[1].name if municipality else None) or layer.name or code
        result.append((f"{place} ({code})", code, municipality[0] if municipality else None))
    return result


def region_context(region: str, municipality: str | None) -> HouseRoutingContext:
    """Дом с подключённой УК и смешанной территорией в указанном регионе."""
    return HouseRoutingContext(
        has_active_connected_uk=True,
        region_code=region,
        municipality_code=municipality,
        territory_policy="mixed",
    )


def compare_regions(
    routing: RoutingService,
    rows: tuple[tuple[str, LocationScope, tuple[DangerKind, ...]], ...] = REGION_COMPARISON,
) -> list[tuple[str, str, dict[str, ResponsibilityRoute]]]:
    """Маршрут каждого подтипа в каждом пакете региона: `{регион: маршрут}`."""
    packs = regions(routing)
    return [
        (
            subtype,
            scope,
            {
                region: routing.route(
                    subtype=subtype,
                    location_scope=scope,
                    danger_kinds=danger,
                    house=region_context(region, municipality),
                )
                for _, region, municipality in packs
            },
        )
        for subtype, scope, danger in rows
    ]


def describe(route: ResponsibilityRoute) -> str:
    channels = ", ".join(channel.label for channel in route.channels) or "канала нет"
    basis = route.basis.rule_id if route.basis and route.basis.rule_id else route.match
    choice = " · выбор оператора" if route.requires_operator_choice else ""
    return f"{route.route_type}: {channels} [{basis}]{choice}"


def print_comparison(routing: RoutingService) -> None:
    packs = regions(routing)
    header = ["Подтип", "Территория", *(label for label, _, _ in packs)]
    print(" | ".join(header))
    print(" | ".join("---" for _ in header))
    for subtype, scope, routes in compare_regions(routing):
        print(" | ".join([subtype, scope, *(describe(routes[code]) for _, code, _ in packs)]))


async def run(args: argparse.Namespace) -> None:
    container = build_container(get_settings())
    try:
        if getattr(args, "compare_regions", False):
            print_comparison(container.routing)
            return
        if args.house_id is None or args.subtype is None:
            raise SystemExit("--house-id и --subtype обязательны без --compare-regions")
        danger = tuple(cast(DangerKind, kind) for kind in args.danger)
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
    parser.add_argument("--house-id", dest="house_id", type=UUID, default=None)
    parser.add_argument("--subtype", default=None)
    parser.add_argument("--scope", choices=list(LOCATION_SCOPES), default="unknown")
    parser.add_argument("--danger", action="append", choices=list(DANGER_KINDS), default=[])
    parser.add_argument("--audience", choices=["resident", "operator"], default="resident")
    parser.add_argument("--source", choices=["chat", "explicit"], default="explicit")
    parser.add_argument("--existing-ticket", dest="existing_ticket", default=None)
    parser.add_argument(
        "--compare-regions",
        dest="compare_regions",
        action="store_true",
        help="Колонка на каждый пакет региона из regions/ для десяти подтипов",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
