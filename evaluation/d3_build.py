"""Сборка набора D3 (синтетические диалоги) из исходников в `datasets/d3/source/`.

    uv run python evaluation/d3_build.py            # проверить и собрать
    uv run python evaluation/d3_build.py --check    # только проверить

Исходник — простой текстовый формат, удобный для письма и вычитки:

    === d001 s01 typical
    @I1 elevator.stopped house_common entrance=2 since="с обеда" cur=yes loc=yes obs=yes expect=yes
    +0 A: Соседи, во втором подъезде лифт опять встал | new_problem | I1
    +40 B>1: у нас тоже | me_too | I1
    +25 C: всем привет | chatter
    +15 D: там кто-то внутри кричит | more_info | I1 | !person_trapped

- `+N` — секунды от предыдущей реплики; `B>1` — ответ на реплику 1 диалога;
- роль — одна из 10 ролей контракта; затем номера инцидентов (или `-`);
  `!вид` — реплика несёт доказательство опасности этого вида;
- `@I…` — инцидент: подтип, территория, подъезд, этаж, «с какого времени»,
  признаки `cur/loc/obs`, `uk` (зона УК по смыслу; моделью не выдаётся — v3
  §4.1), `danger=вид` и `expect=yes|no` — должен ли инцидент стать сигналом.

Ожидаемый `route_type` инцидента не пишется руками в каждом диалоге: он
берётся из эталона маршрутов `datasets/routing/route_reference.v1.jsonl` по
подтипу, территории и опасности. Нет строки в эталоне — сборка падает.

Разделение — по диалогам (инцидент целиком в одной части), с фиксированным
seed и стратификацией по семейству сценария: dev 60 % / holdout 40 %.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import random
import re
import shlex
import sys
from dataclasses import dataclass, field
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domsignal.ai.contracts import DANGER_KINDS, LOCATION_SCOPES, ROLES  # noqa: E402
from domsignal.ai.taxonomy import load_taxonomy  # noqa: E402

SOURCE_DIR = pathlib.Path("datasets/d3/source")
SCENARIOS_FILE = pathlib.Path("datasets/d3/scenarios.v1.jsonl")
ROUTES_FILE = pathlib.Path("datasets/routing/route_reference.v1.jsonl")
OUT_DIR = pathlib.Path("datasets/synthetic")
DEV_FILE = OUT_DIR / "d3_dialogs.v1.dev.jsonl"
HOLDOUT_FILE = OUT_DIR / "d3_dialogs.v1.holdout.jsonl"

SEED = 20260923
DEV_SHARE = 0.6
AUTHOR = (
    "agent P6 (DEV-A), модель Claude Opus 5.5 (Anthropic) — другое семейство, "
    "чем оцениваемые openai/gpt-5-mini и google/gemini-3.1-flash-lite; 23.09.2026"
)

_HEADER = re.compile(r"^=== (d\d{3}) ([snm]\d{2}) ([a-z_]+)$")
_LINE = re.compile(r"^\+(\d+) ([A-Z])(?:>(\d+))?: (.+)$")
_FACETS = ("cur", "loc", "obs")
_YES_NO = {"yes", "no", "unclear"}


class D3Error(ValueError):
    """Исходник D3 не проходит проверку разметки."""


@dataclass
class Incident:
    key: str
    subtype: str
    scope: str
    entrance: str | None = None
    floor: str | None = None
    since: str | None = None
    facets: dict[str, str] = field(default_factory=dict)
    uk: str = "unclear"
    danger: str | None = None
    expect: bool = True


@dataclass
class Dialog:
    id: str
    scenario: str
    style: str
    incidents: dict[str, Incident] = field(default_factory=dict)
    lines: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""


def load_routes(path: pathlib.Path = ROUTES_FILE) -> dict[tuple[str, str, str], str]:
    routes: dict[tuple[str, str, str], str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        row = json.loads(raw)
        key = (row["subtype"], row["location_scope"], row.get("danger_kind") or "-")
        routes[key] = row["expected_route_type"]
    return routes


def load_scenarios(path: pathlib.Path = SCENARIOS_FILE) -> dict[str, dict[str, Any]]:
    scenarios: dict[str, dict[str, Any]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            row = json.loads(raw)
            scenarios[row["id"]] = row
    return scenarios


def _incident(key: str, rest: str, where: str) -> Incident:
    tokens = shlex.split(rest)
    if len(tokens) < 2:
        raise D3Error(f"{where}: инцидент без подтипа и территории")
    incident = Incident(key=key, subtype=tokens[0], scope=tokens[1])
    for token in tokens[2:]:
        name, _, value = token.partition("=")
        if name == "entrance":
            incident.entrance = value or None
        elif name == "floor":
            incident.floor = value or None
        elif name == "since":
            incident.since = value or None
        elif name in _FACETS:
            if value not in _YES_NO:
                raise D3Error(f"{where}: {name}={value!r}")
            incident.facets[name] = value
        elif name == "uk":
            incident.uk = value
        elif name == "danger":
            incident.danger = None if value in ("", "-") else value
        elif name == "expect":
            incident.expect = value == "yes"
        else:
            raise D3Error(f"{where}: неизвестное поле инцидента {name!r}")
    for name in _FACETS:
        incident.facets.setdefault(name, "unclear")
    return incident


def parse_source(text: str, source: str) -> list[Dialog]:
    dialogs: list[Dialog] = []
    current: Dialog | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        where = f"{source}:{number}"
        if not line or line.startswith("#"):
            continue
        header = _HEADER.match(line)
        if header:
            current = Dialog(id=header[1], scenario=header[2], style=header[3], source=source)
            dialogs.append(current)
            continue
        if current is None:
            raise D3Error(f"{where}: строка вне диалога")
        if line.startswith("@I"):
            key, _, rest = line[1:].partition(" ")
            current.incidents[key] = _incident(key, rest, where)
            continue
        match = _LINE.match(line)
        if not match:
            raise D3Error(f"{where}: не разобрана строка {line!r}")
        gap, author, reply, body = match.groups()
        parts = [part.strip() for part in body.split(" | ")]
        if len(parts) < 2:
            raise D3Error(f"{where}: нет роли")
        text_part, role = parts[0], parts[1]
        refs: list[str] = []
        danger: str | None = None
        for extra in parts[2:]:
            if extra.startswith("!"):
                danger = extra[1:]
            elif extra != "-":
                refs.extend(item.strip() for item in extra.split(","))
        current.lines.append(
            {
                "gap": int(gap),
                "author": author,
                "reply": int(reply) if reply else None,
                "text": text_part,
                "role": role,
                "refs": refs,
                "danger": danger,
                "where": where,
            }
        )
    return dialogs


def validate(
    dialogs: list[Dialog],
    routes: dict[tuple[str, str, str], str],
    scenarios: dict[str, dict[str, Any]],
) -> None:
    taxonomy = load_taxonomy()
    seen: set[str] = set()
    for dialog in dialogs:
        if dialog.id in seen:
            raise D3Error(f"{dialog.id}: повтор идентификатора")
        seen.add(dialog.id)
        if dialog.scenario not in scenarios:
            raise D3Error(f"{dialog.id}: сценарий {dialog.scenario} не описан")
        if not 10 <= len(dialog.lines) <= 20:
            raise D3Error(f"{dialog.id}: {len(dialog.lines)} реплик, нужно 10–20")
        for incident in dialog.incidents.values():
            where = f"{dialog.id}.{incident.key}"
            if not taxonomy.is_known(incident.subtype):
                raise D3Error(f"{where}: неизвестный подтип {incident.subtype}")
            if incident.scope not in LOCATION_SCOPES:
                raise D3Error(f"{where}: неизвестная территория {incident.scope}")
            if incident.danger is not None and incident.danger not in DANGER_KINDS:
                raise D3Error(f"{where}: неизвестный вид опасности {incident.danger}")
            if incident.expect and route_key(incident) not in routes:
                raise D3Error(f"{where}: нет строки эталона маршрута для {route_key(incident)}")
        used: set[str] = set()
        for index, line in enumerate(dialog.lines, start=1):
            if line["role"] not in ROLES:
                raise D3Error(f"{line['where']}: неизвестная роль {line['role']!r}")
            for ref in line["refs"]:
                if ref not in dialog.incidents:
                    raise D3Error(f"{line['where']}: инцидент {ref} не объявлен")
                used.add(ref)
            if line["reply"] is not None and not 1 <= line["reply"] < index:
                raise D3Error(f"{line['where']}: ответ на несуществующую реплику")
            if line["danger"] is not None and line["danger"] not in DANGER_KINDS:
                raise D3Error(f"{line['where']}: неизвестный вид опасности {line['danger']}")
            if line["role"] == "new_problem" and not line["refs"]:
                raise D3Error(f"{line['where']}: new_problem без инцидента")
        unused = set(dialog.incidents) - used
        if unused:
            raise D3Error(f"{dialog.id}: инциденты без реплик {sorted(unused)}")


def route_key(incident: Incident) -> tuple[str, str, str]:
    return (incident.subtype, incident.scope, incident.danger or "-")


def to_row(
    dialog: Dialog,
    routes: dict[tuple[str, str, str], str],
    scenarios: dict[str, dict[str, Any]],
    split: str,
) -> dict[str, Any]:
    offset = 0
    lines: list[dict[str, Any]] = []
    for index, line in enumerate(dialog.lines, start=1):
        offset += line["gap"] if index > 1 else 0
        lines.append(
            {
                "n": index,
                "offset_s": offset,
                "author": line["author"],
                "reply_to": line["reply"],
                "text": line["text"],
                "role": line["role"],
                "incidents": [f"{dialog.id}.{ref}" for ref in line["refs"]],
                "danger": line["danger"],
            }
        )
    incidents = [
        {
            "id": f"{dialog.id}.{incident.key}",
            "subtype": incident.subtype,
            "location_scope": incident.scope,
            "entrance": incident.entrance,
            "floor": incident.floor,
            "since": incident.since,
            "facets": {
                "current": incident.facets["cur"],
                "local": incident.facets["loc"],
                "observed": incident.facets["obs"],
            },
            "uk_scope": incident.uk,
            "danger_kind": incident.danger,
            "signal_expected": incident.expect,
            "expected_route_type": routes.get(route_key(incident)) if incident.expect else None,
        }
        for incident in dialog.incidents.values()
    ]
    scenario = scenarios[dialog.scenario]
    return {
        "kind": "dialog",
        "id": dialog.id,
        "scenario": dialog.scenario,
        "family": scenario["family"],
        "style": dialog.style,
        "split": split,
        "lines": lines,
        "incidents": incidents,
        "synthetic": True,
        "author": AUTHOR,
    }


def split_dialogs(
    dialogs: list[Dialog], scenarios: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Стратифицированное разделение по семейству сценария с фиксированным seed."""
    rng = random.Random(SEED)
    by_family: dict[str, list[str]] = {}
    for dialog in sorted(dialogs, key=lambda item: item.id):
        by_family.setdefault(scenarios[dialog.scenario]["family"], []).append(dialog.id)
    result: dict[str, str] = {}
    for family in sorted(by_family):
        ids = by_family[family]
        rng.shuffle(ids)
        cut = round(len(ids) * DEV_SHARE)
        for index, dialog_id in enumerate(ids):
            result[dialog_id] = "dev" if index < cut else "holdout"
    return result


