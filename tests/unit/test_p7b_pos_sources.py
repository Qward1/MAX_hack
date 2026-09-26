"""P7b §3: основания фактов ПОС и кнопка перехода в официальный сервис.

Правило владельца: нормы — из официальной публикации закона, свойства сервиса
— со страницы самого сервиса без входа; «скриншоты» основанием не считаются,
а факт без источника жителю не показывается. Кнопка «Открыть Госуслуги»
активна только при заполненном и подтверждённом владельцем `url`.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import pytest
import yaml

from domsignal.contracts.routing import RouteChannel
from domsignal.services.appeal_drafts import _actions
from domsignal.services.routing import load_directory
from tests.unit.test_action_cards import card, packaged, resolve  # noqa: F401
from tests.unit.test_routing_core import federal_house

ROOT = Path(__file__).resolve().parents[2]
REGIONS = ROOT / "regions"
FEDERAL = REGIONS / "_federal" / "responsibility.yaml"

#: Официальные источники: публикация закона и страницы самого сервиса.
OFFICIAL_HOSTS = {"publication.pravo.gov.ru", "pravo.gov.ru", "pos.gosuslugi.ru", "gu-st.ru"}


def federal() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(FEDERAL.read_text(encoding="utf-8"))
    return document


def pos_channel() -> dict[str, Any]:
    return next(item for item in federal()["channels"] if item["id"] == "pos_gosuslugi")


def validator_module() -> Any:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import validate_region_pack

        return validate_region_pack
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_every_pos_fact_has_an_official_document_link() -> None:
    channel = pos_channel()
    assert channel["facts"]
    for fact in channel["facts"]:
        assert fact["source_title"] and fact["source_url"], fact
        assert urlparse(fact["source_url"]).hostname in OFFICIAL_HOSTS, fact
        assert "23.09.2026" in fact["source_title"], "дата проверки названа"


def test_the_deadline_follows_the_law_and_not_a_screenshot() -> None:
    facts = [fact["text"] for fact in pos_channel()["facts"]]
    deadline = next(text for text in facts if "30 дней" in text)
    assert "«рассматривается в течение 30 дней со дня регистрации письменного обращения»" in (
        deadline
    )
    assert "календарных" not in " ".join(facts)
    law = next(fact for fact in pos_channel()["facts"] if fact["text"] == deadline)
    assert "59-ФЗ" in law["source_title"] and "ст. 12" in law["source_title"]


def test_facts_not_visible_without_login_are_gone() -> None:
    text = " ".join(fact["text"] for fact in pos_channel()["facts"])
    assert "10 файлов" not in text and "10 МБ" not in text and "Москв" not in text


def test_no_record_in_the_directory_rests_on_screenshots() -> None:
    for path in REGIONS.glob("*/responsibility.yaml"):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        dumped = yaml.safe_dump(document, allow_unicode=True)
        assert "криншот" not in dumped, path


def test_pos_channel_rests_on_480_fz_official_publication() -> None:
    verification = pos_channel()["verification"]
    assert verification["status"] == "verified"
    assert verification["verified_at"] == "2026-09-23"
    assert "480-ФЗ" in verification["source_title"]
    assert verification["source_url"] == (
        "http://publication.pravo.gov.ru/document/0001202308040085"
    )


def test_the_municipal_rule_basis_quotes_the_service_page() -> None:
    rule = next(
        item for item in federal()["rules"] if item["id"] == "federal.municipal_territory.default"
    )
    assert rule["basis"]["source_url"] == "https://pos.gosuslugi.ru/landing/"
    assert "«о ямах, мусоре, плохом освещении и других проблемах»" in rule["basis"]["text"]


def test_the_packaged_card_shows_only_sourced_facts_and_a_disabled_button(
    packaged: Any,  # noqa: F811
) -> None:
    route = resolve(packaged, "street_lighting.failure", "municipal_territory", federal_house())
    built = card(route)
    assert built.facts and all(fact.source_title and fact.source_url for fact in built.facts)
    action = next(item for item in built.actions if item.type == "open_official_channel")
    if pos_channel()["url"] is None:
        assert action.enabled is False and action.url is None
        assert action.reason and "«Сообщите, что вас волнует»" in action.reason
    else:
        assert action.enabled is True and action.url == pos_channel()["url"]


def _channel(url: str | None) -> RouteChannel:
    return RouteChannel(
        id="pos_gosuslugi",
        channel_type="official_web",
        label="Госуслуги. Решаем вместе",
        url=url,
        entry_hint="Госуслуги → «Сообщите, что вас волнует»",
        verification_status="verified",
    )


@pytest.mark.parametrize("url", [None, "https://www.gosuslugi.ru/help/obratitsya_v_pos"])
def test_the_draft_button_is_active_only_with_a_filled_url(url: str | None) -> None:
    draft = SimpleNamespace(filed_at=None, id=uuid4(), created_at=datetime.now(UTC))
    actions = {item.code: item for item in _actions(draft, _channel(url))}  # type: ignore[arg-type]
    button = actions["open_official_channel"]
    assert button.enabled is bool(url)
    assert (button.reason is None) is bool(url)


def test_the_validator_rejects_facts_and_verified_records_without_a_link(tmp_path: Path) -> None:
    module = validator_module()
    document = federal()
    assert module.check_verification(document, FEDERAL) is False
    broken = federal()
    channel = next(item for item in broken["channels"] if item["id"] == "pos_gosuslugi")
    channel["facts"][0]["source_url"] = None
    assert module.check_verification(broken, FEDERAL) is True
    broken = federal()
    rule = next(item for item in broken["rules"] if item["verification"]["status"] == "verified")
    rule["verification"]["source_url"] = None
    assert module.check_verification(broken, FEDERAL) is True
    broken = federal()
    rule = next(item for item in broken["rules"] if item["verification"]["status"] == "verified")
    rule["basis"]["source_url"] = None
    assert module.check_verification(broken, FEDERAL) is True


def test_the_directory_still_loads_for_kazan() -> None:
    effective = load_directory(REGIONS).effective("RU-TA", "kazan")
    assert effective.version.startswith("_federal@3")  # D4: «Госуслуги Дом»
    assert "pos_gosuslugi" in effective.channels
