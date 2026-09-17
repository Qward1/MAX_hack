"""Internal context resolved by MembershipService, never deserialized from client data.

C0 has house membership only. Unknown tenant/management cannot authorize a future
tenant operation. A-15/A-07 must resolve those scopes from active server relations.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from uuid import UUID

OperationSource = Literal["api", "max_replay"]


class ScopeState(StrEnum):
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    KNOWN = "known"


@dataclass(frozen=True)
class ScopeValue[T]:
    state: ScopeState = ScopeState.UNKNOWN
    value: T | None = None

    def __post_init__(self) -> None:
        if (self.state == ScopeState.KNOWN) != (self.value is not None):
            raise ValueError("Only KNOWN scope must have a value")


@dataclass(frozen=True)
class OperationContext:
    actor_user_id: UUID
    house_id: UUID
    source: OperationSource
    roles: frozenset[str]
    permissions: frozenset[str]
    tenant_id: ScopeValue[UUID] = field(default_factory=ScopeValue)
    management_id: ScopeValue[UUID] = field(default_factory=ScopeValue)
    chat_binding_id: ScopeValue[UUID] = field(
        default_factory=lambda: ScopeValue(ScopeState.NOT_APPLICABLE)
    )
    source_chat_id: ScopeValue[str] = field(
        default_factory=lambda: ScopeValue(ScopeState.NOT_APPLICABLE)
    )
    binding_version: ScopeValue[int] = field(
        default_factory=lambda: ScopeValue(ScopeState.NOT_APPLICABLE)
    )
