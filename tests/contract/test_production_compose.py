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

from domsignal.main import create_app
from domsignal.settings import LlmProvider, Settings
from domsignal.worker.pools import lease_seconds_for

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ("migrate", "seed", "api", "worker", "ai-worker")
MODEL_ONLY = (
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
    "LLM_MODEL": "openai/gpt-5-mini",
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
            assert env["LLM_MODEL"] == "openai/gpt-5-mini"
            continue
        assert env["LLM_PROVIDER"] == "rules", service
        assert not set(MODEL_ONLY) & set(env), service


def test_without_model_variables_everything_stays_on_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = settings_of("ai-worker", SYNTHETIC_VPS, monkeypatch)
    assert worker.llm_provider is LlmProvider.RULES
    assert worker.llm_api_key is None and worker.llm_model is None
    assert worker.llm_timeout_seconds == 25
    assert worker.llm_daily_call_budget == 300
    assert worker.llm_chat_daily_share == 0.2
    assert worker.ai_worker_lease_seconds == 60
    api = settings_of("api", SYNTHETIC_VPS, monkeypatch)
    assert api.ai_pool_llm_provider is LlmProvider.RULES
    assert not api.passive_capture_enabled


def test_model_configuration_reaches_the_ai_worker_and_the_lease_covers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {
        **SYNTHETIC_VPS,
        **MODEL,
        "LLM_TIMEOUT_SECONDS": "25",
        "LLM_DAILY_CALL_BUDGET": "300",
        "AI_WORKER_LEASE_SECONDS": "60",
        "PASSIVE_CAPTURE_ENABLED": "true",
        "PASSIVE_WINDOW_SILENCE_SECONDS": "30",
    }
    worker = settings_of("ai-worker", env, monkeypatch)
    assert worker.llm_provider is LlmProvider.OPENAI_COMPATIBLE
    assert worker.llm_api_key == "synthetic-model-key"
    assert worker.llm_model == "openai/gpt-5-mini"
    assert "llm_timeout_seconds" in worker.model_fields_set
    assert (
        lease_seconds_for(
            "ai",
            ai_lease_seconds=worker.ai_worker_lease_seconds,
            model_timeout_seconds=worker.llm_timeout_seconds,
        )
        == 60
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
    rules_only = settings_of("api", SYNTHETIC_VPS, monkeypatch)
    with TestClient(create_app(rules_only)) as client:
        features = client.get("/api/v1/capabilities").json()["features"]
    assert features["ai_analysis"] is False


def test_the_model_provider_without_a_key_stops_the_ai_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {**SYNTHETIC_VPS, "LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "openai/gpt-5-mini"}
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
    placeholder = {**SYNTHETIC_VPS, **MODEL, "LLM_API_KEY": "replace_with_polza_key"}
    with pytest.raises(ValidationError, match="placeholder"):
        settings_of("ai-worker", placeholder, monkeypatch)
