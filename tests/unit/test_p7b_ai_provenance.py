"""P7b §1.4: у каждого `null` в учёте вызова модели есть причина."""

from __future__ import annotations

import pytest

from domsignal.ai.contracts import ExecutionInfo
from domsignal.services.ai_provenance import missing_reason


@pytest.mark.parametrize(
    ("state", "called", "value", "reason"),
    [
        ("ok", True, 0.23, None),
        ("ok", True, None, "not_reported_by_provider"),
        ("fallback_timeout", True, None, "timeout"),
        ("fallback_provider_error", True, None, "provider_error"),
        ("fallback_invalid_output", True, None, "not_reported_by_provider"),
        ("fallback_budget", False, None, "provider_not_called"),
        ("disabled", False, None, "provider_not_called"),
    ],
)
def test_missing_values_carry_a_reason(
    state: str, called: bool, value: float | None, reason: str | None
) -> None:
    execution = ExecutionInfo(state=state, provider_called=called, cost_rub=value)  # type: ignore[arg-type]
    assert missing_reason(execution, execution.cost_rub) == reason
