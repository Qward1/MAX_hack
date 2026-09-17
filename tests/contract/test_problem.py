from uuid import UUID

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from domsignal.main import create_app
from domsignal.settings import Settings


def test_problem_runtime_matches_openapi_and_never_echoes_input() -> None:
    app = create_app(Settings(static_dir="missing", _env_file=None))

    @app.get("/test-error", include_in_schema=False)
    async def fail() -> None:
        raise RuntimeError("secret SQL internal stack")

    schema = app.openapi()
    for path in schema["paths"].values():
        for operation in path.values():
            for status, response in operation["responses"].items():
                if int(status) >= 400:
                    assert set(response["content"]) == {"application/problem+json"}
    validator = Draft202012Validator(
        {"$ref": "#/components/schemas/Problem", "components": schema["components"]}
    )
    secret = "secret-initData-and-token"
    with TestClient(app, raise_server_exceptions=False) as client:
        responses = [
            client.get("/api/v1/me", headers={"X-Request-ID": secret}),
            client.post("/api/v1/auth/max", json={"init_data": {"secret": secret}}),
            client.post("/api/v1/auth/max", json={"init_data": "x", secret: secret}),
            client.get("/not-found"),
            client.get("/api/v1/reports"),
            client.post("/max/webhook"),
            client.get("/test-error"),
        ]
    assert [r.status_code for r in responses] == [401, 422, 422, 404, 405, 503, 500]
    for response in responses:
        body = response.json()
        validator.validate(body)
        assert response.headers["content-type"] == "application/problem+json"
        assert body["trace_id"] == response.headers["X-Request-ID"]
        UUID(body["trace_id"])
        assert secret not in response.text and "SQL" not in response.text
        assert "request_id" not in body and "errors" not in body
        assert body["retryable"] == (response.status_code == 500)
        if response.status_code == 422:
            assert body["field_errors"]
            assert all(set(error) == {"field", "code", "message"} for error in body["field_errors"])
