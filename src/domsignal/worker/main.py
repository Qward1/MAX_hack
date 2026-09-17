from __future__ import annotations

import asyncio

from domsignal.bootstrap import build_container
from domsignal.settings import get_settings
from domsignal.worker.runner import WorkerRunner


async def run() -> None:
    container = build_container(get_settings())
    runner = WorkerRunner(
        session_factory=container.session_factory,
        handlers=container.worker_handlers.mapping,
    )
    try:
        while True:
            handled = await runner.run_once()
            if not handled:
                await asyncio.sleep(1)
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
