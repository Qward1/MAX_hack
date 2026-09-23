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
AI_JOB_KINDS: frozenset[str] = frozenset({"ai.report.analyze", "ai.window.analyze"})


#: Аренда задачи операционного пула: его обработчики модель не ждут.
OPERATIONAL_LEASE_SECONDS = 30

#: Запас аренды AI-пула сверх таймаута вызова модели: чтение окна до вызова и
#: запись результата после него идут под той же арендой.
AI_LEASE_MARGIN_SECONDS = 20


def lease_seconds_for(
    pool: WorkerPool, *, ai_lease_seconds: int, model_timeout_seconds: float | None
) -> int:
    """Аренда задачи пула.

    Аренда AI-пула короче вызова модели отдала бы задачу второму воркеру
    посреди вызова: двойной расход бюджета и потерянная попытка. Такая
    настройка — ошибка запуска, а не молчаливая поправка.
    """
    if pool != "ai":
        return OPERATIONAL_LEASE_SECONDS
    if (
        model_timeout_seconds is not None
        and ai_lease_seconds < model_timeout_seconds + AI_LEASE_MARGIN_SECONDS
    ):
        raise ValueError(
            "AI_WORKER_LEASE_SECONDS must be at least the model timeout + "
            f"{AI_LEASE_MARGIN_SECONDS} s ({model_timeout_seconds:g} + "
            f"{AI_LEASE_MARGIN_SECONDS} > {ai_lease_seconds})"
        )
    return ai_lease_seconds


def pool_for(kind: str) -> WorkerPool:
    """Какому пулу принадлежит вид задачи."""
    return "ai" if kind.startswith(AI_KIND_PREFIX) else DEFAULT_POOL


def claims_kind(pool: WorkerPool, kind: str) -> bool:
    """Забирает ли пул задачи этого вида."""
    return pool_for(kind) == pool
