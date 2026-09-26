"""Каркас пакета нового региона одной командой (D5, docs/SCALING.md).

    python -m domsignal.tools.region_pack new RU-XX --name "Название региона" \\
        --timezone Europe/Moscow --municipality code:"Город" [--municipality ...]

Создаёт `regions/<КОД>/responsibility.yaml`: слой региона с поясом и
муниципалитетами, организация и канал жилнадзора — `needs_verification`
(хранятся, жителю не показываются), правил маршрута нет. До заполнения данных
регион работает на федеральном слое: ПОС, 112, заявка УК, честное «не
определён». Дальше — чек-лист в docs/SCALING.md: официальные каналы с
цитатой и датой, проверка вторым человеком, `scripts/validate_region_pack.py`.
Существующий пакет не перезаписывается.
"""

from __future__ import annotations

import argparse
import re
import sys
import zoneinfo
from datetime import UTC, datetime
from pathlib import Path

import yaml  # type: ignore[import-untyped]

REGION_CODE = re.compile(r"^RU-[A-Z]{2,3}$")
MUNICIPALITY_CODE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

HEADER = """# Региональный слой справочника ответственности: {name}.
#
# Каркас создан командой `python -m domsignal.tools.region_pack new {code}` {day}.
# Регион данными, не кодом. Пока здесь нет проверенных записей, дома региона
# видят федеральный слой: ПОС «Госуслуги. Решаем вместе», 112, заявку УК и
# честное «ответственный не определён». Чек-лист заполнения — docs/SCALING.md
# («Как подключить регион»): официальная страница органа власти, дословная
# цитата и дата проверки → `verified`; иначе запись остаётся
# `needs_verification` и жителю не показывается.
"""


def slug(code: str) -> str:
    return code.lower().replace("-", "_")


def skeleton(
    code: str, name: str, timezone: str, municipalities: list[tuple[str, str]], day: str
) -> dict[str, object]:
    prefix = slug(code)
    pending = {
        "status": "needs_verification",
        "verified_at": None,
        "verified_by": None,
        "source_title": "Заполнить: официальная страница органа власти, дословная цитата и дата",
        "source_url": None,
    }
    return {
        "schema_version": 1,
        "layer_id": code,
        "layer": "region",
        "region": code,
        "name": name,
        "timezone": timezone,
        "version": "1",
        "updated_at": day,
        "organizations": [
            {
                "id": f"{prefix}_gzhi",
                "name": f"Государственная жилищная инспекция ({name})",
                "kind": "other_authority",
                "region": code,
                "municipality": None,
                "verification": dict(pending),
            }
        ],
        "channels": [
            {
                "id": f"{prefix}_gzhi_web",
                "organization_id": f"{prefix}_gzhi",
                "channel_type": "official_web",
                "label": f"Приёмная жилищной инспекции ({name})",
                "url": None,
                "phone": None,
                "entry_hint": None,
                "routes_to_competent_authority": False,
                "facts": [],
                "unavailable_regions": [],
                "verification": dict(pending),
            }
        ],
        "rules": [],
        "reference_links": [],
        "municipalities": [
            {"code": item_code, "name": item_name, "organizations": [], "channels": [], "rules": []}
            for item_code, item_name in municipalities
        ],
    }


def create(
    root: Path,
    code: str,
    *,
    name: str,
    timezone: str,
    municipalities: list[tuple[str, str]],
    today: str | None = None,
) -> Path:
    """Создать каркас пакета. Ошибка входа — `ValueError` с объяснением."""
    if not REGION_CODE.fullmatch(code):
        raise ValueError("Код региона — ISO 3166-2:RU, например RU-SVE")
    if timezone not in zoneinfo.available_timezones():
        raise ValueError(f"Неизвестный часовой пояс {timezone}")
    if not name.strip():
        raise ValueError("Нужно название региона")
    for item_code, _ in municipalities:
        if not MUNICIPALITY_CODE.fullmatch(item_code):
            raise ValueError(f"Код муниципалитета {item_code}: латиница, цифры и «_»")
    target = root / code / "responsibility.yaml"
    if target.exists():
        raise ValueError(f"Пакет {code} уже есть: {target}")
    day = today or datetime.now(UTC).date().isoformat()
    body = yaml.safe_dump(
        skeleton(code, name.strip(), timezone, municipalities, day),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    target.parent.mkdir(parents=True, exist_ok=False)
    target.write_bytes((HEADER.format(name=name.strip(), code=code, day=day) + body).encode())
    return target


def municipality(value: str) -> tuple[str, str]:
    code, separator, name = value.partition(":")
    if not separator or not name.strip():
        raise argparse.ArgumentTypeError("муниципалитет: код:Название, например ekb:Екатеринбург")
    return code.strip(), name.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Каркас пакета региона")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="создать каркас regions/<КОД>/responsibility.yaml")
    new.add_argument("code")
    new.add_argument("--name", required=True)
    new.add_argument("--timezone", required=True)
    new.add_argument("--municipality", action="append", type=municipality, default=[])
    new.add_argument("--regions-dir", type=Path, default=Path("regions"))
    args = parser.parse_args(argv)
    try:
        path = create(
            args.regions_dir,
            args.code,
            name=args.name,
            timezone=args.timezone,
            municipalities=args.municipality,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Создан {path}. Дальше: заполнить каналы по чек-листу docs/SCALING.md и запустить")
    print("  uv run python scripts/validate_region_pack.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
