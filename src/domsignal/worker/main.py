from __future__ import annotations

import argparse
import asyncio
import logging

from domsignal.bootstrap import build_container
from domsignal.logs import configure_logging
from domsignal.settings import get_settings
from domsignal.worker.pools import DEFAULT_POOL, POOLS, WorkerPool, lease_seconds_for
from domsignal.worker.runner import WorkerRunner

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
        while True:
            handled = await runner.run_once()
            if not handled:
                await asyncio.sleep(1)
    finally:
        await container.aclose()


if __name__ == "__main__":
    configure_logging()
    asyncio.run(run(parse_pool()))
