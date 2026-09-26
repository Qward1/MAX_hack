"""D4, В-5: страница /privacy и ссылка на неё во всех входах продукта."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domsignal.bootstrap import build_container
from domsignal.main import create_app
from domsignal.services import privacy
from domsignal.services.action_cards import FORBIDDEN_PHRASES
from domsignal.services.bot_replies import GREETING, HELP
from domsignal.services.chat_voice import connection_notice_text, reading_notice_text
from domsignal.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://domsignal.example"
URL = f"{BASE}/privacy"
#: Решение владельца D4: в интерфейсе нет надписей «тест», «демо», «тестовые данные».
NOT_IN_UI = ("тест", "демо", "demo")
#: Экраны со ссылкой: подвал страницы продукта, «Мой дом», заявка УК.
SCREENS = (
    "miniapp/src/site/Landing.tsx",
    "miniapp/src/features/community/CommunityScreens.tsx",
    "miniapp/src/admin/CompanyApply.tsx",
)


def settings(**extra: object) -> Settings:
    return Settings(static_dir="missing", public_base_url=BASE, _env_file=None, **extra)


def page(contact: str | None = None) -> str:
    return privacy.render_privacy_page(contact=contact, site_url=f"{BASE}/site")


def test_the_page_answers_the_five_questions_without_forbidden_claims() -> None:
    html = page()
    for title in (
        privacy.READS_TITLE,
        privacy.STORES_TITLE,
        privacy.MODEL_TITLE,
        privacy.OFF_TITLE,
        privacy.CONTACT_TITLE,
    ):
        assert f"<h2>{title}</h2>" in html
    assert "polza.ai" in html and "72 часов" in html and "«MAX-чаты»" in html
    lowered = html.lower()
    for phrase in (*FORBIDDEN_PHRASES, *NOT_IN_UI):
        assert phrase not in lowered, phrase
    assert f"{BASE}/site" in html  # без контакта — страница продукта
    assert "privacy@domsignal.example" in page("privacy@domsignal.example")


def test_the_page_is_public_and_served_with_the_site_headers() -> None:
    with TestClient(create_app(settings())) as client:
        response = client.get("/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert privacy.PRIVACY_TITLE in response.text


def test_bot_greeting_help_and_chat_notices_link_the_page() -> None:
    container = build_container(settings())
    try:
        assert container.personal_bot.privacy_url == URL
        assert container.passive.privacy_url == URL
        for text in (GREETING, HELP):
            linked = container.personal_bot._with_privacy(text)
            assert linked.startswith(text) and linked.endswith(URL)
    finally:
        container.engine.sync_engine.dispose()
    for notice in (reading_notice_text("УК", URL), connection_notice_text("УК", URL)):
        assert notice.endswith(privacy.PRIVACY_LINE.format(url=URL))
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in notice.lower()


@pytest.mark.parametrize("surface", SCREENS)
def test_every_entry_screen_links_the_page(surface: str) -> None:
    text = (ROOT / surface).read_text(encoding="utf-8")
    assert "/privacy" in text and "Политика данных" in text
