import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from domsignal.main import create_app
from domsignal.settings import AppEnvironment, Settings

ROOT = Path(__file__).resolve().parents[2]


def test_openapi_exposes_only_implemented_c0_routes_and_problem_schema() -> None:
    app = create_app(
        Settings(
            app_env=AppEnvironment.TEST,
            database_url="postgresql+asyncpg://schema:schema@localhost/schema",
            static_dir="missing",
            _env_file=None,
        )
    )
    schema = app.openapi()
    assert schema["openapi"].startswith("3.1.")
    assert "/api/v1/reports" in schema["paths"]
    assert "/api/v1/appeals" not in schema["paths"]
    assert "Problem" in schema["components"]["schemas"]


def test_demo_region_pack_matches_schema_and_has_no_fake_due_date() -> None:
    schema = json.loads((ROOT / "regions/schema.json").read_text(encoding="utf-8"))
    pack = yaml.safe_load((ROOT / "regions/demo/pack.yaml").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(pack)
    assert pack["rules"][0]["verification_status"] == "demo"
    assert pack["rules"][0]["due_at"] is None
