from __future__ import annotations

import argparse
import json
from pathlib import Path

from domsignal.main import create_app
from domsignal.settings import AppEnvironment, Settings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "openapi.json"


def rendered_schema() -> str:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        database_url="postgresql+asyncpg://schema:schema@localhost/schema",
        static_dir="__schema_export_has_no_static__",
    )
    app = create_app(settings)
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_schema()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("docs/openapi.json is stale; run: uv run python scripts/export_openapi.py")
            return 1
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
