from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from domsignal.api.init_data import validate_init_data
from domsignal.services.errors import InvalidInitData

BOT_TOKEN = "test-bot-token"
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def signed(**overrides: str) -> str:
    values = {
        "auth_date": str(int(NOW.timestamp())),
        "query_id": "query-1",
        "user": json.dumps(
            {"id": 123, "first_name": "Иван", "last_name": "Иванов"},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    values.update(overrides)
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_valid_signature_returns_normalized_user() -> None:
    user = validate_init_data(signed(), bot_token=BOT_TOKEN, max_age_seconds=300, now=NOW)
    assert str(user.id) == "123"
    assert user.display_name == "Иван Иванов"


@pytest.mark.parametrize(
    "raw",
    [
        lambda: signed().replace("query_id=query-1", "query_id=query-2"),
        lambda: signed() + "&hash=0" * 64,
        lambda: signed(extra="unknown"),
        lambda: signed(user=json.dumps({"id": 1, "first_name": "A", "admin": True})),
        lambda: signed(user=json.dumps({"id": False, "first_name": "A"})),
    ],
)
def test_rejects_tampering_duplicates_and_unknown_fields(raw: object) -> None:
    with pytest.raises(InvalidInitData):
        validate_init_data(raw(), bot_token=BOT_TOKEN, max_age_seconds=300, now=NOW)  # type: ignore[operator]


def test_rejects_expired_data() -> None:
    old = NOW - timedelta(minutes=6)
    with pytest.raises(InvalidInitData, match="expired"):
        validate_init_data(
            signed(auth_date=str(int(old.timestamp()))),
            bot_token=BOT_TOKEN,
            max_age_seconds=300,
            now=NOW,
        )
