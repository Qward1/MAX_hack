from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from domsignal.core.display_time import display_zone


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
    OPENAI_COMPATIBLE = "openai_compatible"


class LlmSchemaMode(StrEnum):
    """Форма структурированного ответа, подобранная для конкретной модели.

    Значения совпадают с `domsignal.ai.schema_modes.SchemaMode`; настройки
    намеренно не импортируют AI-пакет.
    """

    JSON_SCHEMA_STRICT = "json_schema_strict"
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"


MAX_API_ORIGIN = "https://platform-api2.max.ru"
LLM_BASE_URL = "https://polza.ai/api/v1"
PRODUCTION_MAX_BOT_USERNAME = "t480_hakaton_max_bot"
WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{5,256}$")


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
    max_bot_token: str | None = Field(default=None, repr=False)
    max_webhook_secret: str | None = Field(default=None, repr=False)
    max_api_base_url: str = MAX_API_ORIGIN
    max_api_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    max_bot_username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{1,100}$")
    max_required_permissions: frozenset[str] = frozenset({"read_all_messages"})
    chat_connection_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    llm_provider: LlmProvider = LlmProvider.RULES
    llm_base_url: str = LLM_BASE_URL
    llm_api_key: str | None = Field(default=None, repr=False)
    llm_model: str | None = None
    llm_schema_mode: LlmSchemaMode = LlmSchemaMode.JSON_SCHEMA_STRICT
    # Путь AI-пула не ждёт человек синхронно (целевая архитектура v3 §10).
    # Не задан — таймаут из профиля модели (`models.v1.yaml`); задан — перекрывает его.
    llm_timeout_seconds: float | None = Field(default=None, gt=0, le=60)
    llm_max_tokens: int = Field(default=1600, ge=256, le=8192)
    llm_max_concurrency: int = Field(default=4, ge=1, le=64)
    llm_daily_call_budget: int = Field(default=1000, ge=0)
    llm_chat_daily_share: float = Field(default=0.2, gt=0, le=1)
    # Провайдер AI-пула для процессов, которые модель не вызывают (api): они
    # объявляют возможность разбора, не получая ключа. Не задан — возможность
    # следует собственному `LLM_PROVIDER`, как в однопроцессном стенде.
    ai_pool_llm_provider: LlmProvider | None = None
    # Аренда задачи AI-пула: не меньше таймаута модели + 20 с, иначе второй
    # воркер перехватит задачу посреди вызова. Операционный пул — 30 с.
    ai_worker_lease_seconds: int = Field(default=60, ge=30, le=600)
    # Параллельные циклы «claim → обработка» в одном процессе пула (D5). Каждый
    # цикл открывает свои сессии БД; семафор провайдера (`LLM_MAX_CONCURRENCY`)
    # и дневной бюджет общие для процесса и для всех процессов соответственно.
    ai_worker_concurrency: int = Field(default=1, ge=1, le=32)
    operational_worker_concurrency: int = Field(default=1, ge=1, le=16)
    # Пул соединений SQLAlchemy на процесс: процессы × (размер + запас) ≤
    # max_connections PostgreSQL (docs/SCALING.md).
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    # Пассивное чтение подключённого чата (A-17/Product). Глобальный выключатель
    # по умолчанию выключен: без него реплики не сохраняются вовсе.
    passive_capture_enabled: bool = False
    # Модель в разборе окон чата (P6-DECISION): `false` — окна разбирают правила
    # без вызова модели и без бюджета; явный путь `/report` и форма не меняются.
    passive_llm_enabled: bool = True
    # Политика окна по умолчанию совпадает с `domsignal.ai.WindowPolicy`; на
    # показе стенд поднимается с короткой тишиной, 120 секунд там ждать нельзя.
    passive_window_silence_seconds: int = Field(default=120, ge=5, le=3600)
    # Окно ядра — не больше 40 реплик вместе с пятью репликами контекста.
    passive_window_max_lines: int = Field(default=10, ge=1, le=35)
    passive_window_max_age_seconds: int = Field(default=300, ge=10, le=86400)
    # Слабые сигналы сверх лимита на дом за сутки уходят в Audit Pool.
    passive_weak_daily_limit: int = Field(default=10, ge=0, le=1000)
    # Сколько суток открытый сигнал собирает ветку с тем же ключом.
    passive_dedupe_days: int = Field(default=7, ge=1, le=30)
    # Сырые реплики живут не дольше 72 часов независимо от состояния разбора.
    passive_buffer_hours: int = Field(default=72, ge=1, le=72)
    # Повтор сообщения об опасности того же вида в доме за это время
    # присоединяется к открытому критическому сигналу (решение владельца: 30).
    passive_danger_group_minutes: int = Field(default=30, ge=1, le=1440)
    # Памятка того же вида опасности в тот же чат не чаще, чем раз за это время.
    passive_chat_memo_pause_minutes: int = Field(default=30, ge=1, le=1440)
    # Сторож разбора окна: если AI-пул не разобрал окно за это время, окно
    # разбирают правила в операционном пуле.
    passive_analysis_fallback_seconds: int = Field(default=90, ge=5, le=3600)
    # Пояс по умолчанию для домов без профиля региона (D4: пояс дома — из пакета региона).
    display_timezone: str = "Europe/Moscow"
    # Контакт по вопросам данных на странице /privacy (D4); пусто — ссылка на /site.
    privacy_contact: str | None = Field(default=None, max_length=200)
    # Житель = участник домового чата (RESIDENT-BY-CHAT-2026-09-25). Если
    # активных привязок не больше этого числа, при входе проверяются все.
    resident_check_all_max_chats: int = Field(default=20, ge=0, le=200)
    # Один вызов MAX API на пару «пользователь, чат» не чаще, чем раз в N с.
    resident_check_interval_seconds: int = Field(default=900, ge=60, le=86400)
    # Срок членства по чату после проверки или события.
    resident_membership_ttl_seconds: int = Field(default=86400, ge=3600, le=604800)
    # Личный бот: сообщений о проблемах на пользователя за сутки.
    bot_daily_report_limit: int = Field(default=10, ge=1, le=100)
    # Сколько текст из лички ждёт выбора дома или ответа «та же проблема».
    bot_hold_seconds: int = Field(default=1800, ge=60, le=86400)
    # Сопровождение обращения (A-09, D3): через столько дней после отметки
    # «Я отправил» бот спрашивает в личке, пришёл ли ответ.
    appeal_followup_days: int = Field(default=14, ge=1, le=90)
    # Ежедневная сводка сотрудникам: час по Москве (D3).
    daily_digest_hour_msk: int = Field(default=9, ge=0, le=23)
    # Ночное окно личных рассылок жителям, МСК (D3): «22:00-08:00»; пусто —
    # без окна. Посты в чат следуют тихим часам своего чата.
    broadcast_dm_quiet_hours: str = Field(
        default="22:00-08:00", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$"
    )

    @property
    def broadcast_dm_quiet_window(self) -> tuple[int, int] | None:
        """Окно личных рассылок в минутах суток МСК или `None`."""
        if not self.broadcast_dm_quiet_hours:
            return None
        start, end = self.broadcast_dm_quiet_hours.split("-")
        return (
            int(start[:2]) * 60 + int(start[3:]),
            int(end[:2]) * 60 + int(end[3:]),
        )

    build_commit: str = "dev"
    public_base_url: str = "http://localhost:8000"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    static_dir: str = "miniapp/dist"
    regions_dir: str = "regions"
    auth_mfa_encryption_key: str | None = Field(default=None, repr=False)
    auth_password_max_length: int = Field(default=1024, ge=64, le=4096)
    employee_invitation_seconds: int = Field(default=172800, ge=300, le=604800)
    auth_session_idle_seconds: int = Field(default=1800, ge=60, le=86400)
    auth_session_absolute_seconds: int = Field(default=28800, ge=300, le=86400)
    auth_challenge_seconds: int = Field(default=600, ge=60, le=900)
    auth_temporary_password_seconds: int = Field(default=86400, ge=300, le=172800)
    auth_rate_threshold: int = Field(default=10, ge=2, le=100)
    auth_rate_window_seconds: int = Field(default=300, ge=30, le=3600)
    auth_rate_backoff_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, value: str) -> str:
        display_zone(value)  # неизвестный пояс — ошибка старта, а не UTC молча
        return value

    @field_validator("auth_mfa_encryption_key")
    @classmethod
    def validate_mfa_key(cls, value: str | None) -> str | None:
        if value is not None:
            from cryptography.fernet import Fernet

            try:
                Fernet(value.encode("ascii"))
            except (ValueError, UnicodeError) as exc:
                raise ValueError("AUTH_MFA_ENCRYPTION_KEY must be a Fernet key") from exc
        return value

    @field_validator(
        "max_bot_token",
        "max_bot_username",
        "max_webhook_secret",
        "llm_api_key",
        "llm_model",
        "llm_timeout_seconds",
        "ai_pool_llm_provider",
        mode="before",
    )
    @classmethod
    def empty_string_is_missing(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("llm_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        """Ключ уходит в заголовке, поэтому адрес провайдера — только HTTPS."""
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LLM_BASE_URL must be an HTTPS URL without credentials")
        return value.rstrip("/")

    @field_validator("max_webhook_secret")
    @classmethod
    def validate_webhook_secret(cls, value: str | None) -> str | None:
        if value is not None and not WEBHOOK_SECRET_PATTERN.fullmatch(value):
            raise ValueError(
                "MAX_WEBHOOK_SECRET must be 5-256 characters from A-Z, a-z, 0-9, _ or -"
            )
        return value

    @field_validator("max_api_base_url")
    @classmethod
    def validate_max_api_base(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("MAX API base must be an HTTPS origin without credentials")
        return value.rstrip("/")

    @field_validator("max_required_permissions")
    @classmethod
    def require_message_permission(cls, value: frozenset[str]) -> frozenset[str]:
        if "read_all_messages" not in value:
            raise ValueError("Group mode requires read_all_messages")
        return value

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

    @staticmethod
    def _is_origin(value: str, *, https_only: bool) -> bool:
        parsed = urlparse(value)
        return bool(
            parsed.scheme in ({"https"} if https_only else {"http", "https"})
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        )

    @model_validator(mode="after")
    def require_llm_credentials(self) -> Settings:
        """Внешний провайдер без ключа или модели — это молчаливый отказ AI.

        Требование одинаково для всех окружений: в production оно не
        смягчается, а дополняется проверкой на значение-заглушку.
        """
        if self.llm_provider is not LlmProvider.OPENAI_COMPATIBLE:
            return self
        problems: list[str] = []
        if not self.llm_api_key:
            problems.append("LLM_API_KEY is required")
        if not self.llm_model:
            problems.append("LLM_MODEL is required")
        if (
            self.app_env is AppEnvironment.PRODUCTION
            and self.llm_api_key
            and "replace" in self.llm_api_key.lower()
        ):
            problems.append("LLM_API_KEY must not be a placeholder in production")
        if problems:
            raise ValueError(
                "llm provider openai_compatible needs credentials: " + "; ".join(problems)
            )
        return self

    @model_validator(mode="after")
    def require_capacity_for_concurrency(self) -> Settings:
        """Циклов воркера не больше, чем соединений и мест в семафоре модели.

        Лишний цикл AI-пула не ускоряет разбор: он ждал бы семафор и уходил в
        правила (`fallback_overloaded`); цикл без соединения ждал бы пул БД.
        """
        problems: list[str] = []
        connections = self.db_pool_size + self.db_max_overflow
        for name, loops in (
            ("AI_WORKER_CONCURRENCY", self.ai_worker_concurrency),
            ("OPERATIONAL_WORKER_CONCURRENCY", self.operational_worker_concurrency),
        ):
            if loops + 1 > connections:
                problems.append(f"{name} + 1 must not exceed DB_POOL_SIZE + DB_MAX_OVERFLOW")
        if (
            self.llm_provider is LlmProvider.OPENAI_COMPATIBLE
            and self.ai_worker_concurrency > self.llm_max_concurrency
        ):
            problems.append("AI_WORKER_CONCURRENCY must not exceed LLM_MAX_CONCURRENCY")
        if problems:
            raise ValueError("worker concurrency: " + "; ".join(problems))
        return self

    @model_validator(mode="after")
    def reject_unsafe_production(self) -> Settings:
        if self.app_env is not AppEnvironment.PRODUCTION:
            return self
        problems: list[str] = []
        if not self.auth_mfa_encryption_key:
            problems.append("AUTH_MFA_ENCRYPTION_KEY is required")
        database = urlparse(self.database_url)
        session_secret_lower = self.session_secret.lower()
        if self.allow_test_session:
            problems.append("ALLOW_TEST_SESSION must be false")
        if self.demo_seed:
            problems.append("DEMO_SEED must be false")
        if (
            self.session_secret in {"", "local-only-change-me", "change-me"}
            or len(self.session_secret) < 32
            or len(set(self.session_secret)) < 8
            or "replace" in session_secret_lower
        ):
            problems.append("SESSION_SECRET must be a strong value of at least 32 characters")
        if (
            "domsignal:domsignal@" in self.database_url
            or not database.password
            or len(database.password) < 16
            or "replace" in database.password.lower()
        ):
            problems.append("DATABASE_URL must use non-placeholder production credentials")
        if self.max_transport is not MaxTransportMode.WEBHOOK:
            problems.append("MAX_TRANSPORT must be webhook in production")
        if not self.max_bot_token or "replace" in self.max_bot_token.lower():
            problems.append("MAX_BOT_TOKEN is required in production")
        if (
            not self.max_webhook_secret
            or len(self.max_webhook_secret) < 32
            or len(set(self.max_webhook_secret)) < 8
            or "replace" in self.max_webhook_secret.lower()
        ):
            problems.append("MAX_WEBHOOK_SECRET must be a strong value of at least 32 characters")
        if self.max_bot_username != PRODUCTION_MAX_BOT_USERNAME:
            problems.append(f"MAX_BOT_USERNAME must be {PRODUCTION_MAX_BOT_USERNAME} in production")
        if self.max_api_base_url != MAX_API_ORIGIN:
            problems.append(f"MAX_API_BASE_URL must be {MAX_API_ORIGIN} in production")
        if not self._is_origin(self.public_base_url, https_only=True):
            problems.append("PUBLIC_BASE_URL must be an HTTPS origin")
        else:
            public = urlparse(self.public_base_url)
            if public.port not in {None, 443}:
                problems.append("PUBLIC_BASE_URL must use the default HTTPS port")
            hostname = public.hostname or ""
            if hostname == "example.com" or hostname.endswith(".example.com"):
                problems.append("PUBLIC_BASE_URL must not use the template hostname")
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must not be empty")
        elif any(not self._is_origin(origin, https_only=True) for origin in self.cors_origins):
            problems.append("CORS_ORIGINS must contain only HTTPS origins")
        if self.public_base_url.rstrip("/") not in {
            origin.rstrip("/") for origin in self.cors_origins
        }:
            problems.append("CORS_ORIGINS must include PUBLIC_BASE_URL")
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
