"""Производительность правил: приём webhook и анализ одиночного сообщения."""

from __future__ import annotations

import statistics
import time

from domsignal.ai import WindowAnalyzer, screen_message_for_danger
from tests.ai.helpers import single

SAMPLES = (
    "Лифт в 3 подъезде не работает с утра",
    "В подъезде сильно пахнет газом!",
    "мусор не вывозят третий день, контейнеры переполнены",
    "во дворе не горит фонарь у детской площадки",
    "никто не застрял, лифт просто не едет",
    "на улице у остановки не горят фонари, темно совсем",
)


def _p95(durations: list[float]) -> float:
    ordered = sorted(durations)
    index = max(0, int(len(ordered) * 0.95) - 1)
    return ordered[index]


def test_danger_screening_is_fast() -> None:
    durations: list[float] = []
    for _ in range(50):
        for text in SAMPLES:
            started = time.perf_counter()
            screen_message_for_danger(text)
            durations.append((time.perf_counter() - started) * 1000)
    assert _p95(durations) < 5.0, statistics.mean(durations)


async def test_single_message_analysis_is_fast() -> None:
    analyzer = WindowAnalyzer()
    windows = [single(text) for text in SAMPLES]
    await analyzer.analyze(windows[0])  # прогрев кэша ресурсов
    durations: list[float] = []
    for _ in range(20):
        for window in windows:
            started = time.perf_counter()
            await analyzer.analyze(window)
            durations.append((time.perf_counter() - started) * 1000)
    assert _p95(durations) < 5.0, statistics.mean(durations)
