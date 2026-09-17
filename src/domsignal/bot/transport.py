from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class OutboundNotification:
    destination: str
    text: str


class MaxTransport(Protocol):
    async def send(self, notification: OutboundNotification) -> str | None: ...


class OffTransport:
    async def send(self, notification: OutboundNotification) -> str | None:
        del notification
        return None


@dataclass
class RecordingTransport:
    sent: list[OutboundNotification] = field(default_factory=list)

    async def send(self, notification: OutboundNotification) -> str:
        self.sent.append(notification)
        return f"recording:{len(self.sent)}"
