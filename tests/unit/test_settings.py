import pytest
from pydantic import ValidationError

from domsignal.db.session import create_engine
from domsignal.settings import PRODUCTION_MAX_BOT_USERNAME, AppEnvironment, Settings


@pytest.mark.parametrize(
    "url", ["sqlite:///local.db", "sqlite+aiosqlite:///:memory:", "mysql://db/app"]
)
def test_runtime_rejects_non_postgresql(url: str) -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(database_url=url, _env_file=None)
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_engine(url)


def test_local_defaults_use_safe_offline_providers() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.max_transport.value == "off"
    assert settings.llm_provider.value == "rules"
    assert settings.test_session_enabled


def test_production_rejects_local_bypass_and_default_secrets() -> None:
    with pytest.raises(ValidationError, match="unsafe production settings"):
        Settings(
            app_env="production",
            auth_mfa_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
            _env_file=None,
        )


def test_production_accepts_explicit_safe_baseline() -> None:
    settings = Settings(
        app_env="production",
        auth_mfa_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        database_url="postgresql+asyncpg://app:strong-password-123@db/domsignal",
        session_secret="a-production-secret-with-sufficient-entropy",
        allow_test_session=False,
        demo_seed=False,
        max_transport="webhook",
        max_bot_token="synthetic-token",
        max_webhook_secret="synthetic_webhook_secret_1234567890",
        max_bot_username=PRODUCTION_MAX_BOT_USERNAME,
        public_base_url="https://domsignal.example.ru",
        cors_origins=["https://domsignal.example.ru"],
        _env_file=None,
    )
    assert not settings.test_session_enabled


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"auth_mfa_encryption_key": None}, "AUTH_MFA_ENCRYPTION_KEY"),
        ({"auth_mfa_encryption_key": "invalid"}, "AUTH_MFA_ENCRYPTION_KEY"),
        ({"session_secret": "short"}, "SESSION_SECRET"),
        ({"max_transport": "off"}, "MAX_TRANSPORT"),
        ({"max_bot_token": ""}, "MAX_BOT_TOKEN"),
        ({"max_bot_token": "replace_with_issued_max_token"}, "MAX_BOT_TOKEN"),
        ({"max_webhook_secret": ""}, "MAX_WEBHOOK_SECRET"),
        ({"max_webhook_secret": "short_but_valid"}, "MAX_WEBHOOK_SECRET"),
        ({"max_webhook_secret": "replace_with_64_hex_characters"}, "MAX_WEBHOOK_SECRET"),
        ({"max_bot_username": "another_bot"}, "MAX_BOT_USERNAME"),
        ({"max_api_base_url": "https://example.invalid"}, "MAX_API_BASE_URL"),
        (
            {
                "database_url": (
                    "postgresql+asyncpg://app:replace_with_64_hex_characters@db/domsignal"
                )
            },
            "DATABASE_URL",
        ),
        ({"public_base_url": "https://domsignal.example.ru/path"}, "PUBLIC_BASE_URL"),
        (
            {
                "public_base_url": "https://bot.example.com",
                "cors_origins": ["https://bot.example.com"],
            },
            "PUBLIC_BASE_URL",
        ),
        ({"cors_origins": ["http://domsignal.example.ru"]}, "CORS_ORIGINS"),
    ],
)
def test_production_rejects_each_unsafe_live_override(
    override: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "app_env": "production",
        "auth_mfa_encryption_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "database_url": "postgresql+asyncpg://app:strong-password-123@db/domsignal",
        "session_secret": "a-production-secret-with-sufficient-entropy",
        "allow_test_session": False,
        "demo_seed": False,
        "max_transport": "webhook",
        "max_bot_token": "synthetic-token",
        "max_webhook_secret": "synthetic_webhook_secret_1234567890",
        "max_bot_username": PRODUCTION_MAX_BOT_USERNAME,
        "public_base_url": "https://domsignal.example.ru",
        "cors_origins": ["https://domsignal.example.ru"],
    }
    values.update(override)
    with pytest.raises(ValidationError, match=message):
        Settings(**values, _env_file=None)


@pytest.mark.parametrize("secret", ["four", "bad secret", "x" * 257])
def test_webhook_secret_matches_max_contract(secret: str) -> None:
    with pytest.raises(ValidationError, match="MAX_WEBHOOK_SECRET"):
        Settings(max_webhook_secret=secret, _env_file=None)
