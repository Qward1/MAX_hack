from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    schema = json.loads((ROOT / "regions" / "schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    paths = sorted((ROOT / "regions").glob("*/pack.yaml"))
    if not paths:
        print("No region packs found")
        return 1
    failed = False
    for path in paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            print(f"{path.relative_to(ROOT)}:{location}: {error.message}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
