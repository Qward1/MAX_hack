"""Дневной бюджет вызовов модели на счётчике PostgreSQL.

Протокол `BudgetGuard` из `domsignal.ai.resilience` **синхронный**: он
вызывается изнутри `ResilientProvider`, уже в работающем цикле событий, где
нельзя ни `await`, ни блокировать поток. Поэтому решение принимается заранее,
асинхронно и атомарно — в `reserve()`, — а `try_acquire()` только сообщает уже
принятое решение текущей задачи.

Это не ослабление семантики: проверка и списание по-прежнему одна операция
PostgreSQL, и они происходят **до** обращения к провайдеру. Отказ означает
«вызова не будет»: продукт получает результат правил и состояние
`fallback_budget`.

Область бюджета (привязка чата) в запрос окна не входит и входить не может:
во внешний вызов идентификаторы продукта не уходят. Она передаётся рядом с
вызовом — через тот же контекст `budget_scope`, что использует AI-ядро.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.ai import BudgetOutcome, ProviderRateLimited, budget_scope
from domsignal.db.models import GLOBAL_BUDGET_SCOPE

logger = logging.getLogger(__name__)

DEFAULT_DAILY_CALLS = 1000
DEFAULT_CHAT_SHARE = 0.2

_CHARGE = text(
    """
    INSERT INTO ai_call_budget AS b (day, scope_key, calls)
    VALUES (:day, :scope_key, 1)
    ON CONFLICT (day, scope_key) DO UPDATE SET calls = b.calls + 1
    WHERE b.calls < :limit
    RETURNING b.calls
    """
)
#: F1: токены модели в минуту — общий счёт процессов, та же атомарная схема.
_TOKENS = text(
    """
    INSERT INTO ai_token_minutes AS t (minute, tokens)
    VALUES (:minute, :tokens)
    ON CONFLICT (minute) DO UPDATE SET tokens = t.tokens + :tokens
    WHERE t.tokens + :tokens <= :limit
    RETURNING t.tokens
    """
)
_TOKENS_ADJUST = text(
    """
    UPDATE ai_token_minutes SET tokens = GREATEST(0, tokens + :delta) WHERE minute = :minute
    """
)
#: Промпт window.v3 и схема — около 6,8 тыс. токенов входа (M1, 27.09),
#: ответ — до нескольких сотен. Оценка до вызова, после — фактические токены.
PROMPT_TOKENS = 6800
ANSWER_TOKENS = 600


def estimate_tokens(texts: list[str]) -> int:
    """Оценка токенов одного вызова окна до ответа провайдера."""
    return PROMPT_TOKENS + ANSWER_TOKENS + sum(len(value) for value in texts) // 2


@dataclass
class BudgetReservation:
    """Решение бюджета на один вызов модели.

    `allowed=False` — единица не списана и вызова не будет. `outcome`
    заполняется `record()` после попытки: фактическая стоимость и токены.
    """

    scope_key: str | None
    allowed: bool
    daily_calls: int | None = None
    scope_calls: int | None = None
    outcome: BudgetOutcome | None = None
    consumed: bool = field(default=False, repr=False)
    #: F1: отказ ограничителя токенов в минуту — не бюджет дня, а временный лимит.
    rate_limited: bool = False
    retry_after: float | None = None
    minute: datetime | None = None
    tokens_reserved: int = 0


_reservation: ContextVar[BudgetReservation | None] = ContextVar(
    "ai_budget_reservation", default=None
)


class PostgresBudgetGuard:
    """Дневной лимит вызовов и доля области на общем счётчике в PostgreSQL."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        daily_calls: int = DEFAULT_DAILY_CALLS,
        chat_share: float = DEFAULT_CHAT_SHARE,
        clock: Callable[[], datetime] | None = None,
        tokens_per_minute: int = 0,
    ) -> None:
        if daily_calls < 0:
            raise ValueError("daily call budget must not be negative")
        if not 0 < chat_share <= 1:
            raise ValueError("chat share must be in (0, 1]")
        self.sessions = session_factory
        self.daily_calls = daily_calls
        self.chat_share = chat_share
        self.tokens_per_minute = tokens_per_minute
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def per_scope_limit(self) -> int:
        """Сколько вызовов в сутки может израсходовать одна область."""
        return max(1, int(self.daily_calls * self.chat_share)) if self.daily_calls else 0

    @asynccontextmanager
    async def reserve(
        self, scope_key: str | None, *, tokens: int = 0
    ) -> AsyncIterator[BudgetReservation]:
        """Проверить и списать единицу дня (и токены минуты) до вызова модели.

        Списание общего счёта, доли области и токенов минуты идёт одной
        транзакцией: отказ любого откатывает остальные, иначе отказы
        дренировали бы дневной лимит дома.
        """
        reservation = await self._charge_all(scope_key, tokens)
        token = _reservation.set(reservation)
        try:
            with budget_scope(scope_key):
                yield reservation
        finally:
            _reservation.reset(token)
            await self._settle_tokens(reservation)
            self._log(reservation)

    # ------------------------------------------------- протокол BudgetGuard

    def try_acquire(self, scope_key: str | None) -> bool:
        """Сообщить решение, принятое `reserve()` для текущей задачи.

        Вне `reserve()` решения нет, поэтому ответ — «вызова не будет»: это
        отказ в безопасную сторону, а не молчаливый пропуск лимита.
        """
        reservation = _reservation.get()
        if reservation is not None and reservation.rate_limited and not reservation.consumed:
            reservation.consumed = True
            # Ограничитель токенов — как 429: окно подождёт, предохранитель цел.
            raise ProviderRateLimited(
                "llm tokens per minute are spent",
                retry_after=reservation.retry_after,
                local=True,
            )
        if reservation is None or reservation.consumed or not reservation.allowed:
            return False
        reservation.consumed = True
        return True

    def record(self, outcome: BudgetOutcome) -> None:
        """Уточнить учёт после попытки. Единица при отказе не возвращается."""
        reservation = _reservation.get()
        if reservation is not None:
            reservation.outcome = outcome

    # --------------------------------------------------------------- детали

    async def _charge_all(self, scope_key: str | None, tokens: int = 0) -> BudgetReservation:
        now = self._clock().astimezone(UTC)
        day = now.date()
        minute = now.replace(second=0, microsecond=0)
        rate_limited = False
        try:
            async with self.sessions() as session:
                try:
                    daily = await self._charge(session, day, GLOBAL_BUDGET_SCOPE, self.daily_calls)
                    scoped: int | None = None
                    allowed = daily is not None
                    if allowed and scope_key is not None:
                        scoped = await self._charge(
                            session, day, scope_key, self.per_scope_limit
                        )
                        allowed = scoped is not None
                    if allowed and self.tokens_per_minute > 0 and tokens > 0:
                        spent = (
                            await session.execute(
                                _TOKENS,
                                {
                                    "minute": minute,
                                    "tokens": tokens,
                                    "limit": self.tokens_per_minute,
                                },
                            )
                        ).scalar_one_or_none()
                        allowed = spent is not None
                        rate_limited = spent is None
                    if allowed:
                        await session.commit()
                    else:
                        await session.rollback()
                except Exception:
                    await session.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001 - бюджет не должен ронять путь жителя
            logger.error("ai_budget_unavailable", extra={"error_type": type(exc).__name__})
            return BudgetReservation(scope_key=scope_key, allowed=False)
        return BudgetReservation(
            scope_key=scope_key,
            allowed=allowed,
            daily_calls=daily,
            scope_calls=scoped,
            rate_limited=rate_limited,
            retry_after=(60 - now.second) if rate_limited else None,
            minute=minute if allowed and tokens else None,
            tokens_reserved=tokens if allowed and self.tokens_per_minute > 0 else 0,
        )

    async def _settle_tokens(self, reservation: BudgetReservation) -> None:
        """После ответа — поправка оценки фактическими токенами провайдера."""
        outcome = reservation.outcome
        if not reservation.tokens_reserved or reservation.minute is None or outcome is None:
            return
        if outcome.tokens_in is None and outcome.tokens_out is None:
            return
        actual = (outcome.tokens_in or 0) + (outcome.tokens_out or 0)
        delta = actual - reservation.tokens_reserved
        if not delta:
            return
        try:
            async with self.sessions() as session, session.begin():
                await session.execute(
                    _TOKENS_ADJUST, {"minute": reservation.minute, "delta": delta}
                )
        except Exception as exc:  # noqa: BLE001 - учёт не должен ронять разбор
            logger.warning("ai_tokens_adjust_failed", extra={"error_type": type(exc).__name__})

    async def _charge(
        self, session: AsyncSession, day: date, scope_key: str, limit: int
    ) -> int | None:
        """Атомарный инкремент с проверкой лимита; `None` — лимит исчерпан.

        Нулевой лимит отсекается до запроса: `ON CONFLICT ... WHERE` защищает
        только обновление, а вставка первой строки прошла бы мимо проверки.
        """
        if limit <= 0:
            return None
        result = await session.execute(
            _CHARGE, {"day": day, "scope_key": scope_key, "limit": limit}
        )
        return result.scalar_one_or_none()

    def _log(self, reservation: BudgetReservation) -> None:
        outcome = reservation.outcome
        logger.info(
            "ai_budget_reservation",
            extra={
                "ai_budget_allowed": reservation.allowed,
                "ai_budget_daily_calls": reservation.daily_calls,
                "ai_budget_daily_limit": self.daily_calls,
                "ai_budget_scope_calls": reservation.scope_calls,
                "ai_budget_scope_limit": self.per_scope_limit,
                "ai_budget_used": reservation.consumed,
                "ai_rate_limited": reservation.rate_limited,
                "ai_tokens_reserved": reservation.tokens_reserved,
                "ai_cost_rub": outcome.cost_rub if outcome else None,
                "ai_tokens_in": outcome.tokens_in if outcome else None,
                "ai_tokens_out": outcome.tokens_out if outcome else None,
            },
        )


__all__ = ["GLOBAL_BUDGET_SCOPE", "BudgetReservation", "PostgresBudgetGuard", "estimate_tokens"]
