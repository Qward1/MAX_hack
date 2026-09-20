"""Запреты формулировок и форма контракта явного пути.

Продукт не подаёт обращение за человека и не подтверждает внешнюю регистрацию.
Проверка идёт по самим шаблонам, а не только по собранным ответам: так
запрещённая формулировка не проедет в новой константе мимо сценарных тестов.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import CodeType, ModuleType

import pytest

from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.contracts.incidents import ReportCreated
from domsignal.core.incidents import ClassificationMode
from domsignal.services import (
    action_cards,
    appeal_drafts,
    explicit_reports,
    notification_render,
    route_card_render,
)
from domsignal.services.action_cards import FORBIDDEN_PHRASES

TEMPLATE_MODULES: tuple[ModuleType, ...] = (
    action_cards,
    appeal_drafts,
    explicit_reports,
    notification_render,
    route_card_render,
)


def _literals(code: CodeType) -> list[str]:
    """Все строковые литералы кода, включая вложенные функции и выражения."""
    found: list[str] = []
    for const in code.co_consts:
        if isinstance(const, str):
            found.append(const)
        elif isinstance(const, CodeType):
            found.extend(_literals(const))
    return found


def _callables(module: ModuleType) -> Iterator[tuple[str, object]]:
    for name, value in vars(module).items():
        if getattr(value, "__module__", None) != module.__name__:
            continue
        if isinstance(value, type):
            for method, attribute in vars(value).items():
                if hasattr(attribute, "__code__"):
                    yield f"{name}.{method}", attribute
        elif hasattr(value, "__code__"):
            yield name, value


def _template_strings(module: ModuleType) -> dict[str, str]:
    """Тексты модуля: константы и литералы внутри его функций.

    Документация исключена сознательно: docstring обсуждает запрещённые
    формулировки и обязан их называть, а видимым текстом не становится.
    """
    found: dict[str, str] = {}
    for name, value in vars(module).items():
        if name.startswith("__") or name == "FORBIDDEN_PHRASES":
            continue
        if isinstance(value, str):
            found[f"{module.__name__}.{name}"] = value
        elif isinstance(value, tuple | list | frozenset | set):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    found[f"{module.__name__}.{name}[{index}]"] = item
    for name, function in _callables(module):
        documented = getattr(function, "__doc__", None)
        for index, literal in enumerate(_literals(function.__code__)):  # type: ignore[attr-defined]
            if literal == documented:
                continue
            found[f"{module.__name__}.{name}()[{index}]"] = literal
    assert found, module.__name__
    return found


@pytest.mark.parametrize("module", TEMPLATE_MODULES, ids=lambda m: m.__name__)
def test_no_template_claims_the_appeal_was_filed_for_the_resident(module: ModuleType) -> None:
    for where, text in _template_strings(module).items():
        lowered = text.lower()
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in lowered, (where, phrase)


def test_forbidden_phrase_list_is_the_single_source_of_truth() -> None:
    # Карточка, личное сообщение и черновик проверяются одним списком.
    assert "заявка отправлена" in FORBIDDEN_PHRASES
    assert "обращение зарегистрировано" in FORBIDDEN_PHRASES
    assert "передано в" in FORBIDDEN_PHRASES
    assert route_card_render.MAX_FACTS == 2


def test_self_filing_note_says_who_actually_sends_the_appeal() -> None:
    note = appeal_drafts.SELF_FILING_NOTE.lower()
    assert "не отправляет" in note and "вы отправляете" in note


def test_dispatcher_note_is_honest_about_the_unknown_route() -> None:
    note = explicit_reports.DISPATCHER_REVIEW_NOTE.lower()
    assert "не определён" in note
    assert "диспетчер" in note


def test_classification_mode_covers_manual_rules_and_model() -> None:
    assert [mode.value for mode in ClassificationMode] == ["manual", "rules", "model"]


def test_ai_analysis_capability_defaults_to_off() -> None:
    # Правила работают всегда, поэтому выключенный флаг не скрывает явный путь.
    assert CapabilityFlags(test_auth=False).ai_analysis is False


def test_action_card_is_optional_on_report_created() -> None:
    # Поле аддитивное: прежние потребители продолжают читать ответ.
    assert ReportCreated.model_fields["action_card"].is_required() is False


def test_route_card_intent_has_no_field_for_model_prose() -> None:
    fields = set(route_card_render.RouteCardIntent.model_fields)
    assert not fields & {"clean_description", "description", "summary"}
