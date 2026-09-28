"""P7a: production Compose передаёт модель только AI-пулу и не ослабляет проверки.

Окружение сервиса собирается так же, как его собирает Compose: базовый файл,
поверх него production-оверлей, затем подстановка `${VAR:-default}` и
`${VAR:?message}` из файла окружения VPS. Значения синтетические.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from domsignal.ai.models import load_models
from domsignal.bootstrap import build_ai
from domsignal.main import create_app
from domsignal.settings import LlmProvider, Settings
from domsignal.worker.pools import lease_seconds_for

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ("migrate", "seed", "api", "worker", "ai-worker")
MODEL_ONLY = (
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_DAILY_CALL_BUDGET",
    "LLM_CHAT_DAILY_SHARE",
    "AI_WORKER_LEASE_SECONDS",
)
SYNTHETIC_VPS = {
    "PUBLIC_DOMAIN": "domsignal.example.ru",
    "POSTGRES_PASSWORD": "synthetic-postgres-password-1234",
    "SESSION_SECRET": "synthetic-production-session-secret-1234",
    "MAX_BOT_TOKEN": "synthetic-token",
    "MAX_WEBHOOK_SECRET": "synthetic_webhook_secret_1234567890",
    "AUTH_MFA_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "BUILD_COMMIT": "0" * 40,
}
MODEL = {
    "LLM_PROVIDER": "openai_compatible",
    "LLM_API_KEY": "synthetic-model-key",
    "LLM_MODEL": "Qwen/Qwen3-30B-A3B",
}
_REFERENCE = re.compile(r"\$\{(?P<name>[A-Z0-9_]+)(?:(?P<op>:-|:\?)(?P<arg>[^}]*))?\}")


def _load(name: str) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load((ROOT / name).read_text("utf-8"))
    return document


def _interpolate(value: object, env: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        current = env.get(match["name"], "")
        if match["op"] == ":?" and not current:
            raise KeyError(match["arg"])
        if match["op"] == ":-" and not current:
            return match["arg"]
        return current

    return _REFERENCE.sub(replace, str(value))


def environment(service: str, env: dict[str, str]) -> dict[str, str]:
    """Окружение контейнера после слияния файлов и подстановки."""
    merged: dict[str, object] = {}
    for name in ("compose.yaml", "compose.prod.yaml"):
        merged.update(_load(name)["services"][service].get("environment") or {})
    return {key: _interpolate(value, env) for key, value in merged.items()}


def settings_of(service: str, env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Настройки процесса ровно из его окружения, без переменных оболочки."""
    for name in (*MODEL_ONLY, "LLM_PROVIDER", "AI_POOL_LLM_PROVIDER", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    values = {key.lower(): value for key, value in environment(service, env).items()}
    return Settings(**values, static_dir="missing", _env_file=None)


def dotenv(path: Path) -> dict[str, str]:
    pairs = (
        line.split("=", 1)
        for line in path.read_text("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return {key.strip(): value.strip() for key, value in pairs}


def test_only_the_ai_worker_receives_model_variables() -> None:
    for service in BACKEND:
        env = environment(service, {**SYNTHETIC_VPS, **MODEL})
        if service == "ai-worker":
            assert env["LLM_PROVIDER"] == "openai_compatible"
            assert env["LLM_API_KEY"] == "synthetic-model-key"
            assert env["LLM_MODEL"] == "Qwen/Qwen3-30B-A3B"
            assert env["LLM_BASE_URL"] == "https://foundation-models.api.cloud.ru/v1"
            continue
        assert env["LLM_PROVIDER"] == "rules", service
        assert not set(MODEL_ONLY) & set(env), service


def test_without_model_variables_everything_stays_on_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = settings_of("ai-worker", SYNTHETIC_VPS, monkeypatch)
    assert worker.llm_provider is LlmProvider.RULES
    assert worker.llm_api_key is None and worker.llm_model is None
    # P6b: пусто — таймаут из профиля модели, а не явные 60 с.
    assert worker.llm_timeout_seconds is None
    assert worker.llm_daily_call_budget == 300
    assert worker.llm_chat_daily_share == 0.2
    assert worker.ai_worker_lease_seconds == 80
    # Аренда по умолчанию покрывает таймаут по умолчанию с запасом 20 с.
    assert (
        lease_seconds_for(
            "ai",
            ai_lease_seconds=worker.ai_worker_lease_seconds,
            model_timeout_seconds=worker.llm_timeout_seconds,
        )
        == 80
    )
    api = settings_of("api", SYNTHETIC_VPS, monkeypatch)
    assert api.ai_pool_llm_provider is LlmProvider.RULES
    assert not api.passive_capture_enabled
    # Окно не длиннее 6 реплик и модель в окнах чата — одинаково во всех
    # процессах, которые режут и разбирают окна (OWNER-DECISION-2026-09-24).
    for service in ("api", "worker", "ai-worker"):
        passive = settings_of(service, SYNTHETIC_VPS, monkeypatch)
        assert passive.passive_window_max_lines == 6
        assert passive.passive_llm_enabled


def test_the_model_timeout_comes_from_the_profile_unless_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = settings_of("ai-worker", {**SYNTHETIC_VPS, **MODEL}, monkeypatch)
    ai = build_ai(worker, None)  # type: ignore[arg-type]  # фабрика сессий не нужна
    profile = load_models().default
    assert profile is not None and profile.id == "Qwen/Qwen3-30B-A3B"
    assert ai.timeout_seconds == profile.timeout_seconds, "профиль Qwen3-30B-A3B (M1)"
    assert ai.provider is not None
    assert ai.provider.base_url == "https://foundation-models.api.cloud.ru/v1"
    assert ai.provider.open_danger_extra_body == {}
    assert ai.provider.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert ai.provider.price_rub_per_million == (13.908, 55.6076)
    assert ai.provider.max_tokens == 1600
    assert ai.provider.prompt_version == "window.v3"
    assert lease_seconds_for(
        "ai",
        ai_lease_seconds=worker.ai_worker_lease_seconds,
        model_timeout_seconds=profile.timeout_seconds,
    ) == 80
    explicit = settings_of(
        "ai-worker", {**SYNTHETIC_VPS, **MODEL, "LLM_TIMEOUT_SECONDS": "45"}, monkeypatch
    )
    assert build_ai(explicit, None).timeout_seconds == 45.0  # type: ignore[arg-type]


def test_model_configuration_reaches_the_ai_worker_and_the_lease_covers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        **SYNTHETIC_VPS,
        **MODEL,
        "LLM_TIMEOUT_SECONDS": "60",
        "LLM_DAILY_CALL_BUDGET": "300",
        "AI_WORKER_LEASE_SECONDS": "80",
        "PASSIVE_CAPTURE_ENABLED": "true",
        "PASSIVE_WINDOW_SILENCE_SECONDS": "30",
    }
    worker = settings_of("ai-worker", env, monkeypatch)
    assert worker.llm_provider is LlmProvider.OPENAI_COMPATIBLE
    assert worker.llm_api_key == "synthetic-model-key"
    assert worker.llm_model == "Qwen/Qwen3-30B-A3B"
    assert worker.llm_base_url == "https://foundation-models.api.cloud.ru/v1"
    assert "llm_timeout_seconds" in worker.model_fields_set
    assert (
        lease_seconds_for(
            "ai",
            ai_lease_seconds=worker.ai_worker_lease_seconds,
            model_timeout_seconds=worker.llm_timeout_seconds,
        )
        == 80
    )
    for service in ("api", "worker", "ai-worker"):
        passive = settings_of(service, env, monkeypatch)
        assert passive.passive_capture_enabled
        assert passive.passive_window_silence_seconds == 30


def test_the_api_advertises_the_model_without_holding_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = settings_of("api", {**SYNTHETIC_VPS, **MODEL}, monkeypatch)
    assert api.llm_provider is LlmProvider.RULES
    assert api.llm_api_key is None and api.llm_model is None
    assert api.ai_pool_llm_provider is LlmProvider.OPENAI_COMPATIBLE
    with TestClient(create_app(api)) as client:
        features = client.get("/api/v1/capabilities").json()["features"]
    assert features["ai_analysis"] is True
    assert features["passive_ai_analysis"] is True
    switched_off = settings_of(
        "api", {**SYNTHETIC_VPS, **MODEL, "PASSIVE_LLM_ENABLED": "false"}, monkeypatch
    )
    with TestClient(create_app(switched_off)) as client:
        features = client.get("/api/v1/capabilities").json()["features"]
    assert features["ai_analysis"] is True, "/report сохраняет модель"
    assert features["passive_ai_analysis"] is False, "окна чата — только правила"
    rules_only = settings_of("api", SYNTHETIC_VPS, monkeypatch)
    with TestClient(create_app(rules_only)) as client:
        features = client.get("/api/v1/capabilities").json()["features"]
    assert features["ai_analysis"] is False
    assert features["passive_ai_analysis"] is False


def test_the_model_provider_without_a_key_stops_the_ai_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {**SYNTHETIC_VPS, "LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "Qwen/Qwen3-30B-A3B"}
    with pytest.raises(ValidationError, match="LLM_API_KEY is required"):
        settings_of("ai-worker", env, monkeypatch)
    # Процессы без модели от этого не падают: у них правила.
    assert settings_of("api", env, monkeypatch).llm_provider is LlmProvider.RULES


def test_production_still_rejects_the_template_values(monkeypatch: pytest.MonkeyPatch) -> None:
    template = {**dotenv(ROOT / "deploy" / ".env.example"), "BUILD_COMMIT": "0" * 40}
    assert template["LLM_PROVIDER"] == "rules" and template["LLM_API_KEY"] == ""
    # Шаблонный ключ MFA — даже не ключ Fernet; с настоящим ключом остальные
    # шаблонные значения отвергает production-проверка.
    valid_key = {"AUTH_MFA_ENCRYPTION_KEY": SYNTHETIC_VPS["AUTH_MFA_ENCRYPTION_KEY"]}
    for service in ("api", "worker", "ai-worker"):
        with pytest.raises(ValidationError, match="AUTH_MFA_ENCRYPTION_KEY"):
            settings_of(service, template, monkeypatch)
        with pytest.raises(ValidationError, match="unsafe production settings") as rejected:
            settings_of(service, {**template, **valid_key}, monkeypatch)
        for name in ("SESSION_SECRET", "DATABASE_URL", "MAX_BOT_TOKEN", "PUBLIC_BASE_URL"):
            assert name in str(rejected.value)
    placeholder = {**SYNTHETIC_VPS, **MODEL, "LLM_API_KEY": "replace_with_provider_key"}
    with pytest.raises(ValidationError, match="placeholder"):
        settings_of("ai-worker", placeholder, monkeypatch)


def test_production_login_threshold_fits_a_jury_behind_one_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Финал: 30 попыток за 5 минут на логин и новых входов с адреса; локально — 10."""
    assert settings_of("api", SYNTHETIC_VPS, monkeypatch).auth_rate_threshold == 30
    custom = {**SYNTHETIC_VPS, "AUTH_RATE_THRESHOLD": "12"}
    assert settings_of("api", custom, monkeypatch).auth_rate_threshold == 12
    assert Settings.model_fields["auth_rate_threshold"].default == 10
