"""Часовой пояс дома и УК — из пакета региона (D4, В-2).

Пояс дома — поле `timezone` слоя его региона (профиль дома → регион). Без
профиля или с регионом, которого нет в справочнике, — `Europe/Moscow`. Пояс
УК — пояс большинства её текущих домов. Хранение и сравнение времени
остаются в UTC; пояс нужен только для тихих часов, часа сводки, суток
дашбордов и подписи времени в сообщениях сотрудникам.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.core.display_time import DEFAULT_DISPLAY_TIMEZONE
from domsignal.core.responsibility import ResponsibilityDirectory
from domsignal.db.models import HouseManagement, HouseRoutingProfile
from domsignal.services.onboarding import current_management


def majority(zones: Iterable[str], default: str = DEFAULT_DISPLAY_TIMEZONE) -> str:
    """Пояс большинства; при равенстве — пояс по умолчанию, иначе первый по имени."""
    counts = Counter(zones)
    if not counts:
        return default
    best = max(counts.values())
    top = sorted(zone for zone, count in counts.items() if count == best)
    return default if default in top else top[0]


class HouseZones:
    def __init__(
        self,
        directory: ResponsibilityDirectory | None,
        default: str = DEFAULT_DISPLAY_TIMEZONE,
    ) -> None:
        self.directory = directory
        self.default = default

    def of_region(self, region_code: str | None) -> str:
        zone = self.directory.timezone_for(region_code) if self.directory else None
        return zone or self.default

    async def of_house(self, session: AsyncSession, house_id: UUID | None) -> str:
        if house_id is None:
            return self.default
        region = await session.scalar(
            select(HouseRoutingProfile.region_code).where(HouseRoutingProfile.house_id == house_id)
        )
        return self.of_region(region)

    async def of_houses(self, session: AsyncSession, house_ids: Iterable[UUID]) -> str:
        ids = list(house_ids)
        if not ids:
            return self.default
        rows = await session.execute(
            select(HouseRoutingProfile.house_id, HouseRoutingProfile.region_code).where(
                HouseRoutingProfile.house_id.in_(ids)
            )
        )
        regions = {house: region for house, region in rows.tuples()}
        return majority((self.of_region(regions.get(house)) for house in ids), self.default)

    async def of_company(self, session: AsyncSession, company_id: UUID) -> str:
        houses = await session.scalars(
            select(HouseManagement.house_id).where(
                HouseManagement.tenant_id == company_id, *current_management()
            )
        )
        return await self.of_houses(session, houses)


__all__ = ["HouseZones", "majority"]
