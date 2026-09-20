"""Устойчивость вызова модели: предохранитель, ограничитель и бюджет.

`ResilientProvider` реализует тот же протокол `AnalysisProvider` и оборачивает
любой провайдер. Отказ здесь — не исключение наружу, а честное состояние:
фасад отображает `ProviderCircuitOpen`, `ProviderOverloaded` и
`ProviderBudgetExceeded` в `fallback_circuit_open`, `fallback_overloaded` и
`fallback_budget`, и продукт получает результат правил.

Что где живёт (целевая архитектура v3 §10):

- предохранитель — **на процесс**: серия отказов подряд закрывает доступ к
  провайдеру на паузу, затем пропускается одна пробная попытка;
- ограничитель конкурентности — **на процесс**: реплики × семафор ≤ квота
  провайдера;
- бюджет — **общий для всех реплик**: дневной лимит вызовов и доля на один
  чат. Реализация в памяти годится для одного процесса и для оценки; для
  продукта DEV-B делает реализацию того же протокола на счётчике PostgreSQL
  (атомарный инкремент), см. `BudgetGuard`.

Ключ чата в запрос окна не входит и входить не может: во внешний вызов
идентификаторы продукта не уходят. Поэтому область бюджета задаётся рядом с
вызовом через контекст `budget_scope`.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

from domsignal.ai.providers.base import (
    AnalysisProvider,
    ProviderBudgetExceeded,
    ProviderCircuitOpen,
    ProviderInvalidOutput,
    ProviderOverloaded,
    ProviderRequest,
    ProviderResult,
    prompt_version_of,
)

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_RESET_SECONDS = 60.0
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_ACQUIRE_WAIT_SECONDS = 1.5
DEFAULT_CHAT_SHARE = 0.2

_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar("ai_budget_scope", default=None)


@contextmanager
def budget_scope(key: str | None) -> Iterator[None]:
    """Задать область бюджета (обычно — привязка чата) на время вызова."""
    token = _scope.set(key)
    try:
        yield
    finally:
        _scope.reset(token)


def current_budget_scope() -> str | None:
    """Текущая область бюджета или `None`, если её не задали."""
    return _scope.get()


# ------------------------------------------------------------------- бюджет


@dataclass(frozen=True)
class BudgetOutcome:
    """Чем закончился вызов, за который бюджет уже списал единицу."""

    scope_key: str | None
    success: bool
    cost_rub: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


@runtime_checkable
class BudgetGuard(Protocol):
    """Учёт вызовов модели.

    Семантика, обязательная для любой реализации:

    - `try_acquire(scope_key)` вызывается **до** обращения к провайдеру и
      **списывает единицу** дневного лимита, если она есть. `False` означает
      «вызова не будет»: лимит дня исчерпан или область выбрала свою долю.
      Проверка и списание обязаны быть атомарными (в PostgreSQL — один
      `UPDATE ... RETURNING`), иначе параллельные реплики перебирают лимит.
    - `record(outcome)` вызывается **после** попытки, ровно один раз на каждое
      успешное `try_acquire`. Единица при отказе **не возвращается**: запрос
      уже ушёл к провайдеру и мог быть оплачен. `record` уточняет учёт —
      фактическую стоимость и токены.
    """

    def try_acquire(self, scope_key: str | None) -> bool: ...

    def record(self, outcome: BudgetOutcome) -> None: ...


@dataclass
class BudgetSnapshot:
    """Состояние бюджета на текущие сутки — для логов и отчётов."""

    day: date
    calls: int
    limit: int
    per_scope_limit: int
    failures: int
    cost_rub: float
    by_scope: dict[str, int] = field(default_factory=dict)


class InMemoryBudgetGuard:
    """Дневной лимит вызовов и доля на область — в памяти процесса.

    Годится для одного процесса, тестов и скриптов оценки. Для продукта
    нужен счётчик в PostgreSQL: несколько реплик воркера считают общий лимит.
    """

    def __init__(
        self,
        daily_calls: int,
        *,
        chat_share: float = DEFAULT_CHAT_SHARE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if daily_calls < 0:
            raise ValueError("daily call budget must not be negative")
        if not 0 < chat_share <= 1:
            raise ValueError("chat share must be in (0, 1]")
        self.daily_calls = daily_calls
        self.chat_share = chat_share
        self._clock = clock or (lambda: datetime.now(UTC))
        self._day = self._clock().date()
        self._calls = 0
        self._failures = 0
        self._cost_rub = 0.0
        self._by_scope: dict[str, int] = {}

    @property
    def per_scope_limit(self) -> int:
        """Сколько вызовов в сутки может израсходовать одна область."""
        return max(1, int(self.daily_calls * self.chat_share)) if self.daily_calls else 0

    def try_acquire(self, scope_key: str | None) -> bool:
        self._roll_day()
        if self._calls >= self.daily_calls:
            return False
        if scope_key is not None and self._by_scope.get(scope_key, 0) >= self.per_scope_limit:
            return False
        self._calls += 1
        if scope_key is not None:
            self._by_scope[scope_key] = self._by_scope.get(scope_key, 0) + 1
        return True

    def record(self, outcome: BudgetOutcome) -> None:
        self._roll_day()
        if not outcome.success:
            self._failures += 1
        if outcome.cost_rub:
            self._cost_rub += outcome.cost_rub

    def snapshot(self) -> BudgetSnapshot:
        self._roll_day()
        return BudgetSnapshot(
            day=self._day,
            calls=self._calls,
            limit=self.daily_calls,
            per_scope_limit=self.per_scope_limit,
            failures=self._failures,
            cost_rub=round(self._cost_rub, 6),
            by_scope=dict(self._by_scope),
        )

    def _roll_day(self) -> None:
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self._calls = 0
            self._failures = 0
            self._cost_rub = 0.0
            self._by_scope.clear()


# ------------------------------------------------------------ предохранитель


class CircuitBreaker:
    """Серия отказов подряд закрывает провайдера на паузу.

    Неразбираемый ответ (`ProviderInvalidOutput`) предохранитель не считает
    отказом: провайдер жив и ответил, непригоден именно ответ модели — этим
    занимается валидатор и путь правил.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        reset_seconds: float = DEFAULT_RESET_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure threshold must be at least 1")
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._clock = clock or time.monotonic
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def allow(self) -> bool:
        """Можно ли сейчас обращаться к провайдеру."""
        if self._opened_at is None:
            return True
        if self._clock() - self._opened_at < self.reset_seconds:
            return False
        if self._probe_in_flight:
            return False
        self._probe_in_flight = True
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self._probe_in_flight = False
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = self._clock()

    def record_unusable_output(self) -> None:
        """Ответ пришёл, но не пригоден: доступность провайдера не меняется."""
        self._probe_in_flight = False


