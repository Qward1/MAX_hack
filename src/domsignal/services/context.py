"""Internal context resolved by MembershipService, never deserialized from client data.

Tenant/management and access bases come from current persisted relations.
Chat scopes remain NOT_APPLICABLE until the separate connection slice.
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
    organization_role: str | None = None
    house_assignment_role: str | None = None
    resident_membership_id: UUID | None = None

    @property
    def resident_access(self) -> bool:
        return self.resident_membership_id is not None

    chat_binding_id: ScopeValue[UUID] = field(
        default_factory=lambda: ScopeValue(ScopeState.NOT_APPLICABLE)
    )
    source_chat_id: ScopeValue[str] = field(
        default_factory=lambda: ScopeValue(ScopeState.NOT_APPLICABLE)
    )
    binding_version: ScopeValue[int] = field(
        default_factory=lambda: ScopeValue(ScopeState.NOT_APPLICABLE)
    )
