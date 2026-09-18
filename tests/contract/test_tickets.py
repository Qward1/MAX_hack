from uuid import uuid4

import pytest
from pydantic import ValidationError

from domsignal.contracts.tickets import DeadlineCreate, ObservationCreate, ResidentWorkStatus
from domsignal.main import create_app
from domsignal.settings import Settings


def test_ticket_contract_commands_errors_and_headers() -> None:
    schema = create_app(Settings(_env_file=None)).openapi()
    for path, commands in schema["paths"].items():
        if not any(s in path for s in ("/tickets", "/work-attempts", "/work-status")):
            continue
        for method, operation in commands.items():
            assert operation["security"] == [{"HTTPBearer": []}]
            if method == "post":
                key = next(p for p in operation["parameters"] if p["name"] == "Idempotency-Key")
                assert key["required"] and key["in"] == "header"
            for code in ("401", "403", "404", "409", "422", "500"):
                response = operation["responses"][code]
                assert "application/problem+json" in response["content"]
                assert "X-Request-ID" in response["headers"]
    assert "post" not in schema["paths"]["/api/v1/tickets"]
    assert "patch" not in schema["paths"]["/api/v1/tickets/{ticket_id}"]
    assert "work_reported" not in schema["components"]["schemas"]["TicketStatus"]["enum"]


def test_resident_schema_is_independent_and_observation_has_no_client_clock() -> None:
    assert not {"assignee_id", "accepted_by", "management_id", "tenant_id", "events"} & (
        ResidentWorkStatus.model_fields.keys()
    )
    for field in ("actor_id", "tenant_id", "role", "version", "created_at"):
        with pytest.raises(ValidationError):
            ObservationCreate.model_validate({"outcome": "resolved", field: "untrusted"})
    with pytest.raises(ValidationError):
        DeadlineCreate(
            expected_version=1,
            reason="A valid reason",
            kind="completion",
            basis="normative",
            start_event_id=uuid4(),
            due_at=None,
        )
