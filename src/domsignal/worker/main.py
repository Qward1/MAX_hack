from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import UTC, datetime, timedelta

from domsignal.bootstrap import build_container
from domsignal.logs import configure_logging
from domsignal.services.digest import TICK_JOB as DIGEST_TICK_JOB
from domsignal.services.digest import next_hour
from domsignal.services.followups import TICK_JOB as FOLLOWUP_TICK_JOB
from domsignal.services.job_cleanup import TICK_JOB as JOB_CLEANUP_TICK_JOB
from domsignal.services.job_cleanup import TICK_PRIORITY as JOB_CLEANUP_PRIORITY
from domsignal.services.periodic import ensure_periodic
from domsignal.services.reception import TICK_JOB as RECEPTION_TICK_JOB
from domsignal.settings import Settings, get_settings
from domsignal.worker.pools import DEFAULT_POOL, POOLS, WorkerPool, lease_seconds_for
from domsignal.worker.runner import WorkerRunner, run_loops

logger = logging.getLogger(__name__)


def parse_pool(argv: list[str] | None = None) -> WorkerPool:
    """Пул выбирается параметром запуска; по умолчанию — операционный."""
    parser = argparse.ArgumentParser(description="DomSignal durable job worker")
    parser.add_argument("--pool", choices=list(POOLS), default=DEFAULT_POOL)
    return parser.parse_args(argv).pool  # type: ignore[no-any-return]


async def run(pool: WorkerPool = DEFAULT_POOL) -> None:
    container = build_container(get_settings())
    if pool == DEFAULT_POOL:
        # Очистка буфера ставится при старте и дальше переставляет себя сама.
        # Сбой постановки не мешает доставке и приёму: следующий старт повторит.
        try:
            await container.passive.ensure_purge_scheduled()
        except Exception as exc:  # noqa: BLE001
            logger.error("buffer_purge_not_scheduled", extra={"error_type": type(exc).__name__})
        # D3: сопровождение обращений, сводка в 09:00 по местному времени УК,
        # напоминания о приёме.
        try:
            now = datetime.now(UTC)
            await ensure_periodic(container.session_factory, FOLLOWUP_TICK_JOB)
            await ensure_periodic(container.session_factory, RECEPTION_TICK_JOB)
            # D5: очистка очереди задач раз в час, первая — через час после старта.
            await ensure_periodic(
                container.session_factory,
                JOB_CLEANUP_TICK_JOB,
                priority=JOB_CLEANUP_PRIORITY,
                first_at=now + timedelta(hours=1),
            )
            await ensure_periodic(
                container.session_factory,
                DIGEST_TICK_JOB,
                first_at=next_hour(now),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("periodic_jobs_not_scheduled", extra={"error_type": type(exc).__name__})
    try:
        runner = WorkerRunner(
            session_factory=container.session_factory,
            handlers=container.worker_handlers.mapping,
            lease_seconds=lease_seconds_for(
                pool,
                ai_lease_seconds=container.settings.ai_worker_lease_seconds,
                model_timeout_seconds=container.ai_timeout_seconds,
            ),
            notifications=container.notifications,
            pool=pool,
        )
        concurrency = concurrency_for(pool, container.settings)
        stop = asyncio.Event()
        install_stop_signals(stop)
        logger.info("worker_started", extra={"pool": pool, "concurrency": concurrency})
        await run_loops(runner, concurrency=concurrency, stop=stop)
        logger.info("worker_stopped", extra={"pool": pool})
    finally:
        await container.aclose()


def concurrency_for(pool: WorkerPool, settings: Settings) -> int:
    """Число параллельных циклов пула: `AI_WORKER_CONCURRENCY` или операционного."""
    if pool == "ai":
        return settings.ai_worker_concurrency
    return settings.operational_worker_concurrency


def install_stop_signals(stop: asyncio.Event) -> None:
    """SIGTERM/SIGINT — корректная остановка: начатые задачи доходят до конца.

    На Windows обработчики сигналов цикла недоступны: там процесс
    останавливается как раньше, аренда задач вернёт их в очередь.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            return


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run(parse_pool()))