# ------------------------------------------------------------ ограничитель


class ConcurrencyLimiter:
    """Семафор на процесс с ограниченным ожиданием места."""

    def __init__(
        self,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        *,
        wait_seconds: float = DEFAULT_ACQUIRE_WAIT_SECONDS,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max concurrency must be at least 1")
        self.max_concurrency = max_concurrency
        self.wait_seconds = wait_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def acquire(self) -> None:
        try:
            async with asyncio.timeout(self.wait_seconds):
                await self._semaphore.acquire()
        except TimeoutError as exc:
            raise ProviderOverloaded(
                f"no free slot in {self.wait_seconds} s (limit {self.max_concurrency})"
            ) from exc

    def release(self) -> None:
        self._semaphore.release()


# ----------------------------------------------------------------- провайдер


class ResilientProvider:
    """Тот же протокол провайдера плюс предохранитель, семафор и бюджет.

    Порядок проверок выбран так, чтобы ничего не терялось зря: сначала
    предохранитель (вызов заведомо не нужен), затем место в семафоре, и только
    потом единица бюджета — прямо перед обращением к провайдеру.
    """

    def __init__(
        self,
        inner: AnalysisProvider,
        *,
        breaker: CircuitBreaker | None = None,
        limiter: ConcurrencyLimiter | None = None,
        budget: BudgetGuard | None = None,
    ) -> None:
        self.inner = inner
        self.breaker = breaker or CircuitBreaker()
        self.limiter = limiter or ConcurrencyLimiter()
        self.budget = budget

    @property
    def prompt_version(self) -> str | None:
        return prompt_version_of(self.inner)

    async def analyze_window(self, request: ProviderRequest) -> ProviderResult:
        if not self.breaker.allow():
            raise ProviderCircuitOpen("llm circuit is open after repeated failures")
        await self.limiter.acquire()
        try:
            scope_key = current_budget_scope()
            if self.budget is not None and not self.budget.try_acquire(scope_key):
                raise ProviderBudgetExceeded("llm call budget is spent")
            try:
                result = await self.inner.analyze_window(request)
            except asyncio.CancelledError:
                # Отмена задачи — не отказ провайдера: предохранитель не трогаем.
                raise
            except ProviderInvalidOutput:
                self.breaker.record_unusable_output()
                self._record(scope_key, success=False)
                raise
            except Exception:
                self.breaker.record_failure()
                self._record(scope_key, success=False)
                raise
            self.breaker.record_success()
            self._record(
                scope_key,
                success=True,
                cost_rub=result.cost_rub,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
            )
            return result
        finally:
            self.limiter.release()

    def _record(
        self,
        scope_key: str | None,
        *,
        success: bool,
        cost_rub: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        if self.budget is None:
            return
        self.budget.record(
            BudgetOutcome(
                scope_key=scope_key,
                success=success,
                cost_rub=cost_rub,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
        )
