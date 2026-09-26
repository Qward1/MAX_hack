"""Регион дома: одна запись профиля для CLI и платформы (D4, В-1).

Профиль маршрутизации — регион, муниципалитет и территория — данные дома, а не
вывод модели. Платформа выбирает их при одобрении дома или действием «Задать
регион» только из загруженного справочника (`GET /platform/region-packs`);
CLI `house_routing_profile` пишет через ту же функцию. Каждая запись оставляет
событие аудита `operator.house_routing_profile` с прежним и новым профилем.
Транзакцией владеет вызывающий.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.onboarding import RegionMunicipality, RegionPackView
from domsignal.core.responsibility import ResponsibilityDirectory
from domsignal.db.models import HouseRoutingProfile, InboxReceipt
from domsignal.db.repositories.routing import RoutingRepository
from domsignal.services.errors import FieldValidationError

PROFILE_AUDIT_PREFIX = "operator:house-routing-profile:v1"
PROFILE_AUDIT_TYPE = "operator.house_routing_profile"
TERRITORIES = ("uk", "municipal", "mixed", "unknown")

REGION_REQUIRED = (
    "Выберите регион дома из справочника. Без региона дом видит только федеральные "
    "каналы, и жителю могут предложить сервис, недоступный в его регионе."
)
REGION_UNKNOWN = "Такого региона нет в загруженном справочнике. Выберите регион из списка."
MUNICIPALITY_UNKNOWN = "Такого муниципалитета нет в пакете региона. Выберите из списка."


def profile_view(profile: HouseRoutingProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "region_code": profile.region_code,
        "municipality_code": profile.municipality_code,
        "territory_policy": profile.territory_policy,
    }


def region_packs(directory: ResponsibilityDirectory | None) -> list[RegionPackView]:
    """Регионы загруженного справочника с муниципалитетами — варианты выбора."""
    if directory is None:
        return []
    return [
        RegionPackView(
            region_code=code,
            name=layer.name or code,
            timezone=directory.timezone_for(code) or "Europe/Moscow",
            version=layer.version,
            municipalities=[
                RegionMunicipality(code=municipality, name=section.name or municipality)
                for municipality, section in sorted(directory.municipalities.get(code, {}).items())
            ],
        )
        for code, layer in sorted(directory.regions.items())
    ]


def check_choice(
    directory: ResponsibilityDirectory | None,
    region: str | None,
    municipality: str | None,
) -> None:
    """Регион обязателен и есть в справочнике; муниципалитет — из его пакета."""
    if not region:
        raise FieldValidationError(REGION_REQUIRED, field="region_code", code="required")
    if directory is None or region not in directory.regions:
        raise FieldValidationError(REGION_UNKNOWN, field="region_code")
    if municipality and municipality not in directory.municipalities.get(region, {}):
        raise FieldValidationError(MUNICIPALITY_UNKNOWN, field="municipality_code")


async def write_profile(
    session: AsyncSession,
    *,
    house_id: UUID,
    region: str | None,
    municipality: str | None,
    territory: str,
    actor: UUID | None,
    operator: str | None,
    reason: str | None,
) -> dict[str, Any]:
    """Записать профиль дома и событие аудита. Неизвестный дом — `ValueError`."""
    repository = RoutingRepository(session)
    if await repository.house(house_id) is None:
        raise ValueError("House was not found")
    previous = profile_view(await repository.profile(house_id))
    profile = await repository.upsert_profile(
        house_id=house_id,
        region_code=region,
        municipality_code=municipality,
        territory_policy=territory,
        updated_by=actor,
    )
    now = datetime.now(UTC)
    updated_by = str(profile.updated_by) if profile.updated_by else None
    session.add(
        InboxReceipt(
            event_id=f"{PROFILE_AUDIT_PREFIX}:{house_id}:{now:%Y%m%dT%H%M%S%fZ}",
            event_type=PROFILE_AUDIT_TYPE,
            payload={
                "house_id": str(house_id),
                "previous": previous,
                "profile": profile_view(profile),
                "updated_by": updated_by,
                "operator": operator,
                "reason": reason,
                "at": now.isoformat(),
            },
        )
    )
    await session.flush()
    return {"house_id": str(house_id), **(profile_view(profile) or {}), "updated_by": updated_by}


__all__ = [
    "PROFILE_AUDIT_PREFIX",
    "PROFILE_AUDIT_TYPE",
    "TERRITORIES",
    "check_choice",
    "profile_view",
    "region_packs",
    "write_profile",
]
