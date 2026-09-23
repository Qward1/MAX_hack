"""Учёт вызова модели для метрик пилота: задержка, токены, стоимость.

Одна запись для любого исхода разбора — модель ответила, оборвалась по
таймауту, не вызывалась вовсе (правила, бюджет, предохранитель). Поле, которое
провайдер не сообщил, остаётся `null`, а рядом стоит причина: `null` без
причины нельзя отличить от потерянного значения.
"""

from __future__ import annotations

from typing import Any, Literal

from domsignal.ai import WindowAnalysis
from domsignal.ai.contracts import ExecutionInfo

MissingReason = Literal[
    "provider_not_called",
    "timeout",
    "provider_error",
    "not_reported_by_provider",
]


def missing_reason(execution: ExecutionInfo, value: object) -> MissingReason | None:
    """Почему учётного значения нет. Есть значение — причины нет."""
    if value is not None:
        return None
    if not execution.provider_called:
        return "provider_not_called"
    if execution.state == "fallback_timeout":
        return "timeout"
    if execution.state == "fallback_provider_error":
        return "provider_error"
    return "not_reported_by_provider"


def execution_provenance(analysis: WindowAnalysis) -> dict[str, Any]:
    """Как прошёл вызов: состояние, задержка, модель, токены, ₽ и причины `null`."""
    execution = analysis.execution
    return {
        "mode": analysis.mode,
        "state": execution.state,
        "provider_called": execution.provider_called,
        "latency_ms": execution.latency_ms,
        "model": execution.provider_model,
        "tokens_in": execution.tokens_in,
        "tokens_out": execution.tokens_out,
        "tokens_missing_reason": missing_reason(execution, execution.tokens_in),
        "cost_rub": execution.cost_rub,
        "cost_missing_reason": missing_reason(execution, execution.cost_rub),
    }


__all__ = ["MissingReason", "execution_provenance", "missing_reason"]
