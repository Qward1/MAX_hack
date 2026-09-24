"""Запреты формулировок и форма контракта явного пути.

Продукт не подаёт обращение за человека и не подтверждает внешнюю регистрацию.
Проверка идёт по самим шаблонам, а не только по собранным ответам: так
запрещённая формулировка не проедет в новой константе мимо сценарных тестов.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import CodeType, ModuleType

import pytest

from domsignal.contracts.capabilities import CapabilityFlags
from domsignal.contracts.incidents import ReportCreated, ReportPreview, ReportSubmitted
from domsignal.contracts.notifications import NotificationLaunch
from domsignal.contracts.routing import RouteOutcomeView
from domsignal.core.incidents import ClassificationMode
from domsignal.services import (
    action_cards,
    appeal_drafts,
    bot_replies,
    chat_voice,
    explicit_reports,
    notification_render,
    route_card_render,
    signal_inbox,
    signal_texts,
)
from domsignal.services.action_cards import FORBIDDEN_PHRASES

#: Экраны жителя. Их тексты видны человеку так же, как ответы backend.
RESIDENT_SURFACES: tuple[str, ...] = (
    "miniapp/src/app/App.tsx",
    "miniapp/src/features/appeals/AppealDraftScreen.tsx",
    "miniapp/src/features/incidents/ReportFlow.tsx",
    "miniapp/src/features/incidents/presentation.ts",
    "miniapp/src/features/routing/RouteCard.tsx",
    "miniapp/src/features/routing/presentation.ts",
    # Кабинет оператора: очередь сигналов и её подписи (P5).
    "miniapp/src/admin/SignalsApp.tsx",
    "miniapp/src/admin/SignalCommon.tsx",
    "miniapp/src/admin/SignalDetail.tsx",
    "miniapp/src/admin/signalPresentation.ts",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

TEMPLATE_MODULES: tuple[ModuleType, ...] = (
    action_cards,
    appeal_drafts,
    # Ответы личного бота (D1) — тот же список запретов.
    bot_replies,
    # Голос бота в домовом чате и оповещение оператора — тот же список запретов.
    chat_voice,
    explicit_reports,
    notification_render,
    route_card_render,
    # Очередь сигналов оператора: причина силы, подписи, описание заявки.
    signal_inbox,
    signal_texts,
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


@pytest.mark.parametrize("surface", RESIDENT_SURFACES)
def test_no_resident_screen_claims_the_appeal_was_filed(surface: str) -> None:
    """Экран жителя проверяется тем же списком, что и шаблоны backend."""
    path = REPOSITORY_ROOT / surface
    assert path.is_file(), surface
    lowered = path.read_text(encoding="utf-8").lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in lowered, (surface, phrase)


def test_the_route_card_screen_states_who_sends_the_appeal() -> None:
    draft = (REPOSITORY_ROOT / "miniapp/src/features/appeals/AppealDraftScreen.tsx").read_text(
        encoding="utf-8"
    )
    # Отметка жителя не становится подтверждением внешней регистрации.
    assert "ДомСигнал не подтверждает регистрацию во внешней системе" in draft
    assert "Выделите и скопируйте текст вручную" in draft


def test_the_draft_screen_keeps_the_agreed_action_order() -> None:
    draft = (REPOSITORY_ROOT / "miniapp/src/features/appeals/AppealDraftScreen.tsx").read_text(
        encoding="utf-8"
    )
    order = draft.index('["copy_draft", "open_official_channel", "mark_filed"]')
    assert order > 0


def test_launch_contract_grew_additively_for_the_route_card() -> None:
    fields = NotificationLaunch.model_fields
    # Прежние потребители продолжают читать ответ: вид по умолчанию — заявка.
    assert fields["kind"].default == "ticket"
    assert fields["incident_id"].is_required() is False
    assert fields["route_outcome_id"].is_required() is False
    assert fields["house_id"].is_required() is True


def test_route_outcome_view_carries_the_card_and_the_directory_signal() -> None:
    fields = RouteOutcomeView.model_fields
    assert fields["action_card"].is_required() is True
    assert fields["directory_changed"].default is False
    for optional in ("incident_id", "appeal_draft_id"):
        assert fields[optional].is_required() is False


def test_duplicate_candidates_are_optional_and_submit_may_have_no_report() -> None:
    # Дубли аддитивны: прежний предпросмотр остаётся валидным ответом.
    assert ReportPreview.model_fields["duplicates"].is_required() is False
    # Внешний маршрут заявку не создаёт, поэтому `report` пуст по контракту.
    assert ReportSubmitted.model_fields["report"].is_required() is False


def test_route_and_appeal_capabilities_default_to_off() -> None:
    flags = CapabilityFlags(test_auth=False)
    assert flags.routes is False and flags.appeals is False
