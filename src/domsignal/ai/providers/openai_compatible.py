"""Адаптер OpenAI-совместимого API (polza.ai) за протоколом `AnalysisProvider`.

Один вызов на окно, `temperature: 0`, ограниченный `max_tokens`, никаких
повторов: отказ — это результат, и ядро отвечает результатом правил. Плагины
агрегатора (`web`, `response-healing`, `file-parser`) не используются: у нас
своя валидация и нет выхода в интернет из разбора.

Модуль **не импортирует** `domsignal.settings`: все параметры приходят в
конструктор. Продукт собирает провайдера из настроек в своей проводке.

Сверено с документацией polza.ai 20.09.2026:
`POST https://polza.ai/api/v1/chat/completions`, заголовок
`Authorization: Bearer <ключ>`, модель вида `provider/name`,
`response_format` в формах `json_schema` (с `strict`) и `json_object`,
`usage.prompt_tokens`, `usage.completion_tokens` и `usage.cost_rub` (рубли,
фактически списанная сумма). Коды ошибок: 400, 401, 402, 403, 404, 408, 429,
500, 502, 503.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any, cast

import httpx

from domsignal.ai.prompts import PROMPT_VERSION, build_messages, prompt_spec
from domsignal.ai.providers.base import (
    ProviderInvalidOutput,
    ProviderRequest,
    ProviderResult,
    ProviderTimeout,
    ProviderUnavailable,
)
from domsignal.ai.schema_modes import SchemaMode, response_format
from domsignal.ai.taxonomy import Taxonomy

logger = logging.getLogger("domsignal.ai.provider")

#: Базовый адрес API polza.ai по документации на 20.09.2026.
DEFAULT_BASE_URL = "https://polza.ai/api/v1"
DEFAULT_MAX_TOKENS = 1600
DEFAULT_TIMEOUT_SECONDS = 10.0

_FENCE = "```"


class OpenAICompatibleProvider:
    """Провайдер разбора окна через OpenAI-совместимый `/chat/completions`."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str,
        model: str,
        schema_mode: SchemaMode = "json_schema_strict",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = 0.0,
        taxonomy: Taxonomy | None = None,
        few_shot: bool = True,
        extra_body: Mapping[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        if not api_key:
            raise ValueError("api key is required")
        if not model:
            raise ValueError("model is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.schema_mode = schema_mode
        self.timeout_seconds = timeout_seconds
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.few_shot = few_shot
        self.prompt_version = prompt_spec(prompt_version).version
        self.extra_body = dict(extra_body or {})
        self._api_key = api_key
        self._taxonomy = taxonomy
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._key_rejected_logged = False

    # ------------------------------------------------------------------ жизнь

    def __repr__(self) -> str:
        """Ключ не попадает в `repr`: его легко утащить в лог трассировкой."""
        return (
            f"OpenAICompatibleProvider(base_url={self.base_url!r}, model={self.model!r}, "
            f"schema_mode={self.schema_mode!r})"
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> OpenAICompatibleProvider:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ вызов

    def build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        """Тело запроса. Отдельный метод, чтобы его можно было проверить тестом."""
        spec = prompt_spec(self.prompt_version)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": build_messages(
                request,
                self._taxonomy,
                mode=self.schema_mode,
                few_shot=self.few_shot,
                version=spec.version,
            ),
            "max_tokens": self.max_tokens,
            "response_format": response_format(
                self.schema_mode, self._taxonomy, compact=spec.compact
            ),
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        payload.update(self.extra_body)
        return payload

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        """Один вызов модели на окно. Повторов нет: отказ отдаётся ядру как есть."""
        started = time.perf_counter()
        try:
            response = await self._client.post(
                f"{self.base_url}/chat/completions",
                json=self.build_payload(request),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("llm request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"llm transport error: {type(exc).__name__}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._raise_for_status(response)
        return self._parse(response, latency_ms)

    # ---------------------------------------------------------------- разбор

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in (401, 403):
            if not self._key_rejected_logged:
                self._key_rejected_logged = True
                logger.error(
                    "ai.provider.key_rejected",
                    extra={"ai_provider_status": status, "ai_model": self.model},
                )
            raise ProviderUnavailable(f"llm rejected the key: HTTP {status}")
        raise ProviderUnavailable(f"llm responded HTTP {status}")

    def _parse(self, response: httpx.Response, latency_ms: int) -> ProviderResult:
        try:
            body = cast(dict[str, Any], response.json())
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderInvalidOutput("llm response is not JSON") from exc
        if not isinstance(body, dict):
            raise ProviderInvalidOutput("llm response is not an object")
        content = _content_of(body)
        if not content:
            raise ProviderInvalidOutput("llm returned an empty message")
        usage = body.get("usage")
        usage_map = cast(dict[str, Any], usage) if isinstance(usage, dict) else {}
        return ProviderResult(
            content=content,
            model=str(body.get("model") or self.model),
            tokens_in=_as_int(usage_map.get("prompt_tokens")),
            tokens_out=_as_int(usage_map.get("completion_tokens")),
            cost_rub=_as_float(usage_map.get("cost_rub", usage_map.get("cost"))),
            latency_ms=latency_ms,
        )


def _content_of(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderInvalidOutput("llm response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderInvalidOutput("llm choice is not an object")
    message = cast(dict[str, Any], first).get("message")
    if not isinstance(message, dict):
        raise ProviderInvalidOutput("llm choice has no message")
    content = cast(dict[str, Any], message).get("content")
    if content is None:
        return ""
    if not isinstance(content, str):
        raise ProviderInvalidOutput("llm message content is not a string")
    return strip_code_fence(content)


def strip_code_fence(content: str) -> str:
    """Снять обёртку ```json … ```; всё остальное остаётся строгим JSON.

    Некоторые модели оборачивают структурированный ответ в блок markdown даже
    в режиме схемы. Это единственная допустимая правка ответа: ни «починки»
    кавычек, ни выдёргивания JSON из текста здесь нет.
    """
    text = content.strip()
    if not text.startswith(_FENCE):
        return text
    body = text[len(_FENCE) :]
    newline = body.find("\n")
    if newline == -1:
        return text
    language = body[:newline].strip().lower()
    if language not in ("", "json"):
        return text
    rest = body[newline + 1 :]
    end = rest.rfind(_FENCE)
    if end == -1:
        return text
    return rest[:end].strip()


def _as_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
