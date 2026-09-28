"""Адаптер OpenAI-совместимого API на записанных ответах: сети в тестах нет.

Каждый сценарий проверяется дважды: какое исключение поднимает сам адаптер и в
какое состояние `execution.state` его превращает фасад. Фасад не бросает
исключений ни в одном из сценариев.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from domsignal.ai import WindowAnalyzer
from domsignal.ai.providers.base import (
    ProviderInvalidOutput,
    ProviderTimeout,
    ProviderUnavailable,
    build_request,
)
from domsignal.ai.providers.openai_compatible import (
    OpenAICompatibleProvider,
    strip_code_fence,
)
from tests.ai.helpers import facets, model_response, model_signal, single, window

API_KEY = "test-key-not-a-real-secret"
MODEL = "openai/gpt-5-nano"

VALID_ANSWER = model_response(
    [
        model_signal(
            subtype="elevator.stopped",
            facets=facets("yes", "unclear", "yes", quote="лифт", msg="m1"),
        )
    ],
    roles={"m1": "new_problem"},
    refs={"m1": ["new:1"]},
)
OFF_SCHEMA_ANSWER = {"messages": "нет", "signals": {"ref": "new:1"}}


def completion(
    content: str,
    *,
    model: str = MODEL,
    prompt_tokens: int = 2480,
    completion_tokens: int = 174,
    cost_rub: float = 0.04131306,
) -> dict[str, Any]:
    """Записанный успешный ответ polza.ai (формат сверен с документацией 20.09.2026)."""
    return {
        "id": "gen_581761234567890123",
        "object": "chat.completion",
        "created": 1789502192,
        "model": model,
        "provider": "OpenAI",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_rub": cost_rub,
            "cost": cost_rub,
        },
    }


def provider_for(
    handler: Any, *, requests: list[httpx.Request] | None = None, **overrides: Any
) -> OpenAICompatibleProvider:
    def record(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    options: dict[str, Any] = {"api_key": API_KEY, "model": MODEL, "client": client}
    options.update(overrides)
    return OpenAICompatibleProvider(**options)


def replying(body: Any, status: int = 200) -> Any:
    def handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return handler


def failing(exception: Exception) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    return handler


# ------------------------------------------------------------------- успех


async def test_valid_answer_is_parsed_with_tokens_and_cost() -> None:
    provider = provider_for(replying(completion(json.dumps(VALID_ANSWER, ensure_ascii=False))))
    request, _mapping = build_request(single("Лифт не работает"))
    result = await provider.analyze_window(request)
    assert json.loads(result.content) == VALID_ANSWER
    assert result.model == MODEL
    assert (result.tokens_in, result.tokens_out) == (2480, 174)
    assert result.cost_rub == pytest.approx(0.04131306)
    assert result.latency_ms >= 0


def cloudru_completion(content: str) -> dict[str, Any]:
    """Записанный ответ Cloud.ru Foundation Models (27.09.2026): рублей в `usage` нет."""
    return {
        "id": "chatcmpl-96adf558e71327f26ed6c81d3a90ede6",
        "object": "chat.completion",
        "created": 1790530044,
        "model": "qwen3-30b-a3b",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 6124, "total_tokens": 6452, "completion_tokens": 328},
        "service_tier": "default",
    }


async def test_cost_comes_from_the_profile_price_when_the_provider_reports_none() -> None:
    """M1: Cloud.ru сообщает только токены — ₽ считаются по цене профиля модели."""
    body = cloudru_completion(json.dumps(VALID_ANSWER, ensure_ascii=False))
    request, _mapping = build_request(single("Лифт не работает"))
    priced = provider_for(replying(body), price_rub_per_million=(13.908, 55.6076))
    result = await priced.analyze_window(request)
    assert (result.tokens_in, result.tokens_out) == (6124, 328)
    expected = (6124 * 13.908 + 328 * 55.6076) / 1_000_000
    assert result.cost_rub == pytest.approx(expected, abs=1e-6)
    assert result.model == "qwen3-30b-a3b"
    # Без цены стоимость честно неизвестна, а не ноль.
    unpriced = await provider_for(replying(body)).analyze_window(request)
    assert unpriced.cost_rub is None


async def test_reported_cost_wins_over_the_profile_price() -> None:
    body = completion(json.dumps(VALID_ANSWER, ensure_ascii=False))
    request, _mapping = build_request(single("Лифт не работает"))
    provider = provider_for(replying(body), price_rub_per_million=(1000.0, 1000.0))
    result = await provider.analyze_window(request)
    assert result.cost_rub == pytest.approx(0.04131306)


async def test_facade_records_model_prompt_and_accounting() -> None:
    provider = provider_for(replying(completion(json.dumps(VALID_ANSWER, ensure_ascii=False))))
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.execution.state == "ok"
    assert analysis.mode == "model"
    assert analysis.execution.provider_model == MODEL
    assert analysis.execution.tokens_in == 2480
    assert analysis.execution.cost_rub == pytest.approx(0.04131306)
    assert analysis.versions.model == MODEL
    assert analysis.versions.prompt == "window.v3"


async def test_answer_wrapped_in_a_markdown_fence_is_accepted() -> None:
    fenced = f"```json\n{json.dumps(VALID_ANSWER, ensure_ascii=False)}\n```"
    provider = provider_for(replying(completion(fenced)))
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.execution.state == "ok"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ("```python\nprint(1)\n```", "```python\nprint(1)\n```"),
        ("```json без закрытия", "```json без закрытия"),
    ],
)
def test_only_the_code_fence_is_stripped(content: str, expected: str) -> None:
    assert strip_code_fence(content) == expected


# ------------------------------------------------------------------- отказы


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500, 502, 503])
async def test_http_errors_become_provider_unavailable(status: int) -> None:
    provider = provider_for(replying({"error": {"message": "нет"}}, status))
    request, _mapping = build_request(single("Лифт не работает"))
    with pytest.raises(ProviderUnavailable):
        await provider.analyze_window(request)
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    # F1: 429 — лимит запросов (ProviderRateLimited ⊂ ProviderUnavailable), своё состояние.
    expected = "fallback_rate_limited" if status == 429 else "fallback_provider_error"
    assert analysis.execution.state == expected
    assert analysis.mode == "rules"
    assert [signal.subtype for signal in analysis.signals] == ["elevator.stopped"]


async def test_timeout_becomes_provider_timeout() -> None:
    provider = provider_for(failing(httpx.ReadTimeout("slow")))
    request, _mapping = build_request(single("Лифт не работает"))
    with pytest.raises(ProviderTimeout):
        await provider.analyze_window(request)
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_timeout"


async def test_broken_connection_becomes_provider_unavailable() -> None:
    provider = provider_for(failing(httpx.ConnectError("connection reset")))
    request, _mapping = build_request(single("Лифт не работает"))
    with pytest.raises(ProviderUnavailable):
        await provider.analyze_window(request)
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_provider_error"


@pytest.mark.parametrize(
    "body",
    [
        completion(""),
        {"id": "gen_1", "choices": [], "usage": {}},
        {"id": "gen_1", "choices": [{"index": 0, "finish_reason": "error"}]},
        "не json вовсе",
    ],
)
async def test_empty_or_unreadable_response_is_invalid_output(body: Any) -> None:
    provider = provider_for(replying(body))
    request, _mapping = build_request(single("Лифт не работает"))
    with pytest.raises(ProviderInvalidOutput):
        await provider.analyze_window(request)
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_invalid_output"


@pytest.mark.parametrize(
    "content",
    ["{совсем не json", json.dumps(OFF_SCHEMA_ANSWER, ensure_ascii=False), "[]"],
)
async def test_answer_off_the_schema_falls_back_to_rules(content: str) -> None:
    provider = provider_for(replying(completion(content)))
    analysis = await WindowAnalyzer(provider).analyze(single("Лифт не работает"))
    assert analysis.execution.state == "fallback_invalid_output"
    assert analysis.mode == "rules"
    assert analysis.execution.provider_called


async def test_one_call_per_window_without_retries() -> None:
    requests: list[httpx.Request] = []
    provider = provider_for(replying({}, 500), requests=requests)
    await WindowAnalyzer(provider).analyze(window("лифт стоит", "у нас тоже"))
    assert len(requests) == 1


# ---------------------------------------------------------------- приватность


async def test_request_body_carries_only_masked_texts_and_aliases() -> None:
    requests: list[httpx.Request] = []
    provider = provider_for(
        replying(completion(json.dumps(VALID_ANSWER, ensure_ascii=False))), requests=requests
    )
    await WindowAnalyzer(provider).analyze(
        window("мой телефон 8 927 123 45 67, лифт стоит", "я из кв. 45, у нас тоже")
    )
    body = requests[0].content.decode("utf-8")
    assert "line-1" not in body and "line-2" not in body
    assert "resident-1" not in body and "resident-2" not in body
    assert "8 927 123 45 67" not in body
    assert "кв. 45" not in body
    assert any(
        marker in body
        for marker in ('\\"id\\": \\"m1\\"', '\\"id\\":\\"m1\\"', '"id": "m1"')
    )


async def test_open_item_refs_are_replaced_by_window_numbers() -> None:
    from domsignal.ai.contracts import OpenItem

    requests: list[httpx.Request] = []
    provider = provider_for(
        replying(completion(json.dumps(VALID_ANSWER, ensure_ascii=False))), requests=requests
    )
    item = OpenItem(
        ref="incident-7f3c",
        kind="incident",
        category="elevator",
        subtype="elevator.stopped",
        entrance="2",
        title="Лифт во 2 подъезде не работает",
    )
    await WindowAnalyzer(provider).analyze(window("лифт стоит", open_items=(item,)))
    body = requests[0].content.decode("utf-8")
    assert "incident-7f3c" not in body
    assert "open:1" in body


async def test_the_key_lives_only_in_the_header() -> None:
    requests: list[httpx.Request] = []
    provider = provider_for(
        replying(completion(json.dumps(VALID_ANSWER, ensure_ascii=False))), requests=requests
    )
    request, _mapping = build_request(single("Лифт не работает"))
    await provider.analyze_window(request)
    assert requests[0].headers["authorization"] == f"Bearer {API_KEY}"
    assert API_KEY not in requests[0].content.decode("utf-8")
    assert API_KEY not in repr(provider)


async def test_rejected_key_is_logged_once_and_without_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = provider_for(replying({"error": "unauthorized"}, 401))
    request, _mapping = build_request(single("Лифт не работает"))
    with caplog.at_level(logging.ERROR, logger="domsignal.ai.provider"):
        for _ in range(3):
            with pytest.raises(ProviderUnavailable):
                await provider.analyze_window(request)
    records = [record for record in caplog.records if record.message == "ai.provider.key_rejected"]
    assert len(records) == 1
    assert API_KEY not in caplog.text


# ------------------------------------------------------------------- запрос


def test_payload_follows_the_openai_contract_and_uses_no_plugins() -> None:
    provider = provider_for(replying(completion("{}")), max_tokens=900)
    request, _mapping = build_request(single("Лифт не работает"))
    payload = provider.build_payload(request)
    assert payload["model"] == MODEL
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 900
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert "plugins" not in payload
    assert "web_search_options" not in payload
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][-1]["role"] == "user"


def test_json_object_mode_sends_the_schema_inside_the_prompt() -> None:
    provider = provider_for(replying(completion("{}")), schema_mode="json_object")
    request, _mapping = build_request(single("Лифт не работает"))
    payload = provider.build_payload(request)
    assert payload["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in payload["messages"][0]["content"]


def test_model_specific_extras_reach_the_payload() -> None:
    provider = provider_for(
        replying(completion("{}")),
        temperature=None,
        extra_body={"reasoning": {"effort": "low"}},
    )
    request, _mapping = build_request(single("Лифт не работает"))
    payload = provider.build_payload(request)
    assert "temperature" not in payload
    assert payload["reasoning"] == {"effort": "low"}


def test_open_danger_windows_get_more_reasoning() -> None:
    """P6b, живой шаг 6: при открытом сигнале об опасности — reasoning low."""
    from domsignal.ai.contracts import OpenItem

    provider = provider_for(
        replying(completion("{}")),
        extra_body={"reasoning": {"effort": "minimal"}, "provider": {"order": ["openai/flex"]}},
        open_danger_extra_body={"reasoning": {"effort": "low"}},
    )
    gas = OpenItem(
        ref="signal-1",
        kind="signal",
        category="other",
        subtype="other.unspecified",
        entrance="2",
        title="запах газа",
        danger_kinds=("gas",),
    )
    quiet = gas.model_copy(update={"ref": "signal-2", "danger_kinds": ()})
    danger, _ = build_request(window("да, женщина стучит", open_items=(gas,)))
    calm, _ = build_request(window("лифт стоит", open_items=(quiet,)))
    alone, _ = build_request(single("Лифт не работает"))
    assert provider.build_payload(danger)["reasoning"] == {"effort": "low"}
    assert provider.build_payload(danger)["provider"] == {"order": ["openai/flex"]}
    assert provider.build_payload(calm)["reasoning"] == {"effort": "minimal"}
    assert provider.build_payload(alone)["reasoning"] == {"effort": "minimal"}


def test_open_danger_windows_get_a_larger_answer_limit_from_the_profile() -> None:
    """P6c: лимит ответа окна с открытой опасностью — из профиля, остальные прежние."""
    from domsignal.ai.contracts import OpenItem

    provider = provider_for(
        replying(completion("{}")),
        max_tokens=1600,
        open_danger_extra_body={"max_tokens": 2800},
    )
    gas = OpenItem(
        ref="signal-1", kind="signal", category="other", title="запах газа", danger_kinds=("gas",)
    )
    danger, _ = build_request(window("да, женщина стучит", open_items=(gas,)))
    alone, _ = build_request(single("Лифт не работает"))
    assert provider.build_payload(danger)["max_tokens"] == 2800
    assert provider.build_payload(alone)["max_tokens"] == 1600


def test_shipped_profile_sends_the_same_body_with_and_without_open_danger() -> None:
    """M1: у Qwen3-30B-A3B добавки для открытой опасности нет, рассуждения выключены."""
    from domsignal.ai.contracts import OpenItem
    from domsignal.ai.models import load_models

    profile = load_models().default
    assert profile is not None
    provider = provider_for(
        replying(completion("{}")),
        model=profile.id,
        max_tokens=profile.max_tokens,
        temperature=profile.temperature,
        extra_body=profile.extra_body,
        open_danger_extra_body=profile.open_danger_extra_body,
    )
    gas = OpenItem(
        ref="signal-1", kind="signal", category="other", title="запах газа", danger_kinds=("gas",)
    )
    danger, _ = build_request(window("да, женщина стучит", open_items=(gas,)))
    alone, _ = build_request(single("Лифт не работает"))
    for request in (danger, alone):
        payload = provider.build_payload(request)
        assert payload["max_tokens"] == 1600
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert "reasoning" not in payload and "provider" not in payload


def test_provider_refuses_to_start_without_a_key_or_model() -> None:
    with pytest.raises(ValueError, match="api key"):
        OpenAICompatibleProvider(api_key="", model=MODEL)
    with pytest.raises(ValueError, match="model"):
        OpenAICompatibleProvider(api_key=API_KEY, model="")
