"""D5 §2.4: разметка окон реальных чатов — выборка, метрики, проверка согласия.

    uv run python evaluation/d5_labeling.py sample <выгрузки...> --dir data/labeling
    uv run python evaluation/d5_labeling.py metrics <выгрузки...> --dir data/labeling --out <json>
    uv run python evaluation/d5_labeling.py human-check <выгрузки...> --dir data/labeling
    uv run python evaluation/d5_labeling.py kappa --dir data/labeling

**Приватность** (разрешение владельца 26.09 п. 4). Тексты окон — только в
`data/labeling/` (каталог в .gitignore) и только маскированные: телефоны,
почта, ссылки, квартиры, госномера (`domsignal.ai.masking`), плюс здесь же
адреса, упоминания и имена; автор — «Житель A/B» внутри окна. Модели и
внешние API тексты не получают. `labels.csv` — только id окна и метки. Отчёт
`metrics` — только числа с интервалами Уилсона.

Выборка: окна по политике production (тишина 30 с, до 6 реплик), поровну из
чатов, зерно фиксировано. Основной слой — случайные окна; дополнительный —
окна, где правила нашли опасность (все с правом на памятку и случайные с
оповещением), чтобы оценить реальную долю ложных тревог.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import pathlib
import random
import re
import sys
from collections import Counter
from collections.abc import Sequence
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evaluation.d5_realdata import load_chats, screen, split_windows  # noqa: E402

SEED = 20260927
RANDOM_PER_CHAT = 100
DANGER_EXTRA_PER_CHAT = 30
HUMAN_CHECK = 50
LABEL_FIELDS = (
    "window_id",
    "stratum",
    "problem",
    "incident",
    "subtype",
    "addressee",
    "danger_now",
    "official_appeal",
    "status_question",
    "problem_lines",
    "problem_authors",
)
ADDRESSEES = ("uk", "municipality", "rso", "tko", "emergency", "unclear", "")

_ADDRESS = re.compile(
    r"(?<![а-яё])(ул\.?|улиц[аеуы]|пр-?т\.?|проспект[а-я]*|пер\.?|переул[а-я]*|бульвар[а-я]*|"
    r"наб\.?|набережн[а-я]*|шоссе|мкр\.?|микрорайон[а-я]*)\s+[А-ЯЁA-Z0-9][\w\-ёЁ]*",
    re.IGNORECASE,
)
_HOUSE = re.compile(r"(?<![а-яё])(дом|д\.|корпус|корп\.|к\.)\s*№?\s*\d+[а-яa-z]?", re.IGNORECASE)
_MENTION = re.compile(r"@\w+")
_NAME = re.compile(r"(?<=[^\s.!?…\n])(\s+)([А-ЯЁ][а-яё]{2,})")
#: Обращение в начале фразы: «Анна, …», «Виктор! …».
_VOCATIVE = re.compile(r"(^|[.!?…]\s+)([А-ЯЁ][а-яё]{2,})(?=\s*[,!])")
#: Слова с заглавной буквы, которые не имена: организации и сервисы оставляем.
_KEEP = {
    "УК",
    "ТСЖ",
    "МКД",
    "ГЖИ",
    "РСО",
    "МЧС",
    "Госуслуги",
    "Водоканал",
    "Горгаз",
    "Газ",
    "Вконтакте",
    "Телеграм",
    "Макс",
    "МАКС",
    "Дом",
    "Домофон",
    "Сбер",
    "Сбербанк",
    "Россети",
    "Спасибо",
    "Здравствуйте",
    "Добрый",
    "Пожалуйста",
    "Кто",
    "Что",
    "Где",
    "Когда",
    "Почему",
}


def mask(text: str) -> str:
    from domsignal.ai.masking import mask_text

    masked = mask_text(text)
    masked = _MENTION.sub("[упоминание]", masked)
    masked = _ADDRESS.sub("[адрес]", masked)
    masked = _HOUSE.sub("[дом]", masked)

    def name(match: re.Match[str]) -> str:
        word = match.group(2)
        return match.group(0) if word in _KEEP else match.group(1) + "[имя]"

    masked = _NAME.sub(name, masked)

    def vocative(match: re.Match[str]) -> str:
        word = match.group(2)
        return match.group(0) if word in _KEEP else match.group(1) + "[имя]"

    return _VOCATIVE.sub(vocative, masked)


def alias(index: int) -> str:
    from domsignal.ai.masking import author_alias

    return f"Житель {author_alias(index)}"


def build(paths: Sequence[pathlib.Path]) -> list[dict[str, Any]]:
    """Выборка окон (детерминированно): id, слой, маскированные реплики, выводы правил."""
    chats, _ = load_chats(paths)
    rng = random.Random(SEED)
    sample: list[dict[str, Any]] = []
    for chat_index, chat in enumerate(chats, start=1):
        messages = sorted(chat.messages, key=lambda item: item.sent_at)
        facts = screen(messages)
        windows = split_windows(messages, [fact.active for fact in facts])
        order = list(range(len(windows)))
        rng.shuffle(order)
        picked = order[:RANDOM_PER_CHAT]
        chosen = {index: "random" for index in picked}
        memo = [i for i, w in enumerate(windows) if any(facts[j].memo_kinds for j in w)]
        alerts = [i for i, w in enumerate(windows) if any(facts[j].active for j in w)]
        extra = [i for i in memo if i not in chosen]
        rest = [i for i in alerts if i not in chosen and i not in extra]
        rng.shuffle(rest)
        extra += rest[: max(0, DANGER_EXTRA_PER_CHAT - len(extra))]
        for index in extra[:DANGER_EXTRA_PER_CHAT]:
            chosen.setdefault(index, "danger")
        for index, stratum in sorted(chosen.items()):
            window = windows[index]
            authors: dict[str, int] = {}
            lines = []
            for position in window:
                message = messages[position]
                who = authors.setdefault(message.author, len(authors))
                lines.append({"author": alias(who), "text": mask(message.text)})
            sample.append(
                {
                    "window_id": f"c{chat_index}-w{index}",
                    "stratum": stratum,
                    "lines": lines,
                    "rules": {
                        "danger_active": any(facts[j].active for j in window),
                        "memo": any(facts[j].memo_kinds for j in window),
                    },
                    "_window": window,
                    "_messages": messages,
                }
            )
    return sample


async def rules_signals(sample: list[dict[str, Any]]) -> None:
    """Правила продукта без модели: есть ли сигнал и его подтип (на исходном тексте)."""
    from domsignal.ai import WindowAnalyzer
    from domsignal.ai.contracts import WindowInput, WindowLine

    analyzer = WindowAnalyzer()
    for item in sample:
        messages = item["_messages"]
        lines = tuple(
            WindowLine(
                line_id=f"l{position}",
                author_ref=f"a{position}",
                text=messages[index].text[:4000],
                sent_at=messages[index].sent_at,
            )
            for position, index in enumerate(item["_window"])
        )
        analysis = await analyzer.analyze(WindowInput(channel="group_passive", lines=lines))
        item["rules"]["signal"] = bool(analysis.signals)
        item["rules"]["subtypes"] = sorted({signal.subtype for signal in analysis.signals})


def taxonomy_codes() -> set[str]:
    from domsignal.ai.taxonomy import load_taxonomy

    return {subtype.code for subtype in load_taxonomy().subtypes}


def wilson(successes: int, total: int, z: float = 1.96) -> dict[str, Any]:
    if total == 0:
        return {"k": 0, "n": 0, "share": None, "ci95": None}
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {
        "k": successes,
        "n": total,
        "share": round(p, 4),
        "ci95": [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)],
    }


def read_labels(path: pathlib.Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["window_id"]: row for row in csv.DictReader(handle)}


def flag(row: dict[str, str], field: str) -> bool:
    return row.get(field, "").strip() in {"1", "да", "yes", "true"}


def metrics(sample: list[dict[str, Any]], labels: dict[str, dict[str, str]]) -> dict[str, Any]:
    labelled = [item for item in sample if item["window_id"] in labels]
    random_items = [item for item in labelled if item["stratum"] == "random"]
    danger_items = [item for item in labelled if item["rules"]["danger_active"]]
    problems = [item for item in random_items if flag(labels[item["window_id"]], "problem")]
    addressed = [
        item
        for item in problems
        if labels[item["window_id"]].get("addressee") not in {"", "unclear", None}
    ]
    outside = [item for item in addressed if labels[item["window_id"]]["addressee"] != "uk"]
    incidents: Counter[str] = Counter(
        labels[item["window_id"]]["incident"]
        for item in labelled
        if flag(labels[item["window_id"]], "problem") and labels[item["window_id"]].get("incident")
    )
    lines_on = [int(labels[i["window_id"]].get("problem_lines") or 0) for i in problems]
    authors_on = [int(labels[i["window_id"]].get("problem_authors") or 0) for i in problems]
    # Качество правил на случайных окнах: сигнал правил против метки «есть проблема».
    tp = sum(
        1 for i in random_items if i["rules"]["signal"] and flag(labels[i["window_id"]], "problem")
    )
    fp = sum(
        1
        for i in random_items
        if i["rules"]["signal"] and not flag(labels[i["window_id"]], "problem")
    )
    fn = sum(
        1
        for i in random_items
        if not i["rules"]["signal"] and flag(labels[i["window_id"]], "problem")
    )
    both = [
        i
        for i in random_items + [d for d in danger_items if d["stratum"] == "danger"]
        if i["rules"]["signal"]
        and flag(labels[i["window_id"]], "problem")
        # «danger.fire» и пустой подтип — метки вне таксономии: не сравниваются.
        and labels[i["window_id"]].get("subtype", "") in taxonomy_codes()
    ]
    subtype_match = sum(
        1 for i in both if labels[i["window_id"]]["subtype"] in i["rules"]["subtypes"]
    )
    memo_items = [item for item in labelled if item["rules"]["memo"]]
    by_addressee = Counter(labels[i["window_id"]].get("addressee") or "unclear" for i in problems)
    return {
        "label": "разметка ИИ-агентом по маскированным текстам, не людьми",
        "sample": {
            "chats": len({item["window_id"].split("-")[0] for item in labelled}),
            "random_windows": len(random_items),
            "danger_stratum_windows": sum(1 for i in labelled if i["stratum"] == "danger"),
            "policy": "тишина 30 с, до 6 реплик, 300 с, опасность закрывает окно",
            "seed": SEED,
        },
        "problem_share_of_windows": wilson(len(problems), len(random_items)),
        "problem_lines_per_window": {
            "mean": round(sum(lines_on) / len(lines_on), 2) if lines_on else None,
            "multi_line_share": wilson(sum(1 for v in lines_on if v >= 2), len(lines_on)),
        },
        "problem_authors_per_window": {
            "mean": round(sum(authors_on) / len(authors_on), 2) if authors_on else None,
            "multi_author_share": wilson(sum(1 for v in authors_on if v >= 2), len(authors_on)),
        },
        "incidents_in_sample": {
            "incidents": len(incidents),
            "windows_per_incident_max": max(incidents.values()) if incidents else 0,
            "incidents_with_2plus_windows": sum(1 for v in incidents.values() if v >= 2),
        },
        "outside_uk_share": wilson(len(outside), len(addressed)),
        "addressee_counts": dict(by_addressee),
        "official_appeal_share": wilson(
            sum(1 for i in problems if flag(labels[i["window_id"]], "official_appeal")),
            len(problems),
        ),
        "status_question_share": wilson(
            sum(1 for i in problems if flag(labels[i["window_id"]], "status_question")),
            len(problems),
        ),
        "rules_quality": {
            "label": "правила продукта без модели против разметки агента",
            "problem_precision": wilson(tp, tp + fp),
            "problem_recall": wilson(tp, tp + fn),
            "subtype_match": wilson(subtype_match, len(both)),
            "danger_alert_false_share": wilson(
                sum(1 for i in danger_items if not flag(labels[i["window_id"]], "danger_now")),
                len(danger_items),
            ),
            "memo_false_share": wilson(
                sum(1 for i in memo_items if not flag(labels[i["window_id"]], "danger_now")),
                len(memo_items),
            ),
        },
    }


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    if not a:
        return None
    total = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / total
    counts_a, counts_b = Counter(a), Counter(b)
    expected = sum(counts_a[k] * counts_b.get(k, 0) for k in counts_a) / (total * total)
    return round((observed - expected) / (1 - expected), 4) if expected < 1 else 1.0


def write_sample(sample: list[dict[str, Any]], directory: pathlib.Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "windows_masked.jsonl").open("w", encoding="utf-8") as handle:
        for item in sample:
            public = {k: v for k, v in item.items() if not k.startswith("_")}
            handle.write(json.dumps(public, ensure_ascii=False) + "\n")
    labels = directory / "labels.csv"
    if not labels.exists():
        with labels.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
            writer.writeheader()
            for item in sample:
                writer.writerow({"window_id": item["window_id"], "stratum": item["stratum"]})


def human_check(sample: list[dict[str, Any]], directory: pathlib.Path) -> pathlib.Path:
    """Страница для разметки людьми 50 окон (маскированный текст, только локально)."""
    rng = random.Random(SEED + 1)
    chosen = [item for item in sample if item["stratum"] == "random"]
    rng.shuffle(chosen)
    chosen = sorted(chosen[:HUMAN_CHECK], key=lambda item: item["window_id"])
    blocks = []
    for item in chosen:
        lines = "".join(
            f"<p><b>{html.escape(line['author'])}:</b> {html.escape(line['text'])}</p>"
            for line in item["lines"]
        )
        wid = html.escape(item["window_id"])

        def yes_no(name: str, wid: str = wid) -> str:
            return (
                f"<label><input type=radio name='{wid}:{name}' value=1>да</label> "
                f"<label><input type=radio name='{wid}:{name}' value=0>нет</label>"
            )

        options = "".join(f"<option value='{a}'>{a or '—'}</option>" for a in ADDRESSEES)
        blocks.append(
            f"<section data-id='{wid}'><h2>{wid}</h2>{lines}"
            f"<div>Проблема дома: {yes_no('problem')}</div>"
            f"<div>Адресат: <select name='{wid}:addressee'>{options}</select></div>"
            f"<div>Опасность сейчас: {yes_no('danger_now')}</div>"
            f"<div>Официальное обращение: {yes_no('official_appeal')}</div>"
            f"<div>Вопрос о статусе: {yes_no('status_question')}</div></section>"
        )
    page = (
        "<!doctype html><meta charset=utf-8><title>Проверка разметки</title>"
        "<style>body{font:15px/1.5 system-ui;max-width:760px;margin:24px auto;padding:0 16px}"
        "section{border-top:1px solid #ccc;padding:12px 0}h2{font-size:14px;color:#555}</style>"
        "<h1>Разметка 50 окон людьми</h1><p>Тексты замаскированы. Файл только локальный: "
        "не пересылайте его. Кнопка внизу сохраняет human_labels.csv.</p>"
        + "".join(blocks)
        + "<button id=save>Сохранить human_labels.csv</button><script>"
        "document.getElementById('save').onclick=()=>{const f=['window_id','problem','addressee',"
        "'danger_now','official_appeal','status_question'];const rows=[f.join(',')];"
        "document.querySelectorAll('section').forEach(s=>{const id=s.dataset.id;"
        "const v=n=>{const e=s.querySelector(`[name='${id}:${n}']:checked`)||"
        "s.querySelector(`select[name='${id}:${n}']`);return e?e.value:''};"
        "rows.push([id,...f.slice(1).map(v)].join(','))});"
        "const a=document.createElement('a');"
        "a.href=URL.createObjectURL(new Blob([rows.join('\\n')],{type:'text/csv'}));"
        "a.download='human_labels.csv';a.click()};</script>"
    )
    target = directory / "human_check.html"
    target.write_text(page, encoding="utf-8")
    return target


def kappa(directory: pathlib.Path) -> dict[str, Any]:
    agent = read_labels(directory / "labels.csv")
    human = read_labels(directory / "human_labels.csv")
    common = sorted(set(agent) & set(human))
    result: dict[str, Any] = {"windows": len(common)}
    for field in ("problem", "addressee", "danger_now", "official_appeal", "status_question"):
        pairs = [
            (agent[w].get(field, ""), human[w].get(field, ""))
            for w in common
            if human[w].get(field, "") != ""
        ]
        result[field] = {
            "n": len(pairs),
            "kappa": cohen_kappa([a for a, _ in pairs], [h for _, h in pairs]),
        }
    return result


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description="D5 labeling of real chat windows (local only)")
    parser.add_argument("command", choices=("sample", "metrics", "human-check", "kappa"))
    parser.add_argument("paths", nargs="*", type=pathlib.Path)
    parser.add_argument("--dir", type=pathlib.Path, default=pathlib.Path("data/labeling"))
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    if args.command == "kappa":
        body: Any = kappa(args.dir)
    else:
        sample = build(args.paths)
        if args.command == "sample":
            asyncio.run(rules_signals(sample))
            write_sample(sample, args.dir)
            body = {"windows": len(sample), "dir": str(args.dir)}
        elif args.command == "human-check":
            body = {"page": str(human_check(sample, args.dir))}
        else:
            asyncio.run(rules_signals(sample))
            body = metrics(sample, read_labels(args.dir / "labels.csv"))
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(text.encode("utf-8"))
    sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    main()
