"""Реестр «вид задачи → пул воркера»: изоляция нагрузки LLM.

Один код воркера, пул выбирается параметром запуска (целевая архитектура v3
§10). Пул определяется **видом задачи**, а не составом обработчиков: иначе
задача неизвестного вида не досталась бы никому и осталась бы в очереди
навсегда, вместо честного отказа после исчерпания попыток.

Деградация AI не должна касаться доставки уведомлений и жизненного цикла
Ticket — поэтому они остаются в `operational`, а вызовы модели живут в `ai`.
"""

from __future__ import annotations

from typing import Literal, get_args

WorkerPool = Literal["operational", "ai"]

POOLS: tuple[WorkerPool, ...] = get_args(WorkerPool)

#: Пул по умолчанию: всё, что не обращается к модели.
DEFAULT_POOL: WorkerPool = "operational"

#: Префикс видов задач, обращающихся к модели.
AI_KIND_PREFIX = "ai."

#: Известные виды задач AI-пула. Перечень документирует состав пула; решение
#: принимает префикс, поэтому будущий `ai.*` не окажется без хозяина.
AI_JOB_KINDS: frozenset[str] = frozenset({"ai.report.analyze"})


def pool_for(kind: str) -> WorkerPool:
    """Какому пулу принадлежит вид задачи."""
    return "ai" if kind.startswith(AI_KIND_PREFIX) else DEFAULT_POOL


def claims_kind(pool: WorkerPool, kind: str) -> bool:
    """Забирает ли пул задачи этого вида."""
    return pool_for(kind) == pool
