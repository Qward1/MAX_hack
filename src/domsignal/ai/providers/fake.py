"""Детерминированный провайдер для тестов и оценки: сети нет."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from domsignal.ai.providers.base import (
    ProviderInvalidOutput,
    ProviderRequest,
    ProviderResult,
    ProviderTimeout,
    ProviderUnavailable,
)

Scenario = Literal["ok", "timeout", "error", "invalid_json", "garbage"]

_GARBAGE = '{"messages": "нет", "signals": 5}'
_NOT_JSON = "{совсем не json"


class FakeProvider:
    """Провайдер с заданным ответом и воспроизводимыми отказами."""

    def __init__(
        self,
        scenario: Scenario = "ok",
        response: dict[str, Any] | str | None = None,
        *,
        delay_seconds: float = 0.0,
        exception: Exception | None = None,
        model: str = "fake/deterministic",
        prompt_version: str | None = None,
        cost_rub: float | None = None,
    ) -> None:
        self.scenario = scenario
        self.response = response
        self.delay_seconds = delay_seconds
        self.exception = exception
        self.model = model
        self.prompt_version = prompt_version
        self.cost_rub = cost_rub
        self.requests: list[ProviderRequest] = []

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.exception is not None:
            raise self.exception
        if self.scenario == "timeout":
            raise ProviderTimeout("fake timeout")
        if self.scenario == "error":
            raise ProviderUnavailable("fake provider error")
        return self._result(self._content(request))

    def _content(self, request: ProviderRequest) -> str:
        if self.scenario == "invalid_json":
            return _NOT_JSON
        if self.scenario == "garbage":
            return _GARBAGE
        if isinstance(self.response, str):
            return self.response
        if self.response is None:
            return json.dumps(self._silent(request), ensure_ascii=False)
        return json.dumps(self.response, ensure_ascii=False)

    def _result(self, content: str) -> ProviderResult:
        return ProviderResult(
            content=content,
            model=self.model,
            tokens_in=None,
            tokens_out=None,
            cost_rub=self.cost_rub,
            latency_ms=int(self.delay_seconds * 1000),
        )

    @staticmethod
    def _silent(request: ProviderRequest) -> dict[str, Any]:
        """Ответ «ничего не нашёл»: все реплики — болтовня, сигналов нет."""
        return {
            "messages": [
                {"id": line.id, "role": "chatter", "signals": []}
                for line in request.lines
                if not line.is_context
            ],
            "signals": [],
        }


def raise_invalid_output() -> None:
    """Помощник тестов: явный `ProviderInvalidOutput` от провайдера."""
    raise ProviderInvalidOutput("fake invalid output")
