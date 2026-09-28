"""Название УК в текстах бота: без «УК «УК …»» и двойных кавычек."""

from __future__ import annotations

import pytest

from domsignal.services.chat_voice import connection_notice_text, reading_notice_text
from domsignal.services.community_texts import company_quoted, sender_label


@pytest.mark.parametrize(
    ("name", "quoted"),
    [
        ("Солнечная", "«Солнечная»"),
        ("  Приёмка ДС ", "«Приёмка ДС»"),
        ("УК «Пилотная, 7»", "УК «Пилотная, 7»"),
        ("УК Первая (тест)", "УК Первая (тест)"),
        ("ООО «Ромашка»", "ООО «Ромашка»"),
        ("ТСЖ Берёзовая", "ТСЖ Берёзовая"),
        ("Укромный двор", "«Укромный двор»"),
    ],
)
def test_company_is_quoted_once(name: str, quoted: str) -> None:
    assert company_quoted(name) == quoted


def test_sender_label_does_not_repeat_the_legal_form() -> None:
    assert sender_label("company", "УК «Пилотная, 7»") == "Сообщение от УК «Пилотная, 7»"
    assert sender_label("company", "Солнечная") == "Сообщение от УК «Солнечная»"
    assert sender_label("company", "ООО «Ромашка»") == "Сообщение от УК ООО «Ромашка»"


def test_chat_notices_quote_the_company_once() -> None:
    reading = reading_notice_text("УК «Пилотная, 7»")
    assert "подтверждено управляющей компанией УК «Пилотная, 7»." in reading
    assert "Отключить чтение может управляющая компания УК «Пилотная, 7»." in reading
    assert "««" not in reading and "»»" not in reading
    assert "управляющей компанией «Солнечная»" in connection_notice_text("Солнечная")
