from fastapi.testclient import TestClient

from domsignal.main import create_app
from domsignal.settings import PRODUCTION_MAX_BOT_USERNAME, Settings


def production_settings() -> Settings:
    return Settings(
        app_env="production",
        auth_mfa_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        database_url="postgresql+asyncpg://app:strong-password-123@db/domsignal",
        session_secret="synthetic-production-session-secret-1234",
        allow_test_session=False,
        demo_seed=False,
        max_transport="webhook",
        max_bot_token="synthetic-token",
        max_webhook_secret="synthetic_webhook_secret_1234567890",
        max_bot_username=PRODUCTION_MAX_BOT_USERNAME,
        public_base_url="https://domsignal.example.ru",
        cors_origins=["https://domsignal.example.ru"],
        static_dir="missing",
        _env_file=None,
    )


def test_production_disables_test_auth_and_requires_webhook_secret_before_parsing() -> None:
    app = create_app(production_settings())
    with TestClient(app) as client:
        capabilities = client.get("/api/v1/capabilities")
        test_auth = client.post("/api/v1/auth/test-session", json={"actor": "demo"})
        denied = client.post("/max/webhook", json={})
        authenticated = client.post(
            "/max/webhook",
            json={},
            headers={"X-Max-Bot-Api-Secret": "synthetic_webhook_secret_1234567890"},
        )

    assert capabilities.status_code == 200
    features = capabilities.json()["features"]
    assert features["test_auth"] is False
    assert features["max_live"] is True
    assert features["group_mode"] is True
    assert features["admin"] is True
    assert test_auth.status_code == 503
    assert denied.status_code == 401
    assert authenticated.status_code == 422
