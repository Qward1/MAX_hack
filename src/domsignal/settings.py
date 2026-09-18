from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppEnvironment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class MaxTransportMode(StrEnum):
    OFF = "off"
    RECORDING = "recording"
    WEBHOOK = "webhook"


class LlmProvider(StrEnum):
    RULES = "rules"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    app_env: AppEnvironment = AppEnvironment.LOCAL
    app_name: str = "ДомСигнал"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://domsignal:domsignal@localhost:5432/domsignal"
    session_secret: str = "local-only-change-me"
    session_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    init_data_max_age_seconds: int = Field(default=300, ge=30, le=3600)
    allow_test_session: bool = True
    demo_seed: bool = True
    max_transport: MaxTransportMode = MaxTransportMode.OFF
    max_bot_token: str | None = None
    max_webhook_secret: str | None = None
    llm_provider: LlmProvider = LlmProvider.RULES
    build_commit: str = "dev"
    public_base_url: str = "http://localhost:8000"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    static_dir: str = "miniapp/dist"

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use PostgreSQL with asyncpg")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def reject_unsafe_production(self) -> Settings:
        if self.app_env is not AppEnvironment.PRODUCTION:
            return self
        problems: list[str] = []
        if self.allow_test_session:
            problems.append("ALLOW_TEST_SESSION must be false")
        if self.demo_seed:
            problems.append("DEMO_SEED must be false")
        if self.session_secret in {"", "local-only-change-me", "change-me"}:
            problems.append("SESSION_SECRET must be replaced")
        if "domsignal:domsignal@" in self.database_url:
            problems.append("DATABASE_URL must not use demo credentials")
        if self.max_transport is MaxTransportMode.RECORDING:
            problems.append("MAX_TRANSPORT=recording is test-only")
        if self.max_transport is MaxTransportMode.WEBHOOK:
            if not self.max_bot_token:
                problems.append("MAX_BOT_TOKEN is required for webhook transport")
            if not self.max_webhook_secret:
                problems.append("MAX_WEBHOOK_SECRET is required for webhook transport")
        if urlparse(self.public_base_url).scheme != "https":
            problems.append("PUBLIC_BASE_URL must use https")
        if any(origin == "*" for origin in self.cors_origins):
            problems.append("wildcard CORS is forbidden")
        if problems:
            raise ValueError("unsafe production settings: " + "; ".join(problems))
        return self

    @property
    def test_session_enabled(self) -> bool:
        return self.allow_test_session and self.app_env in {
            AppEnvironment.LOCAL,
            AppEnvironment.TEST,
        }

    @property
    def replay_enabled(self) -> bool:
        return self.app_env in {AppEnvironment.LOCAL, AppEnvironment.TEST}


@lru_cache
def get_settings() -> Settings:
    return Settings()
