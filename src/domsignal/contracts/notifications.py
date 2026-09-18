from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationLaunch(BaseModel):
    incident_id: UUID
    house_id: UUID
    work_attempt_id: UUID | None
    stale: bool


class TicketCallback(BaseModel):
    event_id: str
    callback_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    launch_ref: str = Field(pattern=r"^w_[A-Za-z0-9_-]{32}$")
    outcome: Literal["resolved", "unresolved"]
