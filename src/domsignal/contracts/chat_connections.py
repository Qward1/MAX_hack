from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from domsignal.contracts.common import ContractModel
from domsignal.core.chat_connections import ConnectionStatus


class ConnectionCreate(ContractModel):
    scope_type: Literal["house", "entrance"] = "house"
    scope_value: str | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_scope(self) -> Self:
        if self.scope_type == "house" and self.scope_value is not None:
            raise ValueError("House scope has no value")
        if self.scope_type == "entrance" and not (self.scope_value or "").strip():
            raise ValueError("Entrance scope requires a value")
        return self


class ConnectionView(ContractModel):
    id: UUID
    house_id: UUID
    status: ConnectionStatus
    expires_at: datetime
    candidate_max_chat_id: str | None
    scope_type: Literal["house", "entrance"]
    scope_value: str | None
    last_error_code: str | None
    binding_id: UUID | None = None
    binding_version: int | None = None
    # Returned only on first creation, never persisted in receipts or outbox.
    correlation_token: str | None = None


class ConnectionApprove(ContractModel):
    confirm: Literal[True]


class BindingView(ContractModel):
    id: UUID
    max_chat_id: str
    house_id: UUID
    status: Literal["pending", "active", "suspended", "revoked"]
    binding_version: int
    scope_type: Literal["house", "entrance"]
    scope_value: str | None


class PassiveCaptureChange(ContractModel):
    """Включить или выключить чтение подключённого чата."""

    enabled: bool


class PassiveCaptureView(ContractModel):
    binding_id: UUID
    binding_version: int
    passive_capture_enabled: bool
    # Сообщение о чтении чата поставлено сейчас (один раз на версию привязки).
    notice_queued: bool


class GroupMessage(ContractModel):
    event_id: str
    chat_id: str
    external_user_id: str
    occurred_at: datetime
    text: str
    chat_binding_id: UUID
    binding_version: int
