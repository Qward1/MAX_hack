"""Фасад анализа окна: `WindowAnalyzer` никогда не бросает исключений.

Правила выполняются всегда и первыми. Модель может уточнить результат, но её
отказ, таймаут или неразбираемый ответ оставляют продукту честный результат
правил, а не выдуманный ответ.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from pydantic import ValidationError

from domsignal.ai.contracts import (
    AnalysisMode,
    ExecutionInfo,
    ExecutionState,
    SignalDraft,
    Versions,
    WindowAnalysis,
    WindowInput,
)
from domsignal.ai.engine import (
    DEFAULT_AUDIT_RATE,
    apply_audit_sample,
    input_sha256,
    subtype_from_danger,
)
from domsignal.ai.fallback import RulesOutcome, analyze_with_rules
from domsignal.ai.model_output import SCHEMA_ID, WindowModelOutput
from domsignal.ai.providers.base import (
    AnalysisProvider,
    ProviderBudgetExceeded,
    ProviderCircuitOpen,
    ProviderInvalidOutput,
    ProviderOverloaded,
    ProviderResult,
    ProviderTimeout,
    ProviderUnavailable,
    build_request,
    prompt_version_of,
)
from domsignal.ai.rules.lexicon import Lexicon, load_lexicon
from domsignal.ai.taxonomy import Taxonomy, load_taxonomy
from domsignal.ai.validate import ValidatedWindow, validate_output

logger = logging.getLogger("domsignal.ai")

DEFAULT_TIMEOUT_SECONDS = 6.0


class WindowAnalyzer:
    """Одно ядро анализа для пассивного чтения чата и явного пути."""

    def __init__(
        self,
        provider: AnalysisProvider | None = None,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_SECONDS,
        audit_rate: int = DEFAULT_AUDIT_RATE,
        taxonomy: Taxonomy | None = None,
        lexicon: Lexicon | None = None,
    ) -> None:
        self.provider = provider
        self.timeout_s = timeout_s
        self.audit_rate = audit_rate
        self._taxonomy = taxonomy
        self._lexicon = lexicon

    async def analyze(self, window: WindowInput) -> WindowAnalysis:
        """Разобрать окно. Метод не бросает исключений ни при каком входе."""
        started = time.perf_counter()
        digest = ""
        try:
            digest = input_sha256(window)
            taxonomy = self._taxonomy or load_taxonomy()
            lexicon = self._lexicon or load_lexicon()
            rules = analyze_with_rules(window, taxonomy, lexicon)
        except Exception:
            logger.exception("ai.window.rules_failed")
            return self._manual(digest, started)

        if self.provider is None:
            return self._finish(window, rules, digest, started, "disabled", provider_called=False)

        state: ExecutionState = "ok"
        validated: ValidatedWindow | None = None
        result: ProviderResult | None = None
        called = True
        try:
            request, mapping = build_request(window, taxonomy)
            async with asyncio.timeout(self.timeout_s):
                result = await self.provider.analyze_window(request)
            parsed = WindowModelOutput.model_validate(_as_mapping(result.content))
            validated = validate_output(window, parsed, mapping, rules, taxonomy)
        except ProviderBudgetExceeded:
            state, called = "fallback_budget", False
        except ProviderCircuitOpen:
            state, called = "fallback_circuit_open", False
        except ProviderOverloaded:
            state, called = "fallback_overloaded", False
        except (ProviderTimeout, TimeoutError):
            state = "fallback_timeout"
        except ProviderUnavailable:
            state = "fallback_provider_error"
        except (ProviderInvalidOutput, ValidationError, ValueError, TypeError):
            state = "fallback_invalid_output"
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ai.window.provider_failed")
            state = "fallback_provider_error"
        if state != "ok" or validated is None:
            if state == "ok":
                state = "fallback_invalid_output"
            return self._finish(
                window, rules, digest, started, state, provider_called=called, result=result
            )

        typed, events = subtype_from_danger(validated.signals, taxonomy)
        signals = apply_audit_sample(typed, digest, self.audit_rate)
        analysis = WindowAnalysis(
            mode="model",
            execution=self._execution("ok", started, provider_called=True, result=result),
            versions=self._versions(taxonomy, lexicon, digest, result=result),
            lines=validated.lines,
            signals=signals,
            danger_hits=rules.danger_hits,
            semantic_danger=validated.semantic_danger,
            audit_events=(*validated.audit_events, *events),
            dropped_fields=validated.dropped_fields,
        )
        _log(analysis)
        return analysis

    # ---------------------------------------------------------------- helpers

    def _versions(
        self,
        taxonomy: Taxonomy,
        lexicon: Lexicon,
        digest: str,
        *,
        result: ProviderResult | None = None,
    ) -> Versions:
        """Промпт и модель записываются только когда модель действительно ответила."""
        return Versions(
            taxonomy=taxonomy.version,
            rules=lexicon.version,
            schema_id=SCHEMA_ID,
            input_sha256=digest,
            prompt=prompt_version_of(self.provider) if result is not None else None,
            model=(result.model or None) if result is not None else None,
        )

    def _execution(
        self,
        state: ExecutionState,
        started: float,
        *,
        provider_called: bool,
        result: ProviderResult | None,
    ) -> ExecutionInfo:
        """Учёт берётся только из ответа провайдера: `None` — «не сообщил»."""
        return ExecutionInfo(
            state=state,
            latency_ms=_elapsed_ms(started),
            provider_called=provider_called,
            provider_model=(result.model or None) if result is not None else None,
            tokens_in=result.tokens_in if result is not None else None,
            tokens_out=result.tokens_out if result is not None else None,
            cost_rub=result.cost_rub if result is not None else None,
        )

    def _finish(
        self,
        window: WindowInput,
        rules: RulesOutcome,
        digest: str,
        started: float,
        state: ExecutionState,
        *,
        provider_called: bool,
        result: ProviderResult | None = None,
    ) -> WindowAnalysis:
        taxonomy = self._taxonomy or load_taxonomy()
        lexicon = self._lexicon or load_lexicon()
        typed, events = subtype_from_danger(rules.signals, taxonomy)
        signals: tuple[SignalDraft, ...] = apply_audit_sample(typed, digest, self.audit_rate)
        mode: AnalysisMode = "rules" if rules.has_signals else "manual"
        analysis = WindowAnalysis(
            mode=mode,
            execution=self._execution(
                state, started, provider_called=provider_called, result=result
            ),
            versions=self._versions(taxonomy, lexicon, digest, result=result),
            lines=rules.lines,
            signals=signals,
            danger_hits=rules.danger_hits,
            audit_events=(*rules.audit_events, *events),
        )
        _log(analysis)
        return analysis

    def _manual(self, digest: str, started: float) -> WindowAnalysis:
        analysis = WindowAnalysis(
            mode="manual",
            execution=ExecutionInfo(
                state="error_rules",
                latency_ms=_elapsed_ms(started),
                provider_called=False,
            ),
            versions=Versions(
                taxonomy="unknown",
                rules="unknown",
                schema_id=SCHEMA_ID,
                input_sha256=digest,
            ),
        )
        _log(analysis)
        return analysis


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _as_mapping(raw: Any) -> Any:
    if isinstance(raw, str | bytes | bytearray):
        return json.loads(raw)
    return raw


def _log(analysis: WindowAnalysis) -> None:
    """Одна структурированная строка на анализ, без текстов реплик."""
    logger.info(
        "ai.window.analyzed",
        extra={
            "ai_mode": analysis.mode,
            "ai_state": analysis.execution.state,
            "ai_latency_ms": analysis.execution.latency_ms,
            "ai_lines": len(analysis.lines),
            "ai_signals": len(analysis.signals),
            "ai_dropped_fields": analysis.dropped_fields,
            "ai_audit_events": len(analysis.audit_events),
            "ai_input_sha256": analysis.versions.input_sha256,
            "ai_model": analysis.execution.provider_model,
            "ai_tokens_in": analysis.execution.tokens_in,
            "ai_tokens_out": analysis.execution.tokens_out,
            "ai_cost_rub": analysis.execution.cost_rub,
        },
    )
