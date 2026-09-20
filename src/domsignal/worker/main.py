from __future__ import annotations

import argparse
import asyncio

from domsignal.bootstrap import build_container
from domsignal.settings import get_settings
from domsignal.worker.pools import DEFAULT_POOL, POOLS, WorkerPool
from domsignal.worker.runner import WorkerRunner


def parse_pool(argv: list[str] | None = None) -> WorkerPool:
    """Пул выбирается параметром запуска; по умолчанию — операционный."""
    parser = argparse.ArgumentParser(description="DomSignal durable job worker")
    parser.add_argument("--pool", choices=list(POOLS), default=DEFAULT_POOL)
    return parser.parse_args(argv).pool  # type: ignore[no-any-return]


async def run(pool: WorkerPool = DEFAULT_POOL) -> None:
    container = build_container(get_settings())
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
        notifications=container.notifications,
        pool=pool,
    )
    try:
        while True:
            handled = await runner.run_once()
            if not handled:
                await asyncio.sleep(1)
    finally:
        await container.aclose()


if __name__ == "__main__":
    asyncio.run(run(parse_pool()))
