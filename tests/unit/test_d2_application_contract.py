"""Заявка УК (D2): ошибка формата называет своё поле, чтобы форма сказала, что исправить."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from domsignal.contracts.onboarding import CompanyApplicationCreate

BASE = {
    "legal_name": "ООО «Проверка»",
    "short_name": "Проверка",
    "inn": "7712345678",
    "contact_name": "Иван Петров",
    "requested_chat_count": 2,
}


def locations(**patch: object) -> list[tuple[object, ...]]:
    with pytest.raises(ValidationError) as caught:
        CompanyApplicationCreate(**{**BASE, **patch})
    return [tuple(error["loc"]) for error in caught.value.errors()]


@pytest.mark.parametrize(
    ("patch", "field"),
    [
        ({"contact_email": "test@mail"}, "contact_email"),
        ({"contact_email": "a b@mail.ru"}, "contact_email"),
        ({"contact_phone": "-----"}, "contact_phone"),
        ({"contact_phone": "позвонить"}, "contact_phone"),
        ({"contact_email": "ok@mail.ru", "house_addresses": ["д. 5"]}, "house_addresses"),
    ],
)
def test_format_error_names_the_field(patch: dict[str, object], field: str) -> None:
    assert [loc[0] for loc in locations(**patch)] == [field]


def test_missing_contact_is_a_form_level_error() -> None:
    assert locations(contact_email="", contact_phone=" ") == [()]


@pytest.mark.parametrize(
    "phone",
    [
        "+7 (999) 123-45-67",
        "8-843-200-00-00 доб. 12",
        "8 (843) 200–00–00",
        "+7 900 000 00 00 ext. 5",
    ],
)
def test_ordinary_phone_formats_are_accepted(phone: str) -> None:
    model = CompanyApplicationCreate(**BASE, contact_phone=phone, contact_email="")
    assert model.contact_phone == phone and model.contact_email is None
