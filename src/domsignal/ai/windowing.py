"""Чистая политика нарезки потока реплик на окна.

Окно закрывается по первому из условий: тишина, число реплик, возраст первой
реплики, срабатывание правил опасности (немедленно). К окну прикладываются до
пяти предыдущих реплик как контекст — только для чтения.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from domsignal.ai.contracts import Channel, OpenItem, WindowInput, WindowLine
from domsignal.ai.rules.danger import screen_message_for_danger


@dataclass(frozen=True)
class WindowPolicy:
    silence_seconds: int = 120
    max_lines: int = 10
    max_age_seconds: int = 300
    context_lines: int = 5
    close_on_danger: bool = True


DEFAULT_POLICY = WindowPolicy()


def _triggers_danger(line: WindowLine) -> bool:
    return any(not hit.negated for hit in screen_message_for_danger(line.text))


def split_stream(
    lines: Sequence[WindowLine],
    policy: WindowPolicy = DEFAULT_POLICY,
) -> list[list[WindowLine]]:
    """Разбиение потока на группы реплик по политике окна."""
    windows: list[list[WindowLine]] = []
    current: list[WindowLine] = []
    for line in lines:
        if current:
            silence = (line.sent_at - current[-1].sent_at).total_seconds()
            age = (line.sent_at - current[0].sent_at).total_seconds()
            if (
                silence > policy.silence_seconds
                or len(current) >= policy.max_lines
                or age > policy.max_age_seconds
            ):
                windows.append(current)
                current = []
        current.append(line)
        if policy.close_on_danger and _triggers_danger(line):
            windows.append(current)
            current = []
    if current:
        windows.append(current)
    return windows


def build_windows(
    lines: Sequence[WindowLine],
    *,
    channel: Channel = "group_passive",
    open_items: Sequence[OpenItem] = (),
    entrance_hint: str | None = None,
    policy: WindowPolicy = DEFAULT_POLICY,
) -> list[WindowInput]:
    """Окна с приложенным контекстом предыдущих реплик."""
    groups = split_stream(lines, policy)
    result: list[WindowInput] = []
    consumed = 0
    for group in groups:
        start = max(0, consumed - policy.context_lines)
        context = [line.model_copy(update={"is_context": True}) for line in lines[start:consumed]]
        result.append(
            WindowInput(
                channel=channel,
                lines=tuple(context) + tuple(group),
                open_items=tuple(open_items),
                entrance_hint=entrance_hint,
            )
        )
        consumed += len(group)
    return result