def build(check_only: bool = False) -> dict[str, Any]:
    routes = load_routes()
    scenarios = load_scenarios()
    dialogs: list[Dialog] = []
    for path in sorted(SOURCE_DIR.glob("*.d3")):
        dialogs.extend(parse_source(path.read_text(encoding="utf-8"), path.name))
    validate(dialogs, routes, scenarios)
    splits = split_dialogs(dialogs, scenarios)
    rows = {
        "dev": [to_row(d, routes, scenarios, "dev") for d in dialogs if splits[d.id] == "dev"],
        "holdout": [
            to_row(d, routes, scenarios, "holdout") for d in dialogs if splits[d.id] == "holdout"
        ],
    }
    summary: dict[str, Any] = {"dialogs": len(dialogs), "seed": SEED}
    for name, part in rows.items():
        summary[name] = {
            "dialogs": len(part),
            "lines": sum(len(row["lines"]) for row in part),
            "incidents_expected": sum(
                1 for row in part for item in row["incidents"] if item["signal_expected"]
            ),
            "incidents_not_expected": sum(
                1 for row in part for item in row["incidents"] if not item["signal_expected"]
            ),
        }
    if check_only:
        return summary
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in (("dev", DEV_FILE), ("holdout", HOLDOUT_FILE)):
        body = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in sorted(rows[name], key=lambda item: item["id"])
        )
        path.write_bytes(body.encode("utf-8"))
        summary[name]["file"] = path.as_posix()
        summary[name]["sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the D3 synthetic dialogs dataset")
    parser.add_argument("--check", action="store_true", help="validate sources only")
    args = parser.parse_args()
    print(json.dumps(build(check_only=args.check), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
