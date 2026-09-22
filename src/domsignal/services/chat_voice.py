"""Голос бота в домовом чате и оповещение оператора — только шаблоны продукта.

В групповом чате бот пишет ровно два вида сообщений: сообщение о чтении чата
(один раз на привязку и её версию) и памятку безопасности при срабатывании
правил опасности без отрицания и без «не у нас / не сейчас». Это самый строгий
уровень голоса: текст модели сюда не попадает никогда, памятка берётся из
проверенного `regions/_federal/safety.yaml`, а семантическая опасность,
найденная только моделью, даёт оповещение оператора, но не сообщение в чат.

Оповещение оператора — личное сообщение сотруднику с доступом к дому. В нём
только шаблон, подписи видов опасности и дословная цитата жителя.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.bot.messaging import PersonalMessage
from domsignal.contracts.common import ContractModel
from domsignal.contracts.routing import SafetyBlock
from domsignal.core.signals import DANGER_LABELS, author_label
from domsignal.services.route_card_render import safety_lines

#: Вид сообщения в существующем outbox: сообщение в групповой чат.
CHAT_MESSAGE_INTENT_KIND = "chat.message.v1"

#: Вид сообщения в outbox: оповещение операторов о критическом сигнале.
SIGNAL_ALERT_INTENT_KIND = "signal.alert.v1"

#: Префиксы `launch_ref`. Резолвер запуска их не принимает: у сообщения в чат
#: и у оповещения нет экрана, на который можно было бы честно вести ссылкой.
CHAT_REF_PREFIX = "c_"
ALERT_REF_PREFIX = "s_"

ChatPurpose = Literal["chat_reading_notice", "chat_safety_memo"]

_UNNAMED_COMPANY = "управляющая компания дома"

READING_NOTICE_PURPOSE: ChatPurpose = "chat_reading_notice"
SAFETY_MEMO_PURPOSE: ChatPurpose = "chat_safety_memo"

_MEMO_LEAD = "ДомСигнал: в чате написали о признаках опасности."
_ALERT_LEAD = "ДомСигнал: возможная опасность в домовом чате."
_ALERT_TAIL = (
    "Сигнал сохранён и ждёт проверки оператором. "
    "Сообщение в домовом чате не является официальным обращением."
)
_ALERT_SOURCE_RULES = "Признак найден правилами ДомСигнала по словам жителя."
_ALERT_SOURCE_WINDOW = "Признак найден при разборе переписки."


class ChatMessageIntent(ContractModel):
    """Снимок сообщения в групповой чат для доставки.

    Текст снимается в момент решения и не меняется при повторной доставке.
    Поля под свободный текст модели нет.
    """

    purpose: ChatPurpose
    chat_binding_id: UUID
    binding_version: int
    text: str = Field(min_length=1, max_length=4000)
    signal_id: UUID | None = None
    danger_kinds: list[str] = Field(default_factory=list)


class SignalAlertIntent(ContractModel):
    """Оповещение операторов дома о критическом сигнале."""

    signal_id: UUID
    house_id: UUID


def _company(name: str | None) -> str:
    cleaned = (name or "").strip()
    return f"управляющей компанией «{cleaned}»" if cleaned else _UNNAMED_COMPANY


def reading_notice_text(company_name: str | None) -> str:
    """Сообщение о чтении чата: кто подключил, что читает, кто отключит.

    Никаких сроков, гарантий и ссылок: только то, что продукт делает на самом
    деле и что можно проверить.
    """
    who = _company(company_name)
    subject = (
        f"управляющая компания «{company_name.strip()}»"
        if company_name and company_name.strip()
        else _UNNAMED_COMPANY
    )
    return "\n".join(
        (
            f"ДомСигнал подключён к этому чату — подключение подтверждено {who}.",
            "Бот читает сообщения этого чата, чтобы замечать проблемы дома — "
            "например, неработающий лифт или протечку.",
            "Сам бот почти никогда не пишет сюда: только это сообщение и памятку "
            "безопасности, если в чате напишут о признаках опасности.",
            "Сообщение в этом чате не является официальным обращением.",
            f"Отключить чтение может {subject}. "
            "Администратор чата может удалить бота из чата.",
        )
    )


def safety_memo_text(safety: SafetyBlock) -> str:
    """Памятка безопасности: только проверенный блок справочника."""
    return "\n".join((_MEMO_LEAD, *safety_lines(safety)))


def _labels(kinds: list[str] | tuple[str, ...]) -> str:
    labels = [DANGER_LABELS.get(kind, DANGER_LABELS["other_hazard"]) for kind in kinds]
    return ", ".join(dict.fromkeys(labels)) or DANGER_LABELS["other_hazard"]


def _moment(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")


def operator_alert_message(
    *,
    house_address: str,
    danger_kinds: list[str] | tuple[str, ...],
    from_rules: bool,
    quote: str | None,
    quote_author: str | None,
    quote_sent_at: datetime | None,
) -> PersonalMessage:
    """Личное сообщение оператору. Кнопки нет: экрана очереди ещё нет."""
    lines = [
        _ALERT_LEAD,
        f"Дом: {house_address}",
        f"Признаки: {_labels(danger_kinds)}",
        _ALERT_SOURCE_RULES if from_rules else _ALERT_SOURCE_WINDOW,
    ]
    if quote:
        author = author_label(quote_author) if quote_author else "житель"
        moment = f", {_moment(quote_sent_at)}" if quote_sent_at else ""
        lines.append(f"Цитата: «{quote}» — {author}{moment}")
    lines.append(_ALERT_TAIL)
    return PersonalMessage("\n".join(lines), ())


def chat_message(intent: ChatMessageIntent) -> PersonalMessage:
    """Сообщение в чат без кнопок: голос бота здесь — только текст."""
    return PersonalMessage(intent.text, ())


__all__ = [
    "ALERT_REF_PREFIX",
    "CHAT_MESSAGE_INTENT_KIND",
    "CHAT_REF_PREFIX",
    "READING_NOTICE_PURPOSE",
    "SAFETY_MEMO_PURPOSE",
    "SIGNAL_ALERT_INTENT_KIND",
    "ChatMessageIntent",
    "ChatPurpose",
    "SignalAlertIntent",
    "chat_message",
    "operator_alert_message",
    "reading_notice_text",
    "safety_memo_text",
]
