"""Здоровье очереди и готовность справочника на обзоре платформы (D5).

Только агрегаты по базе и по загруженному справочнику — без текстов жителей и
без идентификаторов. Очередь: ожидающие задачи по пулам и возраст самой старой
из тех, что уже пора выполнить; доля окон, разобранных правилами из-за
перегрузки или бюджета модели, за 24 часа; расход дневного бюджета модели.
Справочник (аудит Р-3): по каждому пакету — проверено, ждёт сверки, старше
180 дней, недоступные в регионе каналы.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.dashboards import (
    DirectoryPackReadiness,
    ModelBudgetToday,
    QueueHealth,
    QueuePoolHealth,
    WindowFallbacks,
)
from domsignal.core.responsibility import (
    STALE_AFTER_DAYS,
    DirectoryLayer,
    ResponsibilityDirectory,
    Verification,
)
from domsignal.worker.pools import AI_KIND_PREFIX

_POOLS = text(
    f"""
    SELECT CASE WHEN starts_with(kind, '{AI_KIND_PREFIX}') THEN 'ai' ELSE 'operational' END
             AS pool,
           count(*) FILTER (WHERE status = 'pending' AND next_attempt_at <= :now) AS due,
           count(*) FILTER (WHERE status = 'pending' AND next_attempt_at > :now) AS scheduled,
           count(*) FILTER (WHERE status = 'leased') AS leased,
           extract(epoch FROM :now - min(next_attempt_at)
                   FILTER (WHERE status = 'pending' AND next_attempt_at <= :now)) AS oldest
    FROM jobs
    WHERE status IN ('pending', 'leased')
    GROUP BY 1
    """
)

#: Окна за сутки: кто разобрал и почему правилами.
_WINDOWS = text(
    """
    SELECT count(*) AS total,
           count(*) FILTER (WHERE analyzed_by = 'ai' AND execution_state = 'ok') AS model,
           count(*) FILTER (WHERE analyzed_by = 'fallback') AS watchdog,
           count(*) FILTER (WHERE execution_state = 'fallback_budget') AS budget,
           count(*) FILTER (WHERE execution_state IN ('fallback_overloaded',
                                                      'fallback_circuit_open')) AS overload
    FROM conversation_windows
    WHERE state = 'done' AND completed_at >= :since
    """
)

_DELIVERIES = text(
    """
    SELECT count(*) FROM notification_deliveries
    WHERE (next_attempt_at IS NULL OR next_attempt_at <= :now)
      AND (status IN ('pending', 'retry_wait')
           OR (status = 'accepted' AND desired_version > applied_version))
    """
)


async def queue_health(
    db: AsyncSession, *, daily_call_budget: int, now: datetime | None = None
) -> QueueHealth:
    at = now or datetime.now(UTC)
    rows = {row.pool: row for row in await db.execute(_POOLS, {"now": at})}
    pools = [
        QueuePoolHealth(
            pool=pool,
            due=int(rows[pool].due) if pool in rows else 0,
            scheduled=int(rows[pool].scheduled) if pool in rows else 0,
            leased=int(rows[pool].leased) if pool in rows else 0,
            oldest_due_seconds=(
                round(float(rows[pool].oldest), 1)
                if pool in rows and rows[pool].oldest is not None
                else None
            ),
        )
        for pool in ("operational", "ai")
    ]
    windows = (await db.execute(_WINDOWS, {"since": at - timedelta(hours=24)})).one()
    by_rules = int(windows.watchdog) + int(windows.budget) + int(windows.overload)
    total = int(windows.total)
    used = await db.scalar(
        text("SELECT calls FROM ai_call_budget WHERE scope_key = '' AND day = :day"),
        {"day": at.astimezone(UTC).date()},
    )
    used = int(used or 0)
    return QueueHealth(
        generated_at=at,
        pools=pools,
        deliveries_due=int(await db.scalar(_DELIVERIES, {"now": at}) or 0),
        windows_24h=WindowFallbacks(
            total=total,
            by_model=int(windows.model),
            by_rules_overload_or_budget=by_rules,
            watchdog=int(windows.watchdog),
            budget=int(windows.budget),
            provider_overload=int(windows.overload),
            share_rules_overload_or_budget=round(by_rules / total, 4) if total else None,
        ),
        model_budget_today=ModelBudgetToday(
            used=used,
            limit=daily_call_budget,
            share=round(used / daily_call_budget, 4) if daily_call_budget else None,
        ),
    )


def _records(layer: DirectoryLayer) -> list[Verification]:
    records: list[Any] = [*layer.organizations, *layer.channels, *layer.rules]
    records += list(layer.reference_links)
    if layer.uk_default is not None:
        records.append(layer.uk_default)
    return [item.verification for item in records]


def _readiness(
    code: str, layer: DirectoryLayer, directory: ResponsibilityDirectory, today: date
) -> DirectoryPackReadiness:
    records = _records(layer)
    for section in directory.municipalities.get(code, {}).values():
        records += _records(section)
    channels = [*directory.federal.channels, *layer.channels]
    return DirectoryPackReadiness(
        pack=code,
        name=layer.name or ("Федеральный слой" if code == directory.federal.layer_id else code),
        version=layer.version,
        timezone=layer.timezone,
        verified=sum(1 for item in records if item.status == "verified"),
        needs_verification=sum(1 for item in records if item.status != "verified"),
        stale=sum(1 for item in records if item.status == "verified" and item.stale_on(today)),
        unavailable_channels=sorted(
            channel.label for channel in channels if code in channel.unavailable_regions
        ),
    )


def directory_readiness(
    directory: ResponsibilityDirectory | None, *, today: date | None = None
) -> list[DirectoryPackReadiness]:
    """Готовность каждого пакета справочника: федеральный слой и регионы."""
    if directory is None:
        return []
    day = today or datetime.now(UTC).date()
    federal = directory.federal
    return [
        _readiness(federal.layer_id, federal, directory, day),
        *(
            _readiness(code, layer, directory, day)
            for code, layer in sorted(directory.regions.items())
        ),
    ]


__all__ = ["STALE_AFTER_DAYS", "directory_readiness", "queue_health"]
