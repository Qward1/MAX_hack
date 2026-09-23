"""D1: агрегаты реальных выгрузок домовых чатов — только числа, только локально.

    uv run python evaluation/d1_aggregates.py --structure <каталог>
    uv run python evaluation/d1_aggregates.py <каталог> --rub-per-window 0.30 --out <файл.json>

**Правила приватности (целевая архитектура v3 §12, P6 §4.4).**

- Скрипт не обращается в сеть и не импортирует провайдера модели: реальные
  реплики не покидают машину. Тест это проверяет.
- Печатается и сохраняется **только** числовая сводка: количества, доли,
  перцентили, диапазон по месяцам. Никаких текстов, имён, идентификаторов,
  названий чатов и файлов, дат с точностью до дня. Авторы различаются в памяти
  и нигде не выводятся. Тест проверяет, что в выводе нет строк из входа.
- `--structure` печатает только имена ключей и типы JSON (и счётчики форм
  строк для txt), а не значения.

Форматы: Telegram Desktop «Экспорт истории чата» (JSON, `messages[]`) и
WhatsApp «Экспорт чата» (txt: `ДД.ММ.ГГГГ, ЧЧ:ММ - Автор: текст` или
`[ДД.ММ.ГГ, ЧЧ:ММ:СС] Автор: текст`, продолжение сообщения — строки без даты).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from domsignal.ai.contracts import WindowLine  # noqa: E402
from domsignal.ai.rules.danger import screen_message_for_danger  # noqa: E402
from domsignal.ai.rules.lexicon import passes_recall_gate  # noqa: E402
from domsignal.ai.windowing import DEFAULT_POLICY, WindowPolicy, split_stream  # noqa: E402

_WA_ANDROID = re.compile(
    r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4}),? (\d{1,2}):(\d{2})(?::(\d{2}))? [-–] (.*)$"
)
_WA_IOS = re.compile(
    r"^‎?\[(\d{1,2})\.(\d{1,2})\.(\d{2,4}),? (\d{1,2}):(\d{2})(?::(\d{2}))?\] (.*)$"
)


@dataclass(frozen=True)
class Message:
    """Сообщение выгрузки в памяти. Наружу не выводится ни одно поле."""

    author: str
    text: str
    sent_at: datetime
    is_reply: bool


# ------------------------------------------------------------ структура


def _shape(value: Any, depth: int = 0) -> Any:
    """Имена ключей и типы без значений."""
    if isinstance(value, dict):
        if depth > 3:
            return "object"
        return {str(key): _shape(item, depth + 1) for key, item in sorted(value.items())}
    if isinstance(value, list):
        kinds = sorted({type(item).__name__ for item in value})
        sample = next((item for item in value if isinstance(item, dict)), None)
        return {"list_of": kinds, "len": len(value), "item": _shape(sample, depth + 1)}
    return type(value).__name__


def structure(root: pathlib.Path) -> dict[str, Any]:
    """Структура файлов выгрузок: форматы, ключи и типы — без значений и имён."""
    files: list[dict[str, Any]] = []
    for index, path in enumerate(_export_files(root), start=1):
        entry: dict[str, Any] = {"file": index, "suffix": path.suffix.lower()}
        entry["size_mb"] = round(path.stat().st_size / 1_000_000, 1)
        if path.suffix.lower() == ".json":
            document = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(document, dict):
                entry["keys"] = {
                    str(key): _shape(value) for key, value in sorted(document.items())
                }
                messages = document.get("messages")
                if isinstance(messages, list):
                    keys: Counter[str] = Counter()
                    types: dict[str, set[str]] = {}
                    for item in messages:
                        if isinstance(item, dict):
                            for key, value in item.items():
                                keys[str(key)] += 1
                                types.setdefault(str(key), set()).add(type(value).__name__)
                    entry["message_keys"] = {
                        key: {"count": count, "types": sorted(types[key])}
                        for key, count in sorted(keys.items())
                    }
        else:
            forms: Counter[str] = Counter()
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if _WA_ANDROID.match(raw):
                    forms["dated_android"] += 1
                elif _WA_IOS.match(raw):
                    forms["dated_ios"] += 1
                elif raw.strip():
                    forms["continuation"] += 1
                else:
                    forms["empty"] += 1
            entry["line_forms"] = dict(sorted(forms.items()))
        files.append(entry)
    return {"files": files}


def _export_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in (".json", ".txt")
    )


# ---------------------------------------------------------------- разбор


def _telegram_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            item if isinstance(item, str) else str(item.get("text", ""))
            for item in value
            if isinstance(item, str | dict)
        )
    return ""


def parse_telegram(document: dict[str, Any]) -> list[Message]:
    messages: list[Message] = []
    for item in document.get("messages", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        text = _telegram_text(item.get("text")).strip()
        if not text:
            continue
        stamp = item.get("date_unixtime")
        if isinstance(stamp, str) and stamp.isdigit():
            sent_at = datetime.fromtimestamp(int(stamp), tz=UTC)
        else:
            sent_at = datetime.fromisoformat(str(item["date"])).replace(tzinfo=UTC)
        author = str(item.get("from_id") or item.get("from") or "?")
        messages.append(
            Message(
                author=author,
                text=text,
                sent_at=sent_at,
                is_reply=item.get("reply_to_message_id") is not None,
            )
        )
    return messages


def _wa_datetime(match: re.Match[str]) -> datetime:
    day, month, year, hour, minute, second = match.groups()[:6]
    full_year = int(year) + (2000 if len(year) == 2 else 0)
    return datetime(
        full_year, int(month), int(day), int(hour), int(minute), int(second or 0), tzinfo=UTC
    )


def parse_whatsapp(text: str) -> list[Message]:
    """Сообщения WhatsApp; служебные строки (без «Автор: ») пропускаются."""
    messages: list[Message] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        if current is not None and current["text"].strip():
            messages.append(
                Message(
                    author=current["author"],
                    text=current["text"].strip(),
                    sent_at=current["sent_at"],
                    is_reply=False,
                )
            )

    for raw in text.splitlines():
        match = _WA_ANDROID.match(raw) or _WA_IOS.match(raw)
        if match:
            flush()
            rest = match.group(7)
            author, separator, body = rest.partition(": ")
            if not separator:
                current = None  # служебная строка: добавил(а), сменил(а) тему…
                continue
            if body.strip() in ("<Без медиафайлов>", "<Media omitted>", "<Медиа отсутствуют>"):
                current = None
                continue
            current = {"author": author, "text": body, "sent_at": _wa_datetime(match)}
        elif current is not None:
            current["text"] += "\n" + raw
    flush()
    return messages


def load_messages(path: pathlib.Path) -> tuple[str, list[Message]]:
    if path.suffix.lower() == ".json":
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and isinstance(document.get("messages"), list):
            return "telegram", parse_telegram(document)
        return "unknown_json", []
    return "whatsapp", parse_whatsapp(path.read_text(encoding="utf-8", errors="replace"))


# --------------------------------------------------------------- агрегаты


def _percentiles(values: Sequence[float], shares: Iterable[float]) -> dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    result: dict[str, float] = {}
    for share in shares:
        index = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
        result[f"p{int(share * 100)}"] = round(float(ordered[index]), 2)
    return result


def aggregate(
    messages: Sequence[Message],
    *,
    policy: WindowPolicy = DEFAULT_POLICY,
    rub_per_window: float | None = None,
) -> dict[str, Any]:
    """Только числа. Ни одна строка входа не попадает в результат."""
    ordered = sorted(messages, key=lambda item: item.sent_at)
    total = len(ordered)
    if total == 0:
        return {"messages": 0}
    lines = [
        WindowLine(
            line_id=f"l{index}",
            author_ref=f"a{index}",
            text=message.text[:4000],
            sent_at=message.sent_at,
        )
        for index, message in enumerate(ordered)
    ]
    windows = split_stream(lines, policy)
    days = sorted({message.sent_at.date() for message in ordered})
    calendar_days = (days[-1] - days[0]).days + 1
    windows_by_day: Counter[Any] = Counter(window[0].sent_at.date() for window in windows)
    per_active_day = [windows_by_day[day] for day in days]
    danger_active = danger_displaced = danger_negated = 0
    gate = 0
    for message in ordered:
        hits = screen_message_for_danger(message.text)
        if any(not hit.negated and not hit.displaced for hit in hits):
            danger_active += 1
        elif any(not hit.negated and hit.displaced for hit in hits):
            danger_displaced += 1
        elif hits:
            danger_negated += 1
        gate += int(passes_recall_gate(message.text))
    windows_per_calendar_day = len(windows) / calendar_days
    months = sorted({message.sent_at.strftime("%Y-%m") for message in ordered})
    summary: dict[str, Any] = {
        "messages": total,
        "authors": len({message.author for message in ordered}),
        "months": {"first": months[0], "last": months[-1], "active_months": len(months)},
        "active_days": len(days),
        "calendar_days": calendar_days,
        "reply_share": round(sum(message.is_reply for message in ordered) / total, 4),
        "length_chars": _percentiles(
            [len(message.text) for message in ordered], (0.1, 0.5, 0.9, 0.99)
        ),
        "windows": {
            "policy": {
                "silence_seconds": policy.silence_seconds,
                "max_lines": policy.max_lines,
                "max_age_seconds": policy.max_age_seconds,
            },
            "total": len(windows),
            "per_calendar_day_mean": round(windows_per_calendar_day, 2),
            "per_active_day": _percentiles(per_active_day, (0.5, 0.9, 0.99)),
            "per_active_day_max": max(per_active_day),
            "lines_per_window": {
                "mean": round(statistics.mean(len(window) for window in windows), 2),
                **_percentiles([len(window) for window in windows], (0.5, 0.9, 0.99)),
            },
        },
        "danger_rules_per_1000": {
            "active": round(1000 * danger_active / total, 2),
            "displaced_only": round(1000 * danger_displaced / total, 2),
            "negated_only": round(1000 * danger_negated / total, 2),
        },
        "recall_gate_share": round(gate / total, 4),
        "model_calls_per_day": {
            "mean_calendar_day": round(windows_per_calendar_day, 2),
            "p90_active_day": _percentiles(per_active_day, (0.9,)).get("p90"),
        },
    }
    if rub_per_window is not None:
        summary["rub_per_month_estimate"] = {
            "rub_per_window": rub_per_window,
            "mean": round(windows_per_calendar_day * 30 * rub_per_window, 1),
        }
    return summary


def run(root: pathlib.Path, rub_per_window: float | None) -> dict[str, Any]:
    chats: list[dict[str, Any]] = []
    for index, path in enumerate(_export_files(root), start=1):
        kind, messages = load_messages(path)
        entry = {"chat": index, "format": kind}
        entry.update(aggregate(messages, rub_per_window=rub_per_window))
        chats.append(entry)
    return {"chats": chats, "note": "только агрегаты; тексты, имена и даты не выводятся"}


def main() -> None:
    parser = argparse.ArgumentParser(description="D1 aggregates of real chat exports (local only)")
    parser.add_argument("root", type=pathlib.Path)
    parser.add_argument("--structure", action="store_true")
    parser.add_argument("--rub-per-window", type=float, default=None)
    parser.add_argument("--out", type=pathlib.Path, default=None)
    args = parser.parse_args()
    result = structure(args.root) if args.structure else run(args.root, args.rub_per_window)
    body = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(body.encode("utf-8"))
    print(body, end="")


if __name__ == "__main__":
    main()
