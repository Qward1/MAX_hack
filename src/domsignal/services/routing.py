"""Загрузка справочника ответственности и маршрут по контексту дома из БД.

Справочник читается и проверяется один раз при старте. Невалидный справочник
не роняет сервис: все маршруты становятся `unknown`, ошибка попадает в лог, а
готовность приложения не меняется. Сервис маршрута **никогда не бросает**:
любая ошибка данных или БД превращается в `unknown` без текста в логе.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.routing import (
    DangerKind,
    LocationScope,
    ResponsibilityRoute,
    RouteChannel,
    RouteType,
    SafetyBlock,
    TerritoryPolicy,
)
from domsignal.core.responsibility import ResponsibilityDirectory, build_directory
from domsignal.core.routing import (
    HouseRoutingContext,
    RoutingQuery,
    channel_dto,
    resolve_route,
    route_of_type,
    safety_block,
    unavailable_route,
    visible_to_house,
)
from domsignal.db.repositories.routing import RoutingRepository

logger = logging.getLogger(__name__)

RESPONSIBILITY_FILE = "responsibility.yaml"
SAFETY_FILE = "safety.yaml"
FEDERAL_DIR = "_federal"
RESPONSIBILITY_SCHEMA = "responsibility.schema.json"
SAFETY_SCHEMA = "safety.schema.json"


class DirectoryLoadError(RuntimeError):
    """Файл справочника отсутствует или не проходит схему."""


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise DirectoryLoadError(f"{path.name} is missing")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validator(regions_dir: Path, name: str) -> Draft202012Validator:
    path = regions_dir / name
    if not path.is_file():
        raise DirectoryLoadError(f"{name} is missing")
    return Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )


def validate_document(validator: Draft202012Validator, document: Any, label: str) -> None:
    """Проверить документ слоя по JSON Schema."""
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "<root>"
        raise DirectoryLoadError(f"{label}:{location}: {errors[0].message}")


def load_directory(regions_dir: Path) -> ResponsibilityDirectory:
    """Прочитать и проверить все слои справочника. Бросает `DirectoryLoadError`."""
    responsibility = _validator(regions_dir, RESPONSIBILITY_SCHEMA)
    safety_validator = _validator(regions_dir, SAFETY_SCHEMA)
    federal = _read_yaml(regions_dir / FEDERAL_DIR / RESPONSIBILITY_FILE)
    validate_document(responsibility, federal, f"{FEDERAL_DIR}/{RESPONSIBILITY_FILE}")
    safety = _read_yaml(regions_dir / FEDERAL_DIR / SAFETY_FILE)
    validate_document(safety_validator, safety, f"{FEDERAL_DIR}/{SAFETY_FILE}")
    regions: dict[str, Any] = {}
    for path in sorted(regions_dir.glob(f"*/{RESPONSIBILITY_FILE}")):
        code = path.parent.name
        if code == FEDERAL_DIR:
            continue
        document = _read_yaml(path)
        validate_document(responsibility, document, f"{code}/{RESPONSIBILITY_FILE}")
        regions[code] = document
    try:
        return build_directory(federal=federal, regions=regions, safety=safety)
    except ValueError as exc:
        raise DirectoryLoadError(str(exc)) from exc


def load_directory_or_none(regions_dir: Path) -> ResponsibilityDirectory | None:
    """Загрузить справочник, не роняя приложение при ошибке данных."""
    try:
        return load_directory(regions_dir)
    except (DirectoryLoadError, OSError, yaml.YAMLError) as exc:
        logger.error(
            "responsibility_directory_invalid",
            extra={"error_type": type(exc).__name__, "regions_dir": str(regions_dir)},
        )
        return None


class RoutingService:
    """Маршрут ответственности по контексту дома. Никогда не бросает."""

    def __init__(
        self,
        directory: ResponsibilityDirectory | None,
        *,
        known_subtypes: Collection[str] | None = None,
    ) -> None:
        self.directory = directory
        self._known_subtypes = known_subtypes

    @property
    def available(self) -> bool:
        return self.directory is not None

    @property
    def known_subtypes(self) -> Collection[str]:
        if self._known_subtypes is None:
            from domsignal.ai.taxonomy import load_taxonomy

            self._known_subtypes = load_taxonomy().codes
        return self._known_subtypes

    async def house_context(
        self, session: AsyncSession, house_id: UUID, *, now: datetime | None = None
    ) -> HouseRoutingContext:
        """Контекст дома с сервера; неизвестный дом даёт пустой контекст."""
        moment = now or datetime.now(UTC)
        try:
            repository = RoutingRepository(session)
            house = await repository.house(house_id)
            if house is None:
                return HouseRoutingContext()
            management = await repository.current_management(house_id, moment)
            profile = await repository.profile(house_id)
            policy: TerritoryPolicy = "unknown"
            if profile is not None and profile.territory_policy in {
                "uk",
                "municipal",
                "mixed",
                "unknown",
            }:
                policy = profile.territory_policy  # type: ignore[assignment]
            return HouseRoutingContext(
                is_demo=house.is_demo,
                has_active_connected_uk=management is not None,
                region_code=profile.region_code if profile else None,
                municipality_code=profile.municipality_code if profile else None,
                territory_policy=policy,
            )
        except Exception as exc:  # noqa: BLE001 - контекст не должен ронять путь жителя
            logger.error("routing_house_context_failed", extra={"error_type": type(exc).__name__})
            return HouseRoutingContext()

    def route(
        self,
        *,
        subtype: str,
        location_scope: LocationScope,
        house: HouseRoutingContext,
        danger_kinds: Sequence[DangerKind] = (),
        today: datetime | None = None,
    ) -> ResponsibilityRoute:
        """Определить маршрут. Ошибка справочника превращается в `unknown`."""
        if self.directory is None:
            return unavailable_route()
        try:
            return resolve_route(
                RoutingQuery(
                    subtype=subtype,
                    location_scope=location_scope,
                    danger_kinds=tuple(danger_kinds),
                    house=house,
                ),
                self.directory,
                known_subtypes=self.known_subtypes,
                today=(today or datetime.now(UTC)).date(),
            )
        except Exception as exc:  # noqa: BLE001 - маршрут не должен ронять путь жителя
            logger.error("routing_resolve_failed", extra={"error_type": type(exc).__name__})
            return unavailable_route()

    def route_of_type(
        self,
        route_type: RouteType,
        *,
        subtype: str,
        location_scope: LocationScope,
        house: HouseRoutingContext,
        danger_kinds: Sequence[DangerKind] = (),
        today: datetime | None = None,
    ) -> ResponsibilityRoute:
        """Маршрут выбранного оператором типа; справочник подставляет канал."""
        if self.directory is None:
            return unavailable_route()
        try:
            return route_of_type(
                route_type,
                RoutingQuery(
                    subtype=subtype,
                    location_scope=location_scope,
                    danger_kinds=tuple(danger_kinds),
                    house=house,
                ),
                self.directory,
                known_subtypes=self.known_subtypes,
                today=(today or datetime.now(UTC)).date(),
            )
        except Exception as exc:  # noqa: BLE001 - маршрут не должен ронять очередь
            logger.error("routing_resolve_failed", extra={"error_type": type(exc).__name__})
            return unavailable_route()

    def safety(
        self, house: HouseRoutingContext, danger_kinds: Sequence[DangerKind]
    ) -> SafetyBlock | None:
        """Проверенная памятка безопасности; без справочника — ничего."""
        if self.directory is None:
            return None
        try:
            return safety_block(self.directory, danger_kinds, house)
        except Exception as exc:  # noqa: BLE001 - памятка не должна ронять путь жителя
            logger.error("routing_safety_failed", extra={"error_type": type(exc).__name__})
            return None

    def directory_entry(
        self,
        house: HouseRoutingContext,
        *,
        organization_id: str | None = None,
        channel_id: str | None = None,
    ) -> tuple[str | None, RouteChannel | None]:
        """Имя организации и канал по идентификаторам сохранённого исхода.

        Черновик обращения собирается из уже принятого решения, поэтому ему
        нужен не пересчёт маршрута, а та же запись справочника. Непроверенная
        запись по-прежнему не называется: видимость решает тот же фильтр.
        """
        if self.directory is None:
            return None, None
        try:
            effective = self.directory.effective(house.region_code, house.municipality_code)
            organization = None
            if organization_id is not None:
                found = effective.organizations.get(organization_id)
                if found is not None and visible_to_house(
                    found.verification, is_demo=house.is_demo
                ):
                    organization = found.name
            channel = None
            if channel_id is not None:
                entry = effective.channels.get(channel_id)
                if (
                    entry is not None
                    and entry.available_in(house.region_code)
                    and visible_to_house(entry.verification, is_demo=house.is_demo)
                ):
                    channel = channel_dto(entry, today=datetime.now(UTC).date())
            return organization, channel
        except Exception as exc:  # noqa: BLE001 - справочник не должен ронять черновик
            logger.error("routing_directory_entry_failed", extra={"error_type": type(exc).__name__})
            return None, None

    async def route_for_house(
        self,
        session: AsyncSession,
        *,
        house_id: UUID,
        subtype: str,
        location_scope: LocationScope,
        danger_kinds: Sequence[DangerKind] = (),
        now: datetime | None = None,
    ) -> tuple[ResponsibilityRoute, HouseRoutingContext]:
        """Маршрут вместе с использованным контекстом дома."""
        house = await self.house_context(session, house_id, now=now)
        return (
            self.route(
                subtype=subtype,
                location_scope=location_scope,
                house=house,
                danger_kinds=danger_kinds,
                today=now,
            ),
            house,
        )
