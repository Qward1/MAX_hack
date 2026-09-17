import pytest
from pydantic import ValidationError

from domsignal.settings import AppEnvironment, Settings


def test_local_defaults_use_safe_offline_providers() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env is AppEnvironment.LOCAL
    assert settings.max_transport.value == "off"
    assert settings.llm_provider.value == "rules"
    assert settings.test_session_enabled


def test_production_rejects_local_bypass_and_default_secrets() -> None:
    with pytest.raises(ValidationError, match="unsafe production settings"):
        Settings(app_env="production", _env_file=None)


def test_production_accepts_explicit_safe_baseline() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql+asyncpg://app:strong-password@db/domsignal",
        session_secret="a-production-secret-with-sufficient-entropy",
        allow_test_session=False,
        demo_seed=False,
        public_base_url="https://domsignal.example",
        cors_origins=["https://domsignal.example"],
        _env_file=None,
    )
    assert not settings.test_session_enabled
