"""D4, В-2: пояс дома из пакета региона — тихие часы, сводка, подпись времени."""

from __future__ import annotations

import copy
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from domsignal.core.display_time import display_zone, staff_moment
from domsignal.core.quiet_hours import quiet_until
from domsignal.core.responsibility import build_directory
from domsignal.services.house_zone import HouseZones, majority

ROOT = Path(__file__).resolve().parents[2]


def layer(name: str) -> dict[str, Any]:
    path = ROOT / "regions" / name / "responsibility.yaml"
    document: dict[str, Any] = yaml.safe_load(path.read_text("utf-8"))
    return document


def far_east_region() -> dict[str, Any]:
    """Регион с поясом Владивостока — только данные, код не знает регионов."""
    document = copy.deepcopy(layer("RU-MOW"))
    document.update(layer_id="RU-FE", region="RU-FE", name="Дальний Восток")
    document["timezone"] = "Asia/Vladivostok"
    return document


ZONES = HouseZones(
    build_directory(
        federal=layer("_federal"),
        regions={"RU-MOW": layer("RU-MOW"), "RU-FE": far_east_region()},
    )
)


def test_the_zone_comes_from_the_region_layer_with_moscow_by_default() -> None:
    assert ZONES.of_region("RU-FE") == "Asia/Vladivostok"
    assert ZONES.of_region("RU-MOW") == "Europe/Moscow"
    assert ZONES.of_region(None) == "Europe/Moscow"
    assert ZONES.of_region("RU-UNKNOWN") == "Europe/Moscow"
    assert HouseZones(None).of_region("RU-FE") == "Europe/Moscow"


#: Один момент UTC: во Владивостоке 23:30, в Москве 16:30.
MOMENT = datetime(2026, 9, 27, 13, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("region", "local", "deferred"),
    [
        ("RU-FE", "23:30", True),  # тихие часы 22:00–08:00 по местному — ждём утра
        ("RU-MOW", "16:30", False),  # в Москве тот же момент — отправляется сразу
    ],
)
def test_quiet_hours_follow_the_house_zone(region: str, local: str, deferred: bool) -> None:
    zone = display_zone(ZONES.of_region(region))
    assert MOMENT.astimezone(zone).strftime("%H:%M") == local
    until = quiet_until(22 * 60, 8 * 60, MOMENT, zone)
    assert (until is not None) is deferred
    if until is not None:
        assert until.astimezone(zone).strftime("%d.%m %H:%M") == "28.09 08:00"
        assert until.astimezone(UTC) == datetime(2026, 9, 27, 22, 0, tzinfo=UTC)


def test_staff_time_carries_the_zone_label() -> None:
    assert staff_moment(MOMENT, "Europe/Moscow") == "27.09.2026 16:30 МСК"
    assert staff_moment(MOMENT, "Asia/Vladivostok") == "27.09.2026 23:30 ВЛАД"
    assert staff_moment(MOMENT, "Asia/Yekaterinburg") == "27.09.2026 18:30 UTC+05:00"


def test_company_zone_is_the_majority_of_its_houses() -> None:
    moscow, far_east = "Europe/Moscow", "Asia/Vladivostok"
    assert majority([far_east, far_east, moscow]) == far_east
    assert majority([far_east, moscow]) == moscow  # равенство — пояс по умолчанию
    assert majority([]) == moscow
    assert majority(["Asia/Yakutsk", far_east]) == far_east  # равенство без Москвы — по имени


def validator() -> Any:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validate_region_pack

        return validate_region_pack
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_the_validator_refuses_an_unknown_time_zone() -> None:
    check = validator()
    assert check.timezone_error(layer("RU-MOW")) is None
    assert check.timezone_error(far_east_region()) is None
    broken = {**layer("RU-MOW"), "timezone": "Europe/Atlantis"}
    assert check.timezone_error(broken) == "unknown time zone Europe/Atlantis"


def test_a_region_layer_must_name_its_time_zone() -> None:
    schema = validator().validator(ROOT / "regions" / "responsibility.schema.json")
    document = layer("RU-MOW")
    del document["timezone"]
    assert any("timezone" in error.message for error in schema.iter_errors(document))
    assert not list(schema.iter_errors(layer("_federal")))
