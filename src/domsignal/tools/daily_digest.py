"""Ручной запуск ежедневной сводки сотрудникам (D3) — то же, что задача в 09:00 МСК.

Сводку получают только сотрудники, которые включили её в кабинете и которым
бот может написать; пустой день — без сообщения. Повтор в тот же день не
дублирует: одна сводка на сотрудника, УК и день. Доставляет воркер.

    python -m domsignal.tools.daily_digest
    python -m domsignal.tools.daily_digest --company <id УК>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from domsignal.bootstrap import build_container
from domsignal.settings import get_settings
from domsignal.tools import print_json


async def run(company: UUID | None) -> int:
    container = build_container(get_settings())
    try:
        queued = await container.digest.run(company_id=company)
        print_json({"queued": queued})
        return 0
    finally:
        await container.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue today's staff digest now")
    parser.add_argument("--company", type=UUID, default=None)
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.company)))


if __name__ == "__main__":
    main()
