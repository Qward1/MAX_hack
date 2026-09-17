from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError, field_validator

from domsignal.services.errors import InvalidInitData

ALLOWED_FIELDS = {"auth_date", "chat", "hash", "ip", "query_id", "start_param", "user"}


class MaxUserData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictInt | StrictStr
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: int | str) -> int | str:
        if isinstance(value, int) and value <= 0:
            raise ValueError("numeric MAX user id must be positive")
        if isinstance(value, str) and (not value.strip() or len(value) > 200):
            raise ValueError("string MAX user id must be non-empty and bounded")
        return value

    @property
    def display_name(self) -> str:
        return " ".join(part for part in [self.first_name, self.last_name] if part)


def validate_init_data(
    raw: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: datetime | None = None,
) -> MaxUserData:
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InvalidInitData("Malformed initialization data") from exc
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise InvalidInitData("Duplicate initialization fields are forbidden")
    if set(keys) - ALLOWED_FIELDS:
        raise InvalidInitData("Unknown initialization fields are forbidden")
    values = dict(pairs)
    if not {"auth_date", "hash", "user"}.issubset(values):
        raise InvalidInitData("Required initialization fields are missing")
    supplied_hash = values["hash"]
    if len(supplied_hash) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in supplied_hash):
        raise InvalidInitData("Initialization signature has an invalid format")

    check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs) if key != "hash")
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied_hash.lower()):
        raise InvalidInitData("Initialization signature does not match")

    current = now or datetime.now(UTC)
    try:
        auth_timestamp = int(values["auth_date"])
        auth_date = datetime.fromtimestamp(auth_timestamp, tz=UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise InvalidInitData("auth_date is invalid") from exc
    age = (current - auth_date).total_seconds()
    if age < -30:
        raise InvalidInitData("Initialization data is from the future")
    if age > max_age_seconds:
        raise InvalidInitData("Initialization data has expired")

    try:
        user_payload: Any = json.loads(values["user"])
        return MaxUserData.model_validate(user_payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidInitData("MAX user payload is invalid") from exc
