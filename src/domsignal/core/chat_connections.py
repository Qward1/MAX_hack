"""Connection lifecycle; all application transitions use these functions."""

from enum import StrEnum


class ConnectionStatus(StrEnum):
    CREATED = "created"
    CONNECTOR_CLAIMED = "connector_claimed"
    CHAT_DETECTED = "chat_detected"
    MAX_VERIFIED = "max_verified"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


TERMINAL = {"completed", "expired", "cancelled", "rejected"}
TRANSITIONS = {
    "created": {"connector_claimed"},
    "connector_claimed": {"chat_detected"},
    "chat_detected": {"max_verified"},
    "max_verified": {"awaiting_approval", "completed"},
    "awaiting_approval": {"completed"},
}


def connection_transition(current: str, target: str) -> str:
    if current == target:
        return current
    allowed = TRANSITIONS.get(current, set())
    if current not in TERMINAL:
        allowed = allowed | {"expired", "cancelled", "rejected"}
    if target not in allowed:
        raise ValueError("Invalid connection transition")
    return target


def binding_transition(current: str, target: str) -> str:
    if current == target:
        return current
    # Reactivation always uses a new request and binding, retaining the old history.
    if target not in {
        "pending": {"active", "revoked"},
        "active": {"suspended", "revoked"},
        "suspended": {"revoked"},
        "revoked": set(),
    }.get(current, set()):
        raise ValueError("Invalid binding transition")
    return target
