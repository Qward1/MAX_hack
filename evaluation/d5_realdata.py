"""D5 §2: реальные выгрузки домовых чатов — окна по политике production,
правила без модели, профиль нагрузки. Только числа, только локально.

    uv run python evaluation/d5_realdata.py <выгрузка> [<выгрузка> ...] \\
        --out evaluation/reports/2026-09-27-d1-realdata.json \\
        --profile-out evaluation/reports/2026-09-27-d1-load-profile.json

Выгрузка — файл или каталог: Telegram (JSON), WhatsApp (txt или zip с txt).

**Приватность** (как `d1_aggregates.py`, разрешение владельца 26.09 п. 4):

- ни сети, ни провайдера модели: реплики не покидают машину;
- наружу — только количества, доли, перцентили и распределения по часам;
  ни текстов, ни имён, ни идентификаторов, ни дат с точностью до дня;
- две выгрузки одного чата (повторный экспорт) не считаются дважды: чат
  определяется по совпадению отметок времени сообщений, а не по имени файла.

Каждое число помечено: «наблюдение, N чатов» — измерено по выгрузке;
«оценка правилами» — правила продукта без модели и без разметки людьми.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import pathlib
import statistics
import sys
import zipfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from evaluation.d1_aggregates import Message, parse_telegram, parse_whatsapp  # noqa: E402

#: Политика окна production (P6, OWNER-DECISION-2026-09-24): тишина 30 с, до 6
#: реплик, возраст окна до 300 с, опасность закрывает окно сразу.
PRODUCTION_SILENCE = 30
PRODUCTION_MAX_LINES = 6
PRODUCTION_MAX_AGE = 300
#: Пауза памятки того же вида в тот же чат (PASSIVE_CHAT_MEMO_PAUSE_MINUTES).
MEMO_PAUSE = timedelta(minutes=30)
#: Стоимость окна: P6 (window.v2, flex) и P6c (window.v3, в production).
RUB_PER_WINDOW = {"p6_window_v2": 0.055, "p6c_window_v3": 0.081}
MSK = timezone(timedelta(hours=3))
ROOT = pathlib.Path(__file__).resolve().parents[1]

OBSERVED = "наблюдение"
RULES = "оценка правилами, без разметки людьми"


@dataclass(frozen=True)
class Chat:
    """Сообщения чата в памяти: время — в МСК-часах для распределения по суткам."""

    kind: str
    messages: list[Message]
    #: Час суток отправки по местному времени чата.
    local_hours: list[int]


# ----------------------------------------------------------------- загрузка


def _load_path(path: pathlib.Path) -> list[Chat]:
    chats: list[Chat] = []
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.suffix.lower() in {".json", ".txt", ".zip"}:
                chats.extend(_load_path(child))
        return chats
    suffix = path.suffix.lower()
    if suffix == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and isinstance(document.get("messages"), list):
            messages = parse_telegram(document)
            # Telegram хранит время в UTC; час суток — по Москве.
            hours = [m.sent_at.astimezone(MSK).hour for m in messages]
            chats.append(Chat("telegram", messages, hours))
    elif suffix == ".txt":
        messages = parse_whatsapp(path.read_text(encoding="utf-8", errors="replace"))
        # WhatsApp пишет местное время телефона без пояса: час берётся как есть.
        chats.append(Chat("whatsapp", messages, [m.sent_at.hour for m in messages]))
    elif suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".txt"):
                    raw = archive.read(name).decode("utf-8", errors="replace")
                    messages = parse_whatsapp(raw)
                    chats.append(Chat("whatsapp", messages, [m.sent_at.hour for m in messages]))
    return [chat for chat in chats if chat.messages]


def _fingerprint(chat: Chat) -> set[str]:
    """Отметки времени и длины сообщений — для поиска повторного экспорта."""
    return {
        hashlib.sha256(f"{m.sent_at.isoformat()}|{len(m.text)}".encode()).hexdigest()[:16]
        for m in chat.messages
    }


def load_chats(paths: Iterable[pathlib.Path]) -> tuple[list[Chat], dict[str, Any]]:
    """Чаты без повторов: из двух экспортов одного чата берётся более полный."""
    loaded = [chat for path in paths for chat in _load_path(path)]
    kept: list[tuple[Chat, set[str]]] = []
    merged = 0
    for chat in sorted(loaded, key=lambda item: -len(item.messages)):
        prints = _fingerprint(chat)
        duplicate = False
        for _other, other_prints in kept:
            overlap = len(prints & other_prints) / max(1, min(len(prints), len(other_prints)))
            if overlap >= 0.9:
                duplicate = True
                merged += 1
                break
        if not duplicate:
            kept.append((chat, prints))
    return [chat for chat, _ in kept], {
        "exports_read": len(loaded),
        "same_chat_reexports_skipped": merged,
        "chats": len(kept),
    }


# ----------------------------------------------------------------- расчёты


def quantiles(values: Sequence[float], shares: Iterable[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    out: dict[str, float] = {}
    for share in shares:
        index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
        out[f"p{round(share * 100):g}"] = round(float(ordered[index]), 3)
    return out


def split_windows(messages: Sequence[Message], danger: Sequence[bool]) -> list[list[int]]:
    """Окна по политике production: индексы сообщений. Как `ai.windowing.split_stream`."""
    windows: list[list[int]] = []
    current: list[int] = []
    for index, message in enumerate(messages):
        if current:
            silence = (message.sent_at - messages[current[-1]].sent_at).total_seconds()
            age = (message.sent_at - messages[current[0]].sent_at).total_seconds()
            if (
                silence > PRODUCTION_SILENCE
                or len(current) >= PRODUCTION_MAX_LINES
                or age > PRODUCTION_MAX_AGE
            ):
                windows.append(current)
                current = []
        current.append(index)
        if danger[index]:
            windows.append(current)
            current = []
    if current:
        windows.append(current)
    return windows


@dataclass
class RuleFacts:
    active: bool
    displaced: bool
    negated: bool
    memo_kinds: tuple[str, ...]
    gate: bool


def screen(messages: Sequence[Message]) -> list[RuleFacts]:
    from domsignal.ai.rules.danger import screen_message_for_danger
    from domsignal.ai.rules.lexicon import passes_recall_gate

    facts: list[RuleFacts] = []
    for message in messages:
        hits = screen_message_for_danger(message.text)
        facts.append(
            RuleFacts(
                active=any(not h.negated and not h.displaced for h in hits),
                displaced=any(not h.negated and h.displaced for h in hits),
                negated=bool(hits) and all(h.negated for h in hits),
                memo_kinds=tuple(sorted({h.kind for h in hits if h.chat_memo_eligible})),
                gate=passes_recall_gate(message.text),
            )
        )
    return facts


def memos_by_pause(messages: Sequence[Message], facts: Sequence[RuleFacts]) -> int:
    """Памятки бота в чат: высокоточное срабатывание с паузой 30 мин на вид."""
    last: dict[str, datetime] = {}
    count = 0
    for message, fact in zip(messages, facts, strict=True):
        for kind in fact.memo_kinds:
            previous = last.get(kind)
            if previous is None or message.sent_at - previous >= MEMO_PAUSE:
                count += 1
                last[kind] = message.sent_at
    return count


def per_day(values: Counter[Any], first: datetime, last: datetime) -> list[int]:
    """Счётчики по календарным дням от первого до последнего, нули включены."""
    days = (last.date() - first.date()).days + 1
    return [values.get(first.date() + timedelta(days=offset), 0) for offset in range(days)]


async def rules_routes(messages: Sequence[Message], windows: Sequence[list[int]]) -> dict[str, Any]:
    """Подтипы по правилам и итог роутера для профиля RU-TA / kazan / mixed."""
    from domsignal.ai import WindowAnalyzer
    from domsignal.ai.contracts import WindowInput, WindowLine
    from domsignal.core.routing import HouseRoutingContext
    from domsignal.services.routing import RoutingService, load_directory_or_none

    root = ROOT
    routing = RoutingService(load_directory_or_none(root / "regions"))
    house = HouseRoutingContext(
        has_active_connected_uk=True,
        region_code="RU-TA",
        municipality_code="kazan",
        territory_policy="mixed",
    )
    analyzer = WindowAnalyzer()  # только правила: провайдера нет
    windows_with_signal = 0
    subtypes: Counter[str] = Counter()
    routes: Counter[str] = Counter()
    for window in windows:
        lines = tuple(
            WindowLine(
                line_id=f"l{index}",
                author_ref=f"a{position}",
                text=messages[index].text[:4000],
                sent_at=messages[index].sent_at,
            )
            for position, index in enumerate(window)
        )
        analysis = await analyzer.analyze(WindowInput(channel="group_passive", lines=lines))
        if analysis.signals:
            windows_with_signal += 1
        for signal in analysis.signals:
            subtypes[signal.subtype] += 1
            route = routing.route(
                subtype=signal.subtype,
                location_scope=signal.location_scope.value,
                house=house,
                danger_kinds=tuple(signal.emergency.kinds) if signal.emergency else (),
            )
            routes[route.route_type] += 1
    signals = sum(subtypes.values())
    outside = signals - routes.get("uk_internal", 0) - routes.get("unknown", 0)
    return {
        "label": RULES,
        "windows_with_rule_signal": windows_with_signal,
        "windows_with_rule_signal_share": round(windows_with_signal / max(1, len(windows)), 4),
        "signals": signals,
        "subtypes_top": dict(subtypes.most_common(15)),
        "route_types": dict(routes.most_common()),
        "outside_uk_share_of_routed": round(
            outside / max(1, signals - routes.get("unknown", 0)), 4
        ),
        "unknown_share": round(routes.get("unknown", 0) / max(1, signals), 4),
        "house_profile": "RU-TA / kazan / mixed, УК подключена",
    }


def chat_numbers(chat: Chat) -> dict[str, Any]:
    ordered = sorted(
        zip(chat.messages, chat.local_hours, strict=True), key=lambda item: item[0].sent_at
    )
    messages = [item[0] for item in ordered]
    hours = [item[1] for item in ordered]
    facts = screen(messages)
    danger_close = [fact.active for fact in facts]
    windows = split_windows(messages, danger_close)
    first, last = messages[0].sent_at, messages[-1].sent_at
    calendar_days = (last.date() - first.date()).days + 1
    msg_per_day = per_day(Counter(m.sent_at.date() for m in messages), first, last)
    win_per_day = per_day(Counter(messages[w[0]].sent_at.date() for w in windows), first, last)
    active = [value for value in msg_per_day if value]
    active_windows = [value for value in win_per_day if value]
    # Распределение по часам и доля часа пик внутри суток.
    by_hour = Counter(hours)
    daily_hour: dict[Any, Counter[int]] = {}
    for message, hour in zip(messages, hours, strict=True):
        daily_hour.setdefault(message.sent_at.date(), Counter())[hour] += 1
    peak_shares = [max(c.values()) / sum(c.values()) for c in daily_hour.values()]
    busy_days = [c for c in daily_hour.values() if sum(c.values()) >= 20]
    busy_peak = [max(c.values()) / sum(c.values()) for c in busy_days]
    # Интервалы между сообщениями и всплески по минутам.
    gaps = [
        (b.sent_at - a.sent_at).total_seconds()
        for a, b in zip(messages, messages[1:], strict=False)
    ]
    within = [gap for gap in gaps if gap <= PRODUCTION_SILENCE]
    minutes = Counter(m.sent_at.replace(second=0, microsecond=0) for m in messages)
    ten = Counter(
        m.sent_at.replace(minute=m.sent_at.minute // 10 * 10, second=0, microsecond=0)
        for m in messages
    )
    lines_per_window = Counter(len(w) for w in windows)
    months = max(1.0, calendar_days / 30.4375)
    memos = memos_by_pause(messages, facts)
    gate_windows = sum(1 for w in windows if any(facts[i].gate for i in w))
    windows_per_month = len(windows) / months
    return {
        "format": chat.kind,
        "label": OBSERVED,
        "messages": len(messages),
        "authors": len({m.author for m in messages}),
        "calendar_days": calendar_days,
        "active_days": len(active),
        "reply_share": round(sum(m.is_reply for m in messages) / len(messages), 4),
        "messages_per_day": {
            "calendar": quantiles(msg_per_day, (0.5, 0.9, 0.99)),
            "calendar_mean": round(statistics.fmean(msg_per_day), 2),
            "active_day": quantiles(active, (0.5, 0.9, 0.99)),
            "max": max(msg_per_day),
        },
        "windows": {
            "policy": {
                "silence_seconds": PRODUCTION_SILENCE,
                "max_lines": PRODUCTION_MAX_LINES,
                "max_age_seconds": PRODUCTION_MAX_AGE,
                "close_on_danger": True,
            },
            "total": len(windows),
            "per_day_calendar": quantiles(win_per_day, (0.5, 0.9, 0.99)),
            "per_day_calendar_mean": round(statistics.fmean(win_per_day), 2),
            "per_day_active": quantiles(active_windows, (0.5, 0.9, 0.99)),
            "per_day_max": max(win_per_day),
            "lines_per_window_mean": round(statistics.fmean(len(w) for w in windows), 2),
            "lines_per_window_share": {
                str(size): round(lines_per_window[size] / len(windows), 4)
                for size in range(1, PRODUCTION_MAX_LINES + 1)
            },
        },
        "hours": {
            "timezone": "Europe/Moscow" if chat.kind == "telegram" else "местное время телефона",
            "share_by_hour": [round(by_hour[h] / len(messages), 4) for h in range(24)],
            "peak_hour": max(range(24), key=lambda h: by_hour[h]),
            "peak_hour_share_of_all": round(max(by_hour.values()) / len(messages), 4),
            "busiest_hour_share_of_day": quantiles(peak_shares, (0.5, 0.9)),
            "busiest_hour_share_of_day_20plus": quantiles(busy_peak, (0.5, 0.9)),
            "days_20plus_messages": len(busy_days),
        },
        "intervals_s": {
            "all": quantiles(gaps, (0.1, 0.25, 0.5, 0.75, 0.9, 0.99)),
            "within_window": quantiles(within, (0.1, 0.25, 0.5, 0.75, 0.9)),
            "share_within_30s": round(len(within) / max(1, len(gaps)), 4),
        },
        "bursts": {
            "per_minute_active": quantiles(list(minutes.values()), (0.5, 0.9, 0.99)),
            "per_minute_max": max(minutes.values()),
            "per_10min_active": quantiles(list(ten.values()), (0.5, 0.9, 0.99)),
            "per_10min_max": max(ten.values()),
        },
        "rules": {
            "label": RULES,
            "danger_per_1000": {
                "active": round(1000 * sum(f.active for f in facts) / len(messages), 2),
                "displaced_only": round(
                    1000 * sum(f.displaced and not f.active for f in facts) / len(messages), 2
                ),
                "negated_only": round(1000 * sum(f.negated for f in facts) / len(messages), 2),
            },
            "memo_eligible_messages": sum(bool(f.memo_kinds) for f in facts),
            "memos_with_30min_pause": memos,
            "memos_per_month": round(memos / months, 2),
            "operator_alerts_per_month": round(sum(f.active for f in facts) / months, 2),
        },
        "model": {
            "label": RULES,
            "note": "в production каждое закрытое окно — один вызов модели, фильтра до модели нет",
            "windows_per_month": round(windows_per_month, 1),
            "rub_per_month": {
                key: round(windows_per_month * price, 1) for key, price in RUB_PER_WINDOW.items()
            },
            "recall_gate_windows_share": round(gate_windows / len(windows), 4),
            "rub_per_month_if_gate": {
                key: round(gate_windows / months * price, 1)
                for key, price in RUB_PER_WINDOW.items()
            },
        },
        "_windows": windows,
        "_messages": messages,
    }


def load_profile(chats: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Профиль нагрузки для `scripts/load_ingest.py --profile`: только распределения."""
    busiest = max(chats, key=lambda item: item["messages"])
    hours = [0.0] * 24
    total = sum(chat["messages"] for chat in chats)
    for chat in chats:
        for hour, share in enumerate(chat["hours"]["share_by_hour"]):
            hours[hour] += share * chat["messages"] / total
    return {
        "label": f"{OBSERVED}, {len(chats)} чата; только распределения, без текстов",
        "source": "evaluation/d5_realdata.py",
        "window_policy": busiest["windows"]["policy"],
        "hourly_share": [round(value, 4) for value in hours],
        "peak_hour_share_of_day_p50": busiest["hours"]["busiest_hour_share_of_day_20plus"].get(
            "p50"
        ),
        "peak_hour_share_of_day_p90": busiest["hours"]["busiest_hour_share_of_day_20plus"].get(
            "p90"
        ),
        "intervals_s": busiest["intervals_s"],
        "bursts": busiest["bursts"],
        "reply_share": busiest["reply_share"],
        "lines_per_window_share": busiest["windows"]["lines_per_window_share"],
        "messages_per_day": {chat["format"]: chat["messages_per_day"] for chat in chats},
        "windows_per_day": {chat["format"]: chat["windows"]["per_day_calendar"] for chat in chats},
    }


def run(
    paths: Sequence[pathlib.Path],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    chats, dedupe = load_chats(paths)
    numbers = [chat_numbers(chat) for chat in chats]
    for entry in numbers:
        entry["routes"] = asyncio.run(rules_routes(entry["_messages"], entry["_windows"]))
    public = [{k: v for k, v in entry.items() if not k.startswith("_")} for entry in numbers]
    report = {
        "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "dedupe": dedupe,
        "labels": {"observed": OBSERVED, "rules": RULES},
        "chats": [{"chat": index, **entry} for index, entry in enumerate(public, start=1)],
    }
    return report, load_profile(public), numbers


def main() -> None:
    parser = argparse.ArgumentParser(description="D5 real chat aggregates (local only)")
    parser.add_argument("paths", nargs="+", type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    parser.add_argument("--profile-out", type=pathlib.Path)
    args = parser.parse_args()
    report, profile, _ = run(args.paths)
    for target, body in ((args.out, report), (args.profile_out, profile)):
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(
                (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
