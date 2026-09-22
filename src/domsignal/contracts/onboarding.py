from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from domsignal.contracts.chat_connections import ConnectionView
from domsignal.contracts.common import ContractModel

Role = Literal["operator", "company_admin"]
ReviewStatus = Literal[
    "submitted", "under_review", "needs_info", "approved", "rejected", "cancelled"
]
Surface = Literal[
    "overview",
    "tickets",
    "signals",
    "assigned_houses",
    "houses",
    "staff",
    "chat_connections",
    "organization",
]
Plain = Annotated[str, Field(min_length=1, max_length=2000)]


class PlainInput(ContractModel):
    @field_validator("*", mode="before")
    @classmethod
    def plain_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if any(c in value for c in "<>") or any(
                ord(c) < 32 and c not in "\n\r\t" for c in value
            ):
                raise ValueError("Plain text required")
        return value


class CompanyApplicationCreate(PlainInput):
    legal_name: str = Field(min_length=2, max_length=300)
    short_name: str = Field(min_length=2, max_length=200)
    inn: str = Field(pattern=r"^(?:[0-9]{10}|[0-9]{12})$")
    contact_name: str = Field(min_length=2, max_length=200)
    contact_email: str | None = Field(default=None, max_length=254)
    contact_phone: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def contact(self) -> Self:
        if not self.contact_email and not self.contact_phone:
            raise ValueError("Phone or email required")
        if self.contact_email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.contact_email):
            raise ValueError("Invalid email syntax")
        if self.contact_phone and not re.fullmatch(r"[+0-9() .-]{5,40}", self.contact_phone):
            raise ValueError("Invalid phone syntax")
        return self


class ApplicationReceived(ContractModel):
    received: Literal[True] = True
    message: str = "Данные получены. Для уточнений с вами свяжутся вручную."


class ReviewDecision(PlainInput):
    reason: Plain


class CompanyContext(ContractModel):
    company_id: UUID
    name: str
    surfaces: list[Surface]


class AdminBootstrap(ContractModel):
    user_id: UUID
    display_name: str
    companies: list[CompanyContext]


class PlatformBootstrap(ContractModel):
    display_name: str
    surfaces: list[str]


class AuditView(ContractModel):
    event: str
    occurred_at: datetime
    actor_id: str | None = None
    object_id: str | None = None
    reason: str | None = None


class ApplicationView(ContractModel):
    id: UUID
    legal_name: str
    short_name: str
    inn: str
    contact_name: str
    contact_email: str | None
    contact_phone: str | None
    comment: str | None
    status: ReviewStatus
    submitted_at: datetime
    reviewed_at: datetime | None
    decision_reason: str | None
    company_id: UUID | None
    history: list[AuditView] = Field(default_factory=list)


class InvitationCreate(ContractModel):
    organization_role: Role


class InvitationView(ContractModel):
    id: UUID
    company_id: UUID
    organization_role: Role
    status: Literal["pending", "claimed", "accepted", "expired", "revoked"]
    expires_at: datetime
    created_at: datetime
    claimed_by_user_id: UUID | None
    invitation_url: str | None = None


class CompanyApproved(ContractModel):
    application: ApplicationView
    invitation: InvitationView


class InvitationToken(ContractModel):
    token: str = Field(min_length=32, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")


class InvitationRegister(InvitationToken):
    display_name: str = Field(min_length=2, max_length=200, pattern=r"^[^<>]+$")
    login_name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=1024)


class InvitationPreview(ContractModel):
    company_name: str
    organization_role: Role
    expires_at: datetime


class MembershipView(ContractModel):
    user_id: UUID
    display_name: str
    role: Role
    status: str


class AssignmentView(ContractModel):
    management_id: UUID
    role: Literal["operator", "responsible"]


class StaffDetail(MembershipView):
    assignments: list[AssignmentView]


class AssignmentChange(ContractModel):
    management_id: UUID
    role: Literal["operator", "responsible"] | None


class HouseRequestCreate(PlainInput):
    requested_address: str = Field(min_length=5, max_length=500)
    requested_valid_from: AwareDatetime
    basis_text: Plain


class HouseRequestView(ContractModel):
    id: UUID
    company_id: UUID
    requested_address: str
    requested_valid_from: datetime
    basis_text: str
    candidate_house_id: UUID | None
    status: ReviewStatus
    reviewed_at: datetime | None
    decision_reason: str | None
    created_at: datetime
    management_id: UUID | None
    history: list[AuditView] = Field(default_factory=list)


class HouseApproval(ReviewDecision):
    resolution: Literal["existing", "new"]
    house_id: UUID | None = None
    valid_from: AwareDatetime
    confirm_backdate: bool = False

    @model_validator(mode="after")
    def explicit_identity(self) -> Self:
        if (self.resolution == "existing") != (self.house_id is not None):
            raise ValueError("Choose an explicit existing house or create a new house")
        return self


class ChatSummary(ContractModel):
    id: UUID
    title: str | None
    max_chat_id: str
    status: str
    scope_type: str
    scope_value: str | None
    suspension_reason: str | None
    # Чтение чата включено у привязки. `None` — поверхность этого не сообщает.
    passive_capture_enabled: bool | None = None


class CompanyHouseView(ContractModel):
    house_id: UUID
    management_id: UUID
    address: str
    name: str
    valid_from: datetime
    valid_to: datetime | None
    operator_count: int
    responsible_count: int
    open_ticket_count: int
    bindings: list[ChatSummary]
    connection_requests: list[ConnectionView]
    warning: str | None = None


class CompanyView(ContractModel):
    id: UUID
    name: str
    legal_name: str | None
    inn: str | None
    status: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    house_count: int = 0
    employee_count: int = 0
    binding_problems: int = 0


class CompanyOverview(ContractModel):
    open_tickets: int
    unassigned_tickets: int
    verification_pending: int
    house_count: int
    active_employees: int
    binding_problems: int


class PlatformHouseView(ContractModel):
    id: UUID
    address: str
    name: str


class PlatformBindingView(ChatSummary):
    house_id: UUID
    management_id: UUID
    company_id: UUID


class PlatformHealth(ContractModel):
    database: Literal["ready"]
    pending_jobs: int
    failed_jobs: int
    pending_deliveries: int
