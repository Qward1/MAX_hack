from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from domsignal.contracts.common import ContractModel, PageMeta
from domsignal.core.tickets import TicketAction, TicketEventKind, TicketStatus

DeadlineKind = Literal["response", "completion", "next_update"]
DeadlineBasis = Literal["internal", "agreed", "normative"]


class TicketCommand(ContractModel):
    expected_version: int = Field(ge=1)


class ReasonCommand(TicketCommand):
    reason: str = Field(min_length=3, max_length=2000, pattern=r"\S")


class AssignCommand(ReasonCommand):
    assignee_id: UUID | None


class WorkAttemptCreate(TicketCommand):
    public_description: str = Field(min_length=5, max_length=2000, pattern=r"\S")


class ObservationCreate(ContractModel):
    outcome: Literal["resolved", "unresolved"]
    comment: str | None = Field(default=None, max_length=2000)
    corrects_id: UUID | None = None


class DeadlineCreate(ReasonCommand):
    kind: DeadlineKind
    # Normative is intentionally unavailable until A-02 supplies verified applicability.
    basis: Literal["internal", "agreed"]
    start_event_id: UUID
    due_at: AwareDatetime | None
    agreement_reference: str | None = Field(default=None, min_length=3, max_length=500)
    agreed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def agreement_source(self) -> Self:
        if self.basis == "agreed" and (
            not self.agreement_reference
            or not self.agreement_reference.strip()
            or not self.agreed_at
        ):
            raise ValueError("An agreed deadline requires the agreement source and time")
        if self.basis == "internal" and (self.agreement_reference or self.agreed_at):
            raise ValueError("Internal estimates cannot claim an agreement")
        return self


class AttemptPublic(ContractModel):
    id: UUID
    number: int
    public_description: str
    rework_required: bool
    created_at: datetime


class AttemptView(AttemptPublic):
    ticket_id: UUID
    reported_by: UUID
    performed_by: UUID
    performer_name: str | None = None
    resolved_count: int = Field(default=0, ge=0)
    unresolved_count: int = Field(default=0, ge=0)


class OwnObservation(ContractModel):
    id: UUID
    attempt_id: UUID
    outcome: Literal["resolved", "unresolved"]
    comment: str | None
    revision: int
    corrects_id: UUID | None
    created_at: datetime


class ObservationView(OwnObservation):
    actor_id: UUID


class DeadlinePublic(ContractModel):
    kind: DeadlineKind
    basis: DeadlineBasis
    revision: int
    start_event_id: UUID
    started_at: datetime
    due_at: datetime | None
    rule_source: str | None
    rule_version: str | None
    agreement_recorded: bool


class DeadlineView(DeadlinePublic):
    id: UUID
    event_id: UUID
    agreement_reference: str | None
    agreed_at: datetime | None
    recorded_by: UUID
    reason: str
    created_at: datetime


class TicketView(ContractModel):
    id: UUID
    internal_number: str
    incident_id: UUID
    house_id: UUID
    management_id: UUID
    status: TicketStatus
    version: int
    assignee_id: UUID | None
    assignee_name: str | None = None
    accepted_by: UUID | None
    accepted_at: datetime | None
    requires_reassignment: bool
    routing_reason: str
    responsibility: Literal["not_verified"] = "not_verified"
    source: Literal["api", "max_replay", "max_group"]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    latest_attempt: AttemptView | None
    observation_conflict: bool
    deadlines: list[DeadlineView]
    allowed_actions: list[TicketAction]


class TicketList(ContractModel):
    items: list[TicketView]
    page: PageMeta


class TicketMutation(ContractModel):
    ticket: TicketView
    event_id: UUID
    effect_version: int
    attempt_id: UUID | None = None
    replayed: bool = False


class ResidentWorkStatus(ContractModel):
    """Explicit allowlist: never constructed by serializing a staff DTO."""

    incident_id: UUID
    ticket_id: UUID | None
    internal_number: str | None
    status: TicketStatus | None
    version: int | None
    created_at: datetime | None
    updated_at: datetime | None
    latest_attempt: AttemptPublic | None
    observation_conflict: bool
    my_latest_observation: OwnObservation | None
    deadlines: list[DeadlinePublic]
    allowed_actions: list[Literal["observe_result"]]


class ObservationRecorded(ContractModel):
    observation: OwnObservation
    target_attempt_id: UUID
    applied_to_current: bool
    state_changed: bool
    effect_version: int
    replayed: bool = False
    current: ResidentWorkStatus


class EventView(ContractModel):
    id: UUID
    actor_id: UUID
    kind: TicketEventKind
    version: int
    from_status: TicketStatus | None
    to_status: TicketStatus
    reason: str | None
    attempt_id: UUID | None
    observation_id: UUID | None
    assignee_id: UUID | None
    visibility: Literal["internal", "resident"]
    created_at: datetime


class EventList(ContractModel):
    items: list[EventView]
    page: PageMeta


class AttemptList(ContractModel):
    items: list[AttemptView]
    page: PageMeta


class ObservationList(ContractModel):
    items: list[ObservationView]
    page: PageMeta


class OwnObservationList(ContractModel):
    items: list[OwnObservation]
    page: PageMeta


class DeadlineList(ContractModel):
    items: list[DeadlineView]
    page: PageMeta


class AssigneeView(ContractModel):
    user_id: UUID
    display_name: str


class AssigneeList(ContractModel):
    items: list[AssigneeView]
    page: PageMeta


class TicketNotificationIntent(ContractModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    event_kind: TicketEventKind
    ticket_id: UUID
    incident_id: UUID
    attempt_id: UUID | None
    house_id: UUID
    management_id: UUID
    tenant_id: UUID
    ticket_version: int
    audience: Literal["staff", "participants"]
    chat_binding_id: UUID | None = None
    binding_version: int | None = None
