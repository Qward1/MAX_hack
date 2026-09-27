from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationLaunch(BaseModel):
    """Куда открыть mini app по ссылке из личного сообщения.

    `kind` различает два предмета доставки. У карточки маршрута заявки может не
    быть вовсе (внешнее обращение житель отправляет сам), поэтому `incident_id`
    допускает пустое значение. Проверки доступа одинаковы для обоих префиксов:
    получатель доставки, членство в доме и актуальные права.
    """

    #: `house` — кнопка «Открыть ДомСигнал» в домовом чате (D-01): mini app
    #: открывается на доме этого чата, а не на первом доме по алфавиту.
    kind: Literal["ticket", "route_card", "poll", "announcements", "house"] = "ticket"
    incident_id: UUID | None = None
    house_id: UUID
    route_outcome_id: UUID | None = None
    #: Опрос из поста или личного сообщения рассылки (D3).
    poll_id: UUID | None = None
    work_attempt_id: UUID | None
    stale: bool


class TicketCallback(BaseModel):
    event_id: str
    callback_id: str = Field(min_length=1, max_length=200)
    actor: str = Field(min_length=1, max_length=200)
    message_id: str = Field(min_length=1, max_length=200)
    launch_ref: str = Field(pattern=r"^w_[A-Za-z0-9_-]{32}$")
    outcome: Literal["resolved", "unresolved"]
