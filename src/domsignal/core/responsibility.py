"""Справочник ответственности: модель данных, слои и видимость записей.

Чистая логика без I/O: на вход приходят уже разобранные документы слоёв
(`regions/_federal/responsibility.yaml`, `regions/<REGION>/responsibility.yaml`
и `regions/_federal/safety.yaml`), на выход — объединённый справочник.

Слои: федеральный → регион → муниципалитет. Нижний слой уточняет верхний:
запись с тем же `id` переопределяет, новая — добавляется.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

from domsignal.contracts.routing import (
    ChannelType,
    OrganizationKind,
    RouteType,
    VerificationStatus,
)

#: Через сколько дней проверенная запись показывается с пометкой «требует проверки».
STALE_AFTER_DAYS = 180

FEDERAL_LAYER_ID = "_federal"

_VERIFICATION_STATUSES = ("verified", "needs_verification", "demo")
_CHANNEL_TYPES = ("official_web", "phone", "max_bot", "email", "in_person")
_ORGANIZATION_KINDS = (
    "municipality",
    "resource_supplier",
    "emergency_service",
    "regional_operator",
    "other_authority",
)
_RULE_ROUTE_TYPES = (
    "municipality",
    "resource_supplier",
    "emergency_service",
    "regional_operator",
    "other_authority",
)
_DANGER_KINDS = (
    "gas",
    "smoke_fire",
    "electric",
    "person_trapped",
    "flooding",
    "structural",
    "other_hazard",
)


class DirectoryError(ValueError):
    """Справочник отсутствует или не проходит разбор."""


# --------------------------------------------------------------------- разбор


def _mapping(raw: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise DirectoryError(f"{where}: expected a mapping")
    return cast(Mapping[str, Any], raw)


def _sequence(raw: Any, where: str) -> Sequence[Any]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise DirectoryError(f"{where}: expected a list")
    return cast(Sequence[Any], raw)


def _text(entry: Mapping[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise DirectoryError(f"{where}: {key} must be a non-empty string")
    return value


def _optional_text(entry: Mapping[str, Any], key: str, where: str) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise DirectoryError(f"{where}: {key} must be a non-empty string or null")
    return value


def _flag(entry: Mapping[str, Any], key: str, where: str, *, default: bool = False) -> bool:
    value = entry.get(key, default)
    if not isinstance(value, bool):
        raise DirectoryError(f"{where}: {key} must be a boolean")
    return value


def _codes(entry: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    values = _sequence(entry.get(key), f"{where}.{key}")
    for value in values:
        if not isinstance(value, str) or not value:
            raise DirectoryError(f"{where}.{key}: expected non-empty strings")
    return tuple(cast(Sequence[str], values))


def _day(entry: Mapping[str, Any], key: str, where: str) -> date | None:
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise DirectoryError(f"{where}: {key} must be an ISO date") from exc
    raise DirectoryError(f"{where}: {key} must be an ISO date or null")


def _literal(value: str, allowed: tuple[str, ...], where: str, key: str) -> str:
    if value not in allowed:
        raise DirectoryError(f"{where}: {key}={value!r} is not one of {allowed}")
    return value


# --------------------------------------------------------------------- модель


@dataclass(frozen=True)
class Verification:
    """Статус проверки записи и её источник."""

    status: VerificationStatus
    verified_at: date | None = None
    verified_by: str | None = None
    source_title: str | None = None
    source_url: str | None = None

    def stale_on(self, today: date) -> bool:
        """Проверенная запись старше порога актуальности."""
        return self.verified_at is not None and (today - self.verified_at).days > STALE_AFTER_DAYS

    @classmethod
    def parse(cls, raw: Any, where: str) -> Verification:
        entry = _mapping(raw, where)
        status = _literal(_text(entry, "status", where), _VERIFICATION_STATUSES, where, "status")
        verified_at = _day(entry, "verified_at", where)
        source_title = _optional_text(entry, "source_title", where)
        if status == "verified" and (verified_at is None or source_title is None):
            raise DirectoryError(f"{where}: verified record needs verified_at and a source")
        return cls(
            status=cast(VerificationStatus, status),
            verified_at=verified_at,
            verified_by=_optional_text(entry, "verified_by", where),
            source_title=source_title,
            source_url=_optional_text(entry, "source_url", where),
        )


@dataclass(frozen=True)
class Fact:
    text: str
    source_title: str
    source_url: str | None = None

    @classmethod
    def parse(cls, raw: Any, where: str) -> Fact:
        entry = _mapping(raw, where)
        return cls(
            text=_text(entry, "text", where),
            source_title=_text(entry, "source_title", where),
            source_url=_optional_text(entry, "source_url", where),
        )


@dataclass(frozen=True)
class Basis:
    text: str
    source_title: str
    source_url: str | None = None

    @classmethod
    def parse(cls, raw: Any, where: str) -> Basis:
        entry = _mapping(raw, where)
        return cls(
            text=_text(entry, "text", where),
            source_title=_text(entry, "source_title", where),
            source_url=_optional_text(entry, "source_url", where),
        )


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    kind: OrganizationKind
    region: str | None
    municipality: str | None
    verification: Verification

    @classmethod
    def parse(cls, raw: Any, where: str) -> Organization:
        entry = _mapping(raw, where)
        identifier = _text(entry, "id", where)
        return cls(
            id=identifier,
            name=_text(entry, "name", where),
            kind=cast(
                OrganizationKind,
                _literal(_text(entry, "kind", where), _ORGANIZATION_KINDS, where, "kind"),
            ),
            region=_optional_text(entry, "region", where),
            municipality=_optional_text(entry, "municipality", where),
            verification=Verification.parse(entry.get("verification"), f"{where}.verification"),
        )


@dataclass(frozen=True)
class Channel:
    id: str
    organization_id: str | None
    channel_type: ChannelType
    label: str
    url: str | None
    phone: str | None
    entry_hint: str | None
    routes_to_competent_authority: bool
    facts: tuple[Fact, ...]
    unavailable_regions: tuple[str, ...]
    verification: Verification

    def available_in(self, region_code: str | None) -> bool:
        """Канал не исключён для региона дома."""
        return region_code is None or region_code not in self.unavailable_regions

    @classmethod
    def parse(cls, raw: Any, where: str) -> Channel:
        entry = _mapping(raw, where)
        identifier = _text(entry, "id", where)
        facts = tuple(
            Fact.parse(item, f"{where}.facts[{index}]")
            for index, item in enumerate(_sequence(entry.get("facts"), f"{where}.facts"))
        )
        return cls(
            id=identifier,
            organization_id=_optional_text(entry, "organization_id", where),
            channel_type=cast(
                ChannelType,
                _literal(
                    _text(entry, "channel_type", where), _CHANNEL_TYPES, where, "channel_type"
                ),
            ),
            label=_text(entry, "label", where),
            url=_optional_text(entry, "url", where),
            phone=_optional_text(entry, "phone", where),
            entry_hint=_optional_text(entry, "entry_hint", where),
            routes_to_competent_authority=_flag(entry, "routes_to_competent_authority", where),
            facts=facts,
            unavailable_regions=_codes(entry, "unavailable_regions", where),
            verification=Verification.parse(entry.get("verification"), f"{where}.verification"),
        )


@dataclass(frozen=True)
class Rule:
    id: str
    priority: int
    subtypes: tuple[str, ...]
    location_scopes: tuple[str, ...]
    route_type: RouteType
    organization_id: str | None
    channel_ids: tuple[str, ...]
    can_prepare_appeal: bool
    basis: Basis
    verification: Verification
    layer_id: str = FEDERAL_LAYER_ID
    layer_depth: int = 0
    #: Виды опасности, по которым правило совпадает и без подтипа. Допустимы
    #: только у правил экстренной службы: опасность ортогональна маршруту.
    danger_kinds: tuple[str, ...] = ()

    def matches(
        self, subtype: str, location_scope: str, danger_kinds: Sequence[str] = ()
    ) -> bool:
        """Совпадение по подтипу или по пересечению видов опасности.

        `location_scopes` остаётся дополнительным фильтром; пустой список
        значений в `match` означает «любое значение».
        """
        by_subtype = subtype in self.subtypes
        by_danger = any(kind in self.danger_kinds for kind in danger_kinds)
        if not (by_subtype or by_danger):
            return False
        return not self.location_scopes or location_scope in self.location_scopes

    @classmethod
    def parse(cls, raw: Any, where: str, *, layer_id: str, layer_depth: int) -> Rule:
        entry = _mapping(raw, where)
        identifier = _text(entry, "id", where)
        priority = entry.get("priority")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise DirectoryError(f"{where}: priority must be an integer")
        match = _mapping(entry.get("match"), f"{where}.match")
        subtypes = _codes(match, "subtypes", f"{where}.match")
        danger_kinds = _codes(match, "danger_kinds", f"{where}.match")
        if not subtypes and not danger_kinds:
            raise DirectoryError(f"{where}.match: subtypes or danger_kinds must not be empty")
        route_type = _literal(
            _text(entry, "route_type", where), _RULE_ROUTE_TYPES, where, "route_type"
        )
        if danger_kinds and route_type != "emergency_service":
            raise DirectoryError(
                f"{where}.match: danger_kinds are allowed only for emergency_service rules"
            )
        for kind in danger_kinds:
            _literal(kind, _DANGER_KINDS, f"{where}.match", "danger_kinds")
        return cls(
            id=identifier,
            priority=priority,
            subtypes=subtypes,
            location_scopes=_codes(match, "location_scopes", f"{where}.match"),
            danger_kinds=danger_kinds,
            route_type=cast(RouteType, route_type),
            organization_id=_optional_text(entry, "organization_id", where),
            channel_ids=_codes(entry, "channel_ids", where),
            can_prepare_appeal=_flag(entry, "can_prepare_appeal", where),
            basis=Basis.parse(entry.get("basis"), f"{where}.basis"),
            verification=Verification.parse(entry.get("verification"), f"{where}.verification"),
            layer_id=layer_id,
            layer_depth=layer_depth,
        )


@dataclass(frozen=True)
class UkDefault:
    """Подтипы общего имущества, для которых первая линия — управляющая компания."""

    subtypes: tuple[str, ...]
    resource_supplier_alternatives: tuple[str, ...]
    basis: Basis
    verification: Verification
    #: Подтипы, которые житель видит в квартире, но система общедомовая.
    apartment_subtypes: tuple[str, ...] = ()
    #: Каналы заявки в УК, которые житель использует сам (D4: «Госуслуги Дом»).
    channel_ids: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw: Any, where: str) -> UkDefault:
        entry = _mapping(raw, where)
        subtypes = _codes(entry, "subtypes", where)
        if not subtypes:
            raise DirectoryError(f"{where}: subtypes must not be empty")
        return cls(
            subtypes=subtypes,
            resource_supplier_alternatives=_codes(
                entry, "resource_supplier_alternatives", where
            ),
            basis=Basis.parse(entry.get("basis"), f"{where}.basis"),
            verification=Verification.parse(entry.get("verification"), f"{where}.verification"),
            apartment_subtypes=_codes(entry, "apartment_subtypes", where),
            channel_ids=_codes(entry, "channel_ids", where),
        )


@dataclass(frozen=True)
class SafetyStepData:
    text: str
    source_title: str
    source_url: str | None = None


@dataclass(frozen=True)
class SafetyBlockData:
    id: str
    danger_kinds: tuple[str, ...]
    title: str
    lines: tuple[str, ...]
    phone: str | None
    steps: tuple[SafetyStepData, ...]
    verification: Verification

    def applies_to(self, danger_kinds: Sequence[str]) -> bool:
        """Пустой `danger_kinds` — блок подходит любой опасности."""
        if not self.danger_kinds:
            return True
        return any(kind in self.danger_kinds for kind in danger_kinds)


@dataclass(frozen=True)
class ReferenceLink:
    """Официальная страница тарифов или программы капремонта региона (D4)."""

    id: str
    kind: str
    label: str
    url: str
    verification: Verification

    @classmethod
    def parse(cls, raw: Any, where: str) -> ReferenceLink:
        entry = _mapping(raw, where)
        return cls(
            id=_text(entry, "id", where),
            kind=_literal(
                _text(entry, "kind", where), ("tariffs", "capital_repair"), where, "kind"
            ),
            label=_text(entry, "label", where),
            url=_text(entry, "url", where),
            verification=Verification.parse(entry.get("verification"), f"{where}.verification"),
        )


@dataclass(frozen=True)
class DirectoryLayer:
    """Один слой справочника после разбора документа."""

    layer_id: str
    depth: int
    version: str
    updated_at: date | None
    organizations: tuple[Organization, ...] = ()
    channels: tuple[Channel, ...] = ()
    rules: tuple[Rule, ...] = ()
    uk_default: UkDefault | None = None
    #: Только у слоя региона (D4): название, пояс IANA и справочные ссылки.
    name: str | None = None
    timezone: str | None = None
    reference_links: tuple[ReferenceLink, ...] = ()


@dataclass(frozen=True)
class EffectiveDirectory:
    """Справочник, собранный для конкретных региона и муниципалитета."""

    version: str
    updated_at: date | None
    organizations: Mapping[str, Organization] = field(default_factory=dict)
    channels: Mapping[str, Channel] = field(default_factory=dict)
    rules: tuple[Rule, ...] = ()
    uk_default: UkDefault | None = None
    safety: tuple[SafetyBlockData, ...] = ()

    def safety_for(self, danger_kinds: Sequence[str]) -> SafetyBlockData | None:
        """Первый проверенный блок безопасности, подходящий опасности."""
        for block in self.safety:
            if block.verification.status == "verified" and block.applies_to(danger_kinds):
                return block
        return None


def parse_layer(document: Any, *, depth: int) -> DirectoryLayer:
    """Разобрать документ слоя справочника (муниципалитеты остаются внутри)."""
    entry = _mapping(document, "responsibility layer")
    layer_id = _text(entry, "layer_id", "responsibility layer")
    where = f"{layer_id}"
    organizations = tuple(
        Organization.parse(item, f"{where}.organizations[{index}]")
        for index, item in enumerate(
            _sequence(entry.get("organizations"), f"{where}.organizations")
        )
    )
    channels = tuple(
        Channel.parse(item, f"{where}.channels[{index}]")
        for index, item in enumerate(_sequence(entry.get("channels"), f"{where}.channels"))
    )
    rules = tuple(
        Rule.parse(item, f"{where}.rules[{index}]", layer_id=layer_id, layer_depth=depth)
        for index, item in enumerate(_sequence(entry.get("rules"), f"{where}.rules"))
    )
    raw_default = entry.get("uk_default")
    return DirectoryLayer(
        layer_id=layer_id,
        depth=depth,
        version=_text(entry, "version", where),
        updated_at=_day(entry, "updated_at", where),
        organizations=organizations,
        channels=channels,
        rules=rules,
        uk_default=UkDefault.parse(raw_default, f"{where}.uk_default") if raw_default else None,
        name=_optional_text(entry, "name", where),
        timezone=_optional_text(entry, "timezone", where),
        reference_links=tuple(
            ReferenceLink.parse(item, f"{where}.reference_links[{index}]")
            for index, item in enumerate(
                _sequence(entry.get("reference_links"), f"{where}.reference_links")
            )
        ),
    )


def parse_municipalities(document: Any, *, depth: int) -> dict[str, DirectoryLayer]:
    """Муниципальные секции регионального документа как отдельные слои."""
    entry = _mapping(document, "responsibility layer")
    region_id = _text(entry, "layer_id", "responsibility layer")
    version = _text(entry, "version", region_id)
    updated_at = _day(entry, "updated_at", region_id)
    result: dict[str, DirectoryLayer] = {}
    for index, item in enumerate(
        _sequence(entry.get("municipalities"), f"{region_id}.municipalities")
    ):
        where = f"{region_id}.municipalities[{index}]"
        section = _mapping(item, where)
        code = _text(section, "code", where)
        layer_id = f"{region_id}/{code}"
        result[code] = DirectoryLayer(
            layer_id=layer_id,
            depth=depth,
            version=version,
            updated_at=updated_at,
            name=_text(section, "name", where),
            organizations=tuple(
                Organization.parse(raw, f"{where}.organizations[{position}]")
                for position, raw in enumerate(
                    _sequence(section.get("organizations"), f"{where}.organizations")
                )
            ),
            channels=tuple(
                Channel.parse(raw, f"{where}.channels[{position}]")
                for position, raw in enumerate(
                    _sequence(section.get("channels"), f"{where}.channels")
                )
            ),
            rules=tuple(
                Rule.parse(
                    raw,
                    f"{where}.rules[{position}]",
                    layer_id=layer_id,
                    layer_depth=depth,
                )
                for position, raw in enumerate(_sequence(section.get("rules"), f"{where}.rules"))
            ),
        )
    return result


def parse_safety(document: Any) -> tuple[SafetyBlockData, ...]:
    """Разобрать блоки безопасности."""
    entry = _mapping(document, "safety")
    layer_id = _text(entry, "layer_id", "safety")
    blocks: list[SafetyBlockData] = []
    for index, item in enumerate(_sequence(entry.get("blocks"), f"{layer_id}.blocks")):
        where = f"{layer_id}.blocks[{index}]"
        block = _mapping(item, where)
        steps: list[SafetyStepData] = []
        for position, raw in enumerate(_sequence(block.get("steps"), f"{where}.steps")):
            step = _mapping(raw, f"{where}.steps[{position}]")
            steps.append(
                SafetyStepData(
                    text=_text(step, "text", f"{where}.steps[{position}]"),
                    source_title=_text(step, "source_title", f"{where}.steps[{position}]"),
                    source_url=_optional_text(step, "source_url", f"{where}.steps[{position}]"),
                )
            )
        lines = _codes(block, "lines", where)
        blocks.append(
            SafetyBlockData(
                id=_text(block, "id", where),
                danger_kinds=_codes(block, "danger_kinds", where),
                title=_text(block, "title", where),
                lines=lines,
                phone=_optional_text(block, "phone", where),
                steps=tuple(steps),
                verification=Verification.parse(
                    block.get("verification"), f"{where}.verification"
                ),
            )
        )
    return tuple(blocks)


class ResponsibilityDirectory:
    """Слои справочника и их объединение под конкретный дом."""

    def __init__(
        self,
        *,
        federal: DirectoryLayer,
        regions: Mapping[str, DirectoryLayer] | None = None,
        municipalities: Mapping[str, Mapping[str, DirectoryLayer]] | None = None,
        safety: Sequence[SafetyBlockData] = (),
    ) -> None:
        self.federal = federal
        self.regions = dict(regions or {})
        self.municipalities = {
            region: dict(sections) for region, sections in (municipalities or {}).items()
        }
        self.safety = tuple(safety)
        self._cache: dict[tuple[str | None, str | None], EffectiveDirectory] = {}

    def timezone_for(self, region_code: str | None) -> str | None:
        """Пояс IANA из слоя региона; неизвестный регион — `None`."""
        layer = self.regions.get(region_code or "")
        return layer.timezone if layer is not None else None

    def versions(self) -> dict[str, str]:
        """Версии загруженных слоёв: `{"_federal": "2", "RU-MOW": "1", …}`."""
        return {
            self.federal.layer_id: self.federal.version,
            **{code: layer.version for code, layer in sorted(self.regions.items())},
        }

    def layers_for(self, region_code: str | None, municipality_code: str | None) -> list[
        DirectoryLayer
    ]:
        layers = [self.federal]
        if region_code and region_code in self.regions:
            layers.append(self.regions[region_code])
            sections = self.municipalities.get(region_code, {})
            if municipality_code and municipality_code in sections:
                layers.append(sections[municipality_code])
        return layers

    def effective(
        self, region_code: str | None = None, municipality_code: str | None = None
    ) -> EffectiveDirectory:
        """Объединённый справочник; нижний слой уточняет верхний."""
        key = (region_code, municipality_code)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        layers = self.layers_for(region_code, municipality_code)
        organizations: dict[str, Organization] = {}
        channels: dict[str, Channel] = {}
        rules: dict[str, Rule] = {}
        uk_default = self.federal.uk_default
        for layer in layers:
            for organization in layer.organizations:
                organizations[organization.id] = organization
            for channel in layer.channels:
                channels[channel.id] = channel
            for rule in layer.rules:
                rules[rule.id] = rule
            if layer.uk_default is not None:
                uk_default = layer.uk_default
        updated = [layer.updated_at for layer in layers if layer.updated_at is not None]
        effective = EffectiveDirectory(
            version="+".join(f"{layer.layer_id}@{layer.version}" for layer in layers),
            updated_at=min(updated) if updated else None,
            organizations=organizations,
            channels=channels,
            rules=tuple(
                sorted(rules.values(), key=lambda item: (item.priority, -item.layer_depth, item.id))
            ),
            uk_default=uk_default,
            safety=self.safety,
        )
        self._cache[key] = effective
        return effective


def build_directory(
    *,
    federal: Any,
    regions: Mapping[str, Any] | None = None,
    safety: Any = None,
) -> ResponsibilityDirectory:
    """Собрать справочник из разобранных документов слоёв."""
    federal_layer = parse_layer(federal, depth=0)
    if federal_layer.uk_default is None:
        raise DirectoryError("federal layer must define uk_default")
    region_layers: dict[str, DirectoryLayer] = {}
    municipal_layers: dict[str, dict[str, DirectoryLayer]] = {}
    for code, document in (regions or {}).items():
        region_layers[code] = parse_layer(document, depth=1)
        municipal_layers[code] = parse_municipalities(document, depth=2)
    return ResponsibilityDirectory(
        federal=federal_layer,
        regions=region_layers,
        municipalities=municipal_layers,
        safety=parse_safety(safety) if safety is not None else (),
    )
