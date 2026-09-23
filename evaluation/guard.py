"""Сторож данных: что вообще можно читать и что можно отправить во внешний API.

Правило одно и оно жёсткое (целевая архитектура v3 §12, решение владельца
[PASSIVE-CHAT-2026-09-20]):

- каталог `data/` — реальные выгрузки домовых чатов. Он не открывается ни
  одним скриптом оценки, ни для чтения, ни для отбора моделей;
- во внешний API уходят только строки с `synthetic: true` либо строки,
  прошедшие процедуру обезличивания: `origin: "real_derived_anonymized"` с
  отметкой, кто и когда проверил их вручную.

Проверка срабатывает на входе, а не «где-то дальше»: скрипт, которому дали
запрещённый путь или неразмеченную строку, обязан остановиться.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable, Sequence
from typing import Any

#: Каталог реальных выгрузок. Не читается никогда и ничем.
FORBIDDEN_DIR_NAME = "data"

#: Единственный каталог, из которого скрипты оценки читают наборы.
DATASETS_ROOT = pathlib.Path("datasets")

#: Пометка обезличенного фрагмента реального чата, проверенного человеком.
DERIVED_ORIGIN = "real_derived_anonymized"


class DataGuardError(RuntimeError):
    """Путь или строка не проходят правила приватности."""


def ensure_allowed_path(
    path: str | pathlib.Path, *, root: pathlib.Path | None = DATASETS_ROOT
) -> pathlib.Path:
    """Проверить путь набора.

    Отказ по `data/` — безусловный. Параметр `root` только сужает разрешённую
    область (по умолчанию — `datasets/`) и не может её расширить на `data/`.
    """
    resolved = pathlib.Path(path).resolve()
    if any(part.lower() == FORBIDDEN_DIR_NAME for part in resolved.parts):
        raise DataGuardError(
            f"путь ведёт в каталог реальных выгрузок и запрещён: {resolved.as_posix()}"
        )
    if root is not None:
        allowed = pathlib.Path(root).resolve()
        if any(part.lower() == FORBIDDEN_DIR_NAME for part in allowed.parts):
            raise DataGuardError("корень наборов не может указывать в каталог реальных выгрузок")
        if not resolved.is_relative_to(allowed):
            raise DataGuardError(
                f"набор читается только из {allowed.as_posix()}, а не из {resolved.as_posix()}"
            )
    return resolved


def row_is_allowed(row: dict[str, Any]) -> bool:
    """Можно ли отправить эту строку во внешний API."""
    if row.get("synthetic") is True:
        return True
    return (
        row.get("origin") == DERIVED_ORIGIN
        and bool(row.get("reviewed_by"))
        and bool(row.get("reviewed_at"))
    )


def ensure_allowed_rows(rows: Sequence[dict[str, Any]], *, source: str = "набор") -> None:
    """Остановиться, если хотя бы одна строка не помечена как разрешённая."""
    bad = [
        str(row.get("id", index))
        for index, row in enumerate(rows)
        if not row_is_allowed(row)
    ]
    if bad:
        shown = ", ".join(bad[:5]) + ("…" if len(bad) > 5 else "")
        raise DataGuardError(
            f"{source}: строки без `synthetic: true` и без проверенной пометки "
            f"`{DERIVED_ORIGIN}` — {shown}"
        )


def load_allowed_jsonl(
    path: str | pathlib.Path, *, root: pathlib.Path | None = DATASETS_ROOT
) -> list[dict[str, Any]]:
    """Прочитать JSONL набора после обеих проверок."""
    resolved = ensure_allowed_path(path, root=root)
    rows: list[dict[str, Any]] = []
    for line in resolved.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    ensure_allowed_rows(rows, source=resolved.name)
    return rows


class SliceBudgetExceeded(RuntimeError):
    """Лимит вызовов модели или рублей на срез исчерпан: вызова не будет."""


class SliceBudget:
    """Жёсткий общий лимит вызовов модели на весь срез, общий для всех прогонов.

    Счётчик живёт в JSON-файле, поэтому лимит действует на сумму всех запусков
    скриптов, а не на один процесс. Место резервируется **до** вызова: вызов,
    которому не хватило места, не делается. Рубли учитываются по факту
    (`usage.cost_rub` провайдера); неизвестная стоимость считается нулём и
    отдельно подсчитывается в `unknown_cost_calls`.
    """

    def __init__(self, path: pathlib.Path, *, max_calls: int, max_rub: float) -> None:
        self.path = path
        self.max_calls = max_calls
        self.max_rub = max_rub
        self.state: dict[str, Any] = {
            "max_calls": max_calls,
            "max_rub": max_rub,
            "calls": 0,
            "rub": 0.0,
            "unknown_cost_calls": 0,
            "runs": {},
        }
        if path.exists():
            self.state.update(json.loads(path.read_text(encoding="utf-8")))
            self.state["max_calls"], self.state["max_rub"] = max_calls, max_rub
        self._pending = 0

    @property
    def calls(self) -> int:
        return int(self.state["calls"])

    @property
    def rub(self) -> float:
        return float(self.state["rub"])

    def reserve(self) -> None:
        """Занять место под один вызов или остановиться."""
        if self.calls + self._pending >= self.max_calls:
            raise SliceBudgetExceeded(f"лимит вызовов среза: {self.calls}/{self.max_calls}")
        if self.rub >= self.max_rub:
            raise SliceBudgetExceeded(f"лимит рублей среза: {self.rub:.2f}/{self.max_rub:.0f}")
        self._pending += 1

    def commit(self, run: str, cost_rub: float | None) -> None:
        """Учесть сделанный вызов (даже неудачный: он мог быть оплачен)."""
        self._pending = max(0, self._pending - 1)
        self.state["calls"] = self.calls + 1
        self.state["rub"] = round(self.rub + (cost_rub or 0.0), 6)
        if cost_rub is None:
            self.state["unknown_cost_calls"] = int(self.state["unknown_cost_calls"]) + 1
        runs = self.state["runs"]
        entry = runs.setdefault(run, {"calls": 0, "rub": 0.0})
        entry["calls"] += 1
        entry["rub"] = round(entry["rub"] + (cost_rub or 0.0), 6)
        self.save()

    def release(self) -> None:
        """Отменить резерв: вызов не состоялся."""
        self._pending = max(0, self._pending - 1)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.path.write_bytes(body.encode("utf-8"))


def ensure_request_is_synthetic(texts: Iterable[str], allowed: Iterable[str]) -> None:
    """Последняя проверка перед вызовом модели: тексты взяты из разрешённых строк.

    Скрипт отбора собирает окна сам, поэтому перед отправкой сверяется, что
    каждая реплика действительно пришла из проверенного набора, а не из
    случайного источника.
    """
    known = set(allowed)
    unknown = [text for text in texts if text not in known]
    if unknown:
        raise DataGuardError(
            f"во внешний вызов попал текст не из синтетического набора ({len(unknown)} шт.)"
        )
