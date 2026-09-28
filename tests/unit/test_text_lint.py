"""F1 §2.4: текстовый линтер ловит каждый класс дефектов и не шумит на коде."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import text_lint  # noqa: E402

from domsignal.services.bot_replies import count_label  # noqa: E402


@pytest.fixture(scope="module")
def checker() -> text_lint.Checker:
    return text_lint.Checker()


def kinds(checker: text_lint.Checker, value: str, *, python: bool = False) -> list[str]:
    text = text_lint.Text(ROOT / "x.tsx", 1, value)
    return [issue.kind for issue in checker.check(text, python=python)]


def test_each_defect_class_is_reported(checker: text_lint.Checker) -> None:
    assert "пунктуация" in kinds(checker, "Заявка создана.. Ждите ответа")
    assert "пробел перед знаком" in kinds(checker, "Заявка создана , ждите ответа")
    assert "служебное слово в тексте" in kinds(checker, "Исполнитель: undefined")
    assert "ё" in kinds(checker, "Чат еще не подключен")
    assert "орфография" in kinds(checker, "Новая заяфка в доме")
    assert "число без склонения" in kinds(checker, "`${items.length} заявок`")
    assert "число без склонения" in kinds(checker, 'f"{len(rows)} сообщений"', python=True)


def test_correct_texts_pass(checker: text_lint.Checker) -> None:
    for value in (
        "Чат подключён, заявка ждёт исполнителя.",
        "Все жители видят статус…",
        "Открыть заявку ${ticket.number}: подробности",
        "Проблема решена — спасибо!",
        "ДомСигнал не заменяет экстренные службы.",
    ):
        assert kinds(checker, value) == [], value


def test_scanner_reads_jsx_text_and_skips_comments_and_regexes() -> None:
    source = """
    // Комментарий с ошибкой заяфка
    const re = /[^а-я"']+/g;
    /* ещё комментарий, еще */
    const label = "Подключено";
    return <p>Заявок нет {count} <b>совсем</b></p>;
    """
    found = [(kind, text) for _line, kind, text in text_lint.scan_ts(source)]
    assert ("str", "Подключено") in found
    assert ("jsx", "Заявок нет") in found
    assert ("jsx", "совсем") in found
    assert all("заяфка" not in text and "еще" not in text for _kind, text in found)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "1 сообщение"),
        (3, "3 сообщения"),
        (5, "5 сообщений"),
        (11, "11 сообщений"),
        (21, "21 сообщение"),
    ],
)
def test_count_label(count: int, expected: str) -> None:
    assert count_label(count, ("сообщение", "сообщения", "сообщений")) == expected


def test_product_texts_are_clean() -> None:
    assert text_lint.main([]) == 0
