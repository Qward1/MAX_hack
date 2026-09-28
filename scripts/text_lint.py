"""Проверка видимых текстов продукта (F1 §2.4).

Собирает кириллические строки из `miniapp/src/**/*.ts(x)` (литералы и JSX-текст,
без тестов и сгенерированной схемы) и из `src/domsignal/bot/**`, `services/**`
(строковые литералы без docstring) и проверяет:

- двойную пунктуацию и пробел перед знаком препинания;
- `undefined`, `null`, `NaN` внутри русского текста;
- «ё»: слово, которое словарь знает только с «ё» (ещё, подключён, ждёт), написано через «е»;
- формы числительных: число из `length/count/total…` прямо перед существительным
  без общего помощника склонения (`countLabel`, `pluralize`, `plural`);
- орфографию: слово неизвестно словарю pymorphy3 и не входит в белый список
  `scripts/text_lint_words.txt` (термины продукта, названия, сокращения).

    uv run python scripts/text_lint.py            # отчёт, код 1 при замечаниях
    uv run python scripts/text_lint.py --unknown  # только список неизвестных слов
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS_FILE = ROOT / "scripts" / "text_lint_words.txt"
CYR = re.compile(r"[А-Яа-яЁё]")
WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")

DOUBLE_PUNCT = re.compile(r"(?<![.…])\.\.(?![.\/])|,,|!!|\?\?|[,;:]\.|\.,|;;|::")
SPACE_BEFORE = re.compile(r"[А-Яа-яЁё0-9»)]\s+[,.;:!?](?=\s|$)")
NULLISH = re.compile(r"\b(undefined|null|NaN)\b")
NUMERIC_EXPR = r"[^{}]*\b(?:length|count|total|used|limit|remaining|size|len\()[^{}]*"
NOUNS = (
    r"(?:заяв|сигнал|проблем|дом(?:а|ов)?\b|чат|сообщен|жител|обращен|окн|сотрудник|"
    r"дн(?:я|ей)|минут|час|мест|факт|сосед|запрос|приглашен|участник|голос|раз\b|фото)"
)
PLURAL_TS = re.compile(r"\$?\{" + NUMERIC_EXPR + r"\}\s?" + NOUNS)
PLURAL_PY = re.compile(r"\{" + NUMERIC_EXPR + r"\}\s?" + NOUNS)


@dataclass(frozen=True)
class Text:
    path: Path
    line: int
    value: str


@dataclass(frozen=True)
class Issue:
    path: Path
    line: int
    kind: str
    detail: str

    def render(self) -> str:
        rel = self.path.relative_to(ROOT).as_posix()
        return f"{rel}:{self.line}: {self.kind}: {self.detail}"


# ---------------------------------------------------------------- сбор строк


def ts_files() -> list[Path]:
    base = ROOT / "miniapp" / "src"
    files = [*base.rglob("*.ts"), *base.rglob("*.tsx")]
    return sorted(
        p
        for p in files
        if ".test." not in p.name
        and p.name not in {"schema.ts", "vite-env.d.ts"}
        and "__tests__" not in p.parts
    )


def py_files() -> list[Path]:
    base = ROOT / "src" / "domsignal"
    return sorted([*(base / "bot").rglob("*.py"), *(base / "services").rglob("*.py")])


_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}


def scan_ts(source: str) -> Iterator[tuple[int, str, str]]:
    """Лексер TS/TSX: строки, шаблоны и JSX-текст вне комментариев.

    Выдаёт (строка, вид, текст): вид — "str" для литералов, "jsx" для текста между тегами.
    Регулярные выражения пропускаются по предыдущему значимому символу.
    """
    i, n, line = 0, len(source), 1
    code_start, code_line = 0, 1
    prev = ""

    def flush_code(end: int) -> Iterator[tuple[int, str, str]]:
        chunk = source[code_start:end]
        if CYR.search(chunk):
            offset = code_line
            for part in re.split(r"[{}<>]", chunk):
                if CYR.search(part):
                    at = chunk.find(part)
                    yield offset + chunk[:at].count("\n"), "jsx", " ".join(part.split())

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            yield from flush_code(i)
            j = source.find("\n", i)
            i = n if j < 0 else j
            code_start, code_line = i, line
            continue
        if c == "/" and nxt == "*":
            yield from flush_code(i)
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += source.count("\n", i, j)
            i = j
            code_start, code_line = i, line
            continue
        if c == "/" and prev in _REGEX_PREV:
            # Регулярное выражение: до закрывающей «/» вне класса символов.
            j, in_class = i + 1, False
            while j < n and source[j] != "\n":
                ch = source[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                j += 1
            if j < n and source[j] == "/":
                yield from flush_code(i)
                i = j + 1
                code_start, code_line = i, line
                prev = "/"
                continue
        if c in "'\"`":
            yield from flush_code(i)
            start_line = line
            j, buf = i + 1, []
            depth = 0
            while j < n:
                ch = source[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(source[j : j + 2])
                    j += 2
                    continue
                if ch == "\n":
                    line += 1
                    if c != "`":
                        break
                if c == "`" and ch == "$" and j + 1 < n and source[j + 1] == "{":
                    depth += 1
                    buf.append("${")
                    j += 2
                    continue
                if c == "`" and depth and ch == "}":
                    depth -= 1
                    buf.append("}")
                    j += 1
                    continue
                if ch == c and not depth:
                    break
                buf.append(ch)
                j += 1
            text = "".join(buf)
            if CYR.search(text):
                yield start_line, "str", text
            i = j + 1
            code_start, code_line = i, line
            prev = "a"
            continue
        if c == "\n":
            line += 1
        if not c.isspace():
            prev = c if not (c.isalnum() or c in "_$") else "a"
            if prev == "a":
                # «return /re/» — редкий случай, остальное после идентификатора — деление.
                word_end = i
                while word_end + 1 < n and (
                    source[word_end + 1].isalnum() or source[word_end + 1] == "_"
                ):
                    word_end += 1
                if source[i : word_end + 1] in {"return", "typeof", "case"}:
                    prev = ""
                i = word_end + 1
                continue
        i += 1
    yield from flush_code(n)


def collect_ts(path: Path) -> list[Text]:
    source = path.read_text(encoding="utf-8")
    return [Text(path, line, text) for line, _kind, text in scan_ts(source)]


def collect_py(path: Path) -> list[Text]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    out: list[Text] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings or not CYR.search(node.value):
                continue
            out.append(Text(path, node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            # f-строка целиком — для проверки чисел; части-константы проверяются выше.
            segment = ast.get_source_segment(source, node) or ""
            if CYR.search(segment):
                out.append(Text(path, node.lineno, segment))
    return out


# ---------------------------------------------------------------- проверки


class Checker:
    def __init__(self) -> None:
        import pymorphy3  # type: ignore[import-untyped]  # dev-зависимость линтера

        self.morph = pymorphy3.MorphAnalyzer()
        self.allowed = load_words()
        self._known: dict[str, bool] = {}
        self._yo: dict[str, str | None] = {}

    def known(self, word: str) -> bool:
        w = word.lower()
        if w not in self._known:
            self._known[w] = w in self.allowed or self.morph.word_is_known(w)
        return self._known[w]

    def yo_form(self, word: str) -> str | None:
        w = word.lower()
        if "е" not in w or "ё" in w:
            return None
        if w not in self._yo:
            # Слово, которое словарь знает только с «ё»: «все/всё» неоднозначно и не считается.
            forms = {p.word for p in self.morph.parse(w)}
            only = next(iter(forms)) if len(forms) == 1 else ""
            self._yo[w] = only if "ё" in only else None
        return self._yo[w]

    def check(self, text: Text, *, python: bool) -> Iterator[Issue]:
        value = text.value
        is_fstring = python and value[:2].lower() in {'f"', "f'", "rf", "fr"}
        # Подстановка — как число: «Открыть заявку ${n}:» не даёт ложного «пробела перед знаком».
        plain = re.sub(r"\$\{[^}]*\}", "1", value) if not python else value
        if is_fstring:
            plain = re.sub(r"\{[^}]*\}", " ", value[2:-1])
        if not is_fstring:
            for m in DOUBLE_PUNCT.finditer(plain):
                yield Issue(text.path, text.line, "пунктуация", snippet(plain, m.start()))
            for m in SPACE_BEFORE.finditer(plain):
                yield Issue(text.path, text.line, "пробел перед знаком", snippet(plain, m.start()))
            if CYR.search(plain) and (null := NULLISH.search(plain)):
                yield Issue(
                    text.path, text.line, "служебное слово в тексте", snippet(plain, null.start())
                )
        plural = PLURAL_PY if python else PLURAL_TS
        if found := plural.search(value):
            yield Issue(text.path, text.line, "число без склонения", found.group(0))
        if is_fstring:
            return
        words = WORD.findall(plain)
        for word in words:
            for part in word.split("-"):
                if (yo := self.yo_form(part)) is not None:
                    yield Issue(text.path, text.line, "ё", f"{part} → {yo}")
        # Орфография — только для фраз: одиночные токены бывают основами и ключами.
        if len(words) < 2:
            return
        for word in words:
            if word.isupper() or self.known(word):
                continue
            parts = word.split("-")
            if len(parts) > 1 and all(p.isupper() or self.known(p) for p in parts):
                continue
            yield Issue(text.path, text.line, "орфография", word)


def load_words() -> set[str]:
    if not WORDS_FILE.exists():
        return set()
    words = set()
    for raw in WORDS_FILE.read_text(encoding="utf-8").splitlines():
        entry = raw.split("#", 1)[0].strip().lower()
        if entry:
            words.add(entry)
    return words


def snippet(value: str, at: int) -> str:
    start = max(0, at - 25)
    return "…" + value[start : at + 25].replace("\n", " ") + "…"


def texts() -> Iterator[tuple[Text, bool]]:
    for path in ts_files():
        for text in collect_ts(path):
            yield text, False
    for path in py_files():
        for text in collect_py(path):
            yield text, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--unknown", action="store_true", help="только неизвестные слова с частотой"
    )
    args = parser.parse_args(argv)
    checker = Checker()
    issues: list[Issue] = []
    count = 0
    for text, python in texts():
        count += 1
        issues.extend(checker.check(text, python=python))
    if args.unknown:
        freq: dict[str, int] = {}
        for issue in issues:
            if issue.kind == "орфография":
                freq[issue.detail.lower()] = freq.get(issue.detail.lower(), 0) + 1
        for word, n in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"{n:4} {word}")
        return 0
    seen: set[tuple[str, int, str, str]] = set()
    for issue in issues:
        key = (str(issue.path), issue.line, issue.kind, issue.detail)
        if key in seen:
            continue
        seen.add(key)
        print(issue.render())
    print(f"text_lint: {count} строк, замечаний {len(seen)}", file=sys.stderr)
    return 1 if seen else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(main())
