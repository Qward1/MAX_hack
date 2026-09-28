"""Пробы модели через штатную сборку анализатора (F1 §4.6): только синтетика.

    python -m domsignal.tools.llm_probe                  # три встроенные пробы
    python -m domsignal.tools.llm_probe --file probes.jsonl --limit 10

Каждая проба — окно из синтетических реплик (`{"id": ..., "lines": ["..."]}` в
JSONL). Печатается только номер пробы, режим, состояние, модель, задержка,
токены, ₽ и число сигналов — без текстов. В MAX ничего не пишется, проблемы и
заявки не создаются: анализатор трогает базу только счётчиками бюджета модели.
Реальные тексты чатов в пробы не кладутся.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from domsignal.ai import WindowInput, WindowLine
from domsignal.bootstrap import build_ai
from domsignal.db.session import create_engine, create_session_factory
from domsignal.services.ai_budget import estimate_tokens
from domsignal.settings import get_settings

#: Встроенные синтетические пробы: поломка, опасность, болтовня.
BUILTIN: tuple[dict[str, Any], ...] = (
    {
        "id": "builtin-lift",
        "lines": ["Во втором подъезде лифт стоит с утра", "Да, тоже пешком хожу"],
    },
    {"id": "builtin-gas", "lines": ["На третьем этаже сильно пахнет газом у лифта"]},
    {"id": "builtin-chatter", "lines": ["Всем доброе утро, хороших выходных!"]},
)


def load(path: str | None, limit: int | None) -> list[dict[str, Any]]:
    if path is None:
        probes = list(BUILTIN)
    else:
        probes = [
            json.loads(line)
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return probes[:limit] if limit else probes


def window(probe: dict[str, Any]) -> WindowInput:
    start = datetime.now(UTC) - timedelta(minutes=2)
    lines = tuple(
        WindowLine(
            line_id=f"p{index}",
            author_ref=f"author-{index % 2}",
            text=str(text),
            sent_at=start + timedelta(seconds=10 * index),
        )
        for index, text in enumerate(probe["lines"], start=1)
    )
    return WindowInput(channel=probe.get("channel", "group_passive"), lines=lines)


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        ai = build_ai(settings, create_session_factory(engine))
        total_rub = 0.0
        for probe in load(args.file, args.limit):
            probe_window = window(probe)
            if ai.budget is None:
                analysis = await ai.analyzer.analyze(probe_window)
            else:
                # Как у конвейера: сначала единица дня и токены минуты, потом вызов.
                # Вне резерва сторож бюджета честно отвечает «вызова не будет».
                tokens = estimate_tokens([line.text for line in probe_window.lines])
                async with ai.budget.reserve(None, tokens=tokens):
                    analysis = await ai.analyzer.analyze(probe_window)
            execution = analysis.execution
            total_rub += execution.cost_rub or 0.0
            print(
                json.dumps(
                    {
                        "probe": probe["id"],
                        "mode": analysis.mode,
                        "state": execution.state,
                        "model": execution.provider_model,
                        "latency_ms": execution.latency_ms,
                        "tokens_in": execution.tokens_in,
                        "tokens_out": execution.tokens_out,
                        "cost_rub": execution.cost_rub,
                        "signals": len(analysis.signals),
                        "danger_hits": len(analysis.danger_hits),
                    },
                    ensure_ascii=False,
                )
            )
        print(json.dumps({"total_rub": round(total_rub, 4)}))
    finally:
        await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", default=None, help="JSONL с синтетическими пробами")
    parser.add_argument("--limit", type=int, default=None)
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
