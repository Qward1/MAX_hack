"""D5 §4.2: новый регион одной командой — каркас проходит валидатор и роутер."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

from domsignal.services.routing import RoutingService, load_directory
from domsignal.tools import region_pack
from domsignal.tools.route_preview import compare_regions, regions

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "regions", tmp_path / "regions")
    return tmp_path


def validator(root: Path) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validate_region_pack
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    saved = validate_region_pack.ROOT
    validate_region_pack.ROOT = root
    try:
        return int(validate_region_pack.main())
    finally:
        validate_region_pack.ROOT = saved


def test_one_command_makes_a_pack_the_validator_and_router_accept(workspace: Path) -> None:
    code = region_pack.main(
        [
            "new",
            "RU-SVE",
            "--name",
            "Свердловская область",
            "--timezone",
            "Asia/Yekaterinburg",
            "--municipality",
            "ekb:Екатеринбург",
            "--regions-dir",
            str(workspace / "regions"),
        ]
    )
    assert code == 0
    document = yaml.safe_load((workspace / "regions/RU-SVE/responsibility.yaml").read_text("utf-8"))
    assert document["timezone"] == "Asia/Yekaterinburg" and document["rules"] == []
    assert {c["verification"]["status"] for c in document["channels"]} == {"needs_verification"}
    assert validator(workspace) == 0

    routing = RoutingService(load_directory(workspace / "regions"))
    assert "RU-SVE" in [pack for _, pack, _ in regions(routing)]
    assert routing.directory is not None
    assert routing.directory.timezone_for("RU-SVE") == "Asia/Yekaterinburg"
    for subtype, _, routes in compare_regions(routing):
        route = routes["RU-SVE"]
        # Непроверенный канал жителю не показывается: только федеральный слой.
        assert all(not channel.id.startswith("ru_sve") for channel in route.channels), subtype
    lighting = {subtype: routes["RU-SVE"] for subtype, _, routes in compare_regions(routing)}
    assert [c.id for c in lighting["street_lighting.failure"].channels] == [
        c.id for c in lighting["street_lighting.failure"].channels if c.id.startswith("federal")
    ] or lighting["street_lighting.failure"].channels


def test_bad_input_and_an_existing_pack_are_refused(workspace: Path) -> None:
    root = workspace / "regions"
    with pytest.raises(ValueError, match="ISO"):
        region_pack.create(root, "SVE", name="X", timezone="Europe/Moscow", municipalities=[])
    with pytest.raises(ValueError, match="пояс"):
        region_pack.create(root, "RU-SVE", name="X", timezone="Mars/Olympus", municipalities=[])
    with pytest.raises(ValueError, match="уже есть"):
        region_pack.create(root, "RU-TA", name="X", timezone="Europe/Moscow", municipalities=[])
