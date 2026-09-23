from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from domsignal.ai.taxonomy import load_taxonomy
from domsignal.contracts.routing import DANGER_KINDS, LOCATION_SCOPES
from domsignal.services.routing import FEDERAL_DIR, RESPONSIBILITY_FILE, SAFETY_FILE

ROOT = Path(__file__).resolve().parents[1]

RESPONSIBILITY_SCHEMA = ROOT / "regions" / "responsibility.schema.json"
SAFETY_SCHEMA = ROOT / "regions" / "safety.schema.json"
LEGACY_SCHEMA = ROOT / "regions" / "schema.json"


def validator(path: Path) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(path.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )


def report(path: Path, location: str, message: str) -> None:
    print(f"{path.relative_to(ROOT)}:{location}: {message}")


def schema_errors(
    checker: Draft202012Validator, document: Any, path: Path
) -> bool:
    failed = False
    for error in sorted(checker.iter_errors(document), key=lambda item: list(item.path)):
        report(path, ".".join(str(part) for part in error.path) or "<root>", error.message)
        failed = True
    return failed


def sections(document: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Сам слой и его муниципальные секции как области определения записей."""
    yield "<root>", document
    for index, municipality in enumerate(document.get("municipalities") or []):
        yield f"municipalities.{index}", municipality


def identifiers(documents: Iterable[dict[str, Any]], key: str) -> set[str]:
    found: set[str] = set()
    for document in documents:
        for _, section in sections(document):
            for entry in section.get(key) or []:
                found.add(str(entry.get("id")))
    return found


def danger_match_error(rule: dict[str, Any]) -> str | None:
    """Почему правило не может совпадать по виду опасности, или `None`.

    Опасность ортогональна маршруту (v3 §6.2 п. 5): блок безопасности
    карточка получает при любом маршруте, а вид опасности может вести только в
    экстренную службу. Иначе «затопило» уводило бы жителя от аварийной службы
    УК к 112.
    """
    match = rule.get("match") or {}
    kinds = match.get("danger_kinds") or []
    if not kinds and not (match.get("subtypes") or []):
        return "match needs subtypes or danger_kinds"
    if kinds and rule.get("route_type") != "emergency_service":
        return "danger_kinds are allowed only for emergency_service rules"
    unknown = [kind for kind in kinds if kind not in DANGER_KINDS]
    if unknown:
        return f"unknown danger kinds {unknown}"
    return None


def check_danger_match(rule: dict[str, Any], path: Path, location: str) -> bool:
    error = danger_match_error(rule)
    if error is not None:
        report(path, location, error)
        return True
    return False


def check_references(document: dict[str, Any], path: Path, known: dict[str, set[str]]) -> bool:
    failed = False
    codes = set(load_taxonomy().codes)
    for where, section in sections(document):
        for index, channel in enumerate(section.get("channels") or []):
            organization = channel.get("organization_id")
            if organization is not None and organization not in known["organizations"]:
                report(path, f"{where}.channels.{index}", f"unknown organization {organization}")
                failed = True
        for index, rule in enumerate(section.get("rules") or []):
            location = f"{where}.rules.{index}"
            organization = rule.get("organization_id")
            if organization is not None and organization not in known["organizations"]:
                report(path, location, f"unknown organization {organization}")
                failed = True
            for channel_id in rule.get("channel_ids") or []:
                if channel_id not in known["channels"]:
                    report(path, location, f"unknown channel {channel_id}")
                    failed = True
            match = rule.get("match") or {}
            for code in match.get("subtypes") or []:
                if code not in codes:
                    report(path, location, f"unknown subtype {code}")
                    failed = True
            for scope in match.get("location_scopes") or []:
                if scope not in LOCATION_SCOPES:
                    report(path, location, f"unknown location scope {scope}")
                    failed = True
            failed |= check_danger_match(rule, path, location)
    default = document.get("uk_default")
    if default:
        for code in default.get("subtypes") or []:
            if code not in codes:
                report(path, "uk_default.subtypes", f"unknown subtype {code}")
                failed = True
        for code in default.get("resource_supplier_alternatives") or []:
            if code not in (default.get("subtypes") or []):
                report(
                    path,
                    "uk_default.resource_supplier_alternatives",
                    f"{code} is not part of uk_default.subtypes",
                )
                failed = True
    return failed


def check_verification(document: dict[str, Any], path: Path) -> bool:
    """Проверенная запись обязана называть дату проверки и источник.

    Источник — документ по ссылке (официальная публикация закона или
    страница самого сервиса), а не пересказ: у проверенной записи, у
    основания проверенного правила и у каждого факта канала нужен
    `source_url` (решение владельца P7a).
    """
    failed = False
    for where, section in sections(document):
        for key in ("organizations", "channels", "rules"):
            for index, entry in enumerate(section.get(key) or []):
                location = f"{where}.{key}.{index}"
                for position, fact in enumerate(entry.get("facts") or []):
                    if not fact.get("source_url"):
                        report(path, f"{location}.facts.{position}", "a fact needs a source_url")
                        failed = True
                verification = entry.get("verification") or {}
                if verification.get("status") != "verified":
                    continue
                if not verification.get("verified_at") or not verification.get("source_title"):
                    report(
                        path,
                        f"{location}.verification",
                        "verified record needs verified_at and source_title",
                    )
                    failed = True
                if not verification.get("source_url"):
                    report(path, f"{location}.verification", "verified record needs a source_url")
                    failed = True
                if key == "rules" and not (entry.get("basis") or {}).get("source_url"):
                    report(path, f"{location}.basis", "verified rule basis needs a source_url")
                    failed = True
    return failed


def legacy_packs() -> bool:
    checker = validator(LEGACY_SCHEMA)
    paths = sorted((ROOT / "regions").glob("*/pack.yaml"))
    if not paths:
        print("No region packs found")
        return True
    failed = False
    for path in paths:
        failed |= schema_errors(checker, yaml.safe_load(path.read_text(encoding="utf-8")), path)
    return failed


def responsibility_layers() -> bool:
    checker = validator(RESPONSIBILITY_SCHEMA)
    federal = ROOT / "regions" / FEDERAL_DIR / RESPONSIBILITY_FILE
    if not federal.is_file():
        print(f"{federal.relative_to(ROOT)}: federal responsibility layer is missing")
        return True
    paths = [federal] + [
        path
        for path in sorted((ROOT / "regions").glob(f"*/{RESPONSIBILITY_FILE}"))
        if path != federal
    ]
    documents = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in paths]
    failed = False
    for path, document in zip(paths, documents, strict=True):
        failed |= schema_errors(checker, document, path)
    if failed:
        return True
    known = {
        "organizations": identifiers(documents, "organizations"),
        "channels": identifiers(documents, "channels"),
    }
    for path, document in zip(paths, documents, strict=True):
        failed |= check_references(document, path, known)
        failed |= check_verification(document, path)
    return failed


def safety_blocks() -> bool:
    path = ROOT / "regions" / FEDERAL_DIR / SAFETY_FILE
    if not path.is_file():
        print(f"regions/{FEDERAL_DIR}/{SAFETY_FILE}: safety blocks are missing")
        return True
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    failed = schema_errors(validator(SAFETY_SCHEMA), document, path)
    for index, block in enumerate(document.get("blocks") or []):
        for position, step in enumerate(block.get("steps") or []):
            if not step.get("source_title"):
                report(path, f"blocks.{index}.steps.{position}", "a safety step needs a source")
                failed = True
    return failed


def main() -> int:
    failed = legacy_packs()
    failed |= responsibility_layers()
    failed |= safety_blocks()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
