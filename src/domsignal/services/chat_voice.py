"""Голос бота в домовом чате и оповещение оператора — только шаблоны продукта.

В групповом чате бот пишет только шаблоны: сообщение о подключении и чтении
чата (с кнопкой «Открыть ДомСигнал», D1), памятку безопасности при
срабатывании правил опасности без отрицания и без «не у нас / не сейчас» и
короткий ответ на явный `/report` автору, который ещё не начал диалог с ботом
(не чаще раза в 10 минут). Это самый строгий уровень голоса: текст модели
сюда не попадает никогда, памятка берётся из проверенного
`regions/_federal/safety.yaml`, а семантическая опасность, найденная только
моделью, даёт оповещение оператора, но не сообщение в чат.

Кнопка «Открыть ДомСигнал» несёт непрозрачную ссылку доставки `c_…`: она
только подсказывает, какой чат проверить, и доступа сама не даёт.

Оповещение оператора — личное сообщение сотруднику с доступом к дому. В нём
только шаблон, подписи видов опасности, дословная цитата жителя и ссылка на
деталь сигнала в кабинете — обычным текстом, без кнопки. Цитата — та реплика,
в которой найдена опасность, время — в поясе показа (`DISPLAY_TIMEZONE`).
Новый вид опасности у уже открытого сигнала даёт отдельное оповещение.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.contracts.common import ContractModel
from domsignal.contracts.routing import SafetyBlock
from domsignal.core.display_time import DEFAULT_DISPLAY_TIMEZONE, staff_moment
from domsignal.core.signals import DANGER_LABELS, author_label
from domsignal.services.route_card_render import safety_lines

#: Вид сообщения в существующем outbox: сообщение в групповой чат.
CHAT_MESSAGE_INTENT_KIND = "chat.message.v1"

#: Вид сообщения в outbox: оповещение операторов о критическом сигнале.
SIGNAL_ALERT_INTENT_KIND = "signal.alert.v1"

#: Префиксы `launch_ref`. Резолвер запуска их не принимает: у сообщения в чат
#: и у оповещения нет экрана, на который можно было бы честно вести ссылкой.
#: Ссылка `c_…` из кнопки сообщения в чате только сужает, какой чат проверить
#: при входе в mini app (RESIDENT-BY-CHAT-2026-09-25).
CHAT_REF_PREFIX = "c_"
ALERT_REF_PREFIX = "s_"

ChatPurpose = Literal[
    "chat_reading_notice",
    "chat_safety_memo",
    "chat_connection_notice",
    "chat_report_ack",
]

_UNNAMED_COMPANY = "управляющая компания дома"

READING_NOTICE_PURPOSE: ChatPurpose = "chat_reading_notice"
SAFETY_MEMO_PURPOSE: ChatPurpose = "chat_safety_memo"
CONNECTION_NOTICE_PURPOSE: ChatPurpose = "chat_connection_notice"
REPORT_ACK_PURPOSE: ChatPurpose = "chat_report_ack"

#: Назначения, которым нужно включённое пассивное чтение привязки.
READING_PURPOSES = frozenset({READING_NOTICE_PURPOSE, SAFETY_MEMO_PURPOSE})

OPEN_APP_LABEL = "Открыть ДомСигнал"

_MEMO_LEAD = "ДомСигнал: в чате написали о признаках опасности."
_ALERT_LEAD = "ДомСигнал: возможная опасность в домовом чате."
_ALERT_NEW_KIND_LEAD = "ДомСигнал: новый признак опасности в уже открытом сигнале."
_ALERT_TAIL = (
    "Сигнал сохранён и ждёт проверки оператором. "
    "Сообщение в домовом чате не является официальным обращением."
)
_ALERT_SOURCE_RULES = "Признак найден правилами ДомСигнала по словам жителя."
_ALERT_SOURCE_WINDOW = "Признак найден при разборе переписки."
_ALERT_LINK_LEAD = "Сигнал в кабинете:"


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
    #: Кнопка «Открыть ДомСигнал» со ссылкой этой доставки (D1).
    app_button: bool = False


class SignalAlertIntent(ContractModel):
    """Оповещение операторов дома о критическом сигнале.

    `new_kinds` пуст у первого оповещения по сигналу и перечисляет новые виды
    опасности у повторного. `evidence_mid` — реплика, в которой опасность
    найдена: её текст берётся из цитат сигнала или буфера в момент отправки,
    в outbox слов жителя нет.
    """

    signal_id: UUID
    house_id: UUID
    new_kinds: list[str] = Field(default_factory=list, max_length=7)
    evidence_mid: str | None = Field(default=None, max_length=200)


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
            "Сам бот пишет сюда редко: это сообщение, памятку безопасности, если в "
            "чате напишут о признаках опасности, и короткий ответ на /report.",
            "Сообщить о проблеме и следить за ходом работ — кнопка «Открыть "
            "ДомСигнал» ниже или личные сообщения боту.",
            "Сообщение в этом чате не является официальным обращением.",
            f"Отключить чтение может {subject}. "
            "Администратор чата может удалить бота из чата.",
        )
    )


def connection_notice_text(company_name: str | None) -> str:
    """Сообщение о подключении без чтения переписки: бот читает только /report."""
    who = _company(company_name)
    return "\n".join(
        (
            f"ДомСигнал подключён к этому чату — подключение подтверждено {who}.",
            "Сообщить о проблеме дома: команда /report и описание, личные сообщения "
            "боту или кнопка «Открыть ДомСигнал» ниже.",
            "Сообщение в этом чате не является официальным обращением.",
            "Администратор чата может удалить бота из чата.",
        )
    )


def safety_memo_text(safety: SafetyBlock) -> str:
    """Памятка безопасности: только проверенный блок справочника."""
    return "\n".join((_MEMO_LEAD, *safety_lines(safety)))


def _labels(kinds: list[str] | tuple[str, ...]) -> str:
    labels = [DANGER_LABELS.get(kind, DANGER_LABELS["other_hazard"]) for kind in kinds]
    return ", ".join(dict.fromkeys(labels)) or DANGER_LABELS["other_hazard"]


def signal_cabinet_url(public_base_url: str | None, signal_id: UUID) -> str | None:
    """Ссылка на деталь сигнала в кабинете. Доступ проверяет сам кабинет."""
    base = (public_base_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/admin/?section=signals&signal={signal_id}"


def operator_alert_message(
    *,
    house_address: str,
    danger_kinds: list[str] | tuple[str, ...],
    from_rules: bool,
    quote: str | None,
    quote_author: str | None,
    quote_sent_at: datetime | None,
    cabinet_url: str | None = None,
    new_kinds: list[str] | tuple[str, ...] = (),
    display_timezone: str = DEFAULT_DISPLAY_TIMEZONE,
) -> PersonalMessage:
    """Личное сообщение оператору. Ссылка на кабинет — строкой текста, не кнопкой."""
    lines = [_ALERT_NEW_KIND_LEAD if new_kinds else _ALERT_LEAD, f"Дом: {house_address}"]
    if new_kinds:
        lines.append(f"Новый признак: {_labels(new_kinds)}")
        lines.append(f"Все признаки сигнала: {_labels(danger_kinds)}")
    else:
        lines.append(f"Признаки: {_labels(danger_kinds)}")
    lines.append(_ALERT_SOURCE_RULES if from_rules else _ALERT_SOURCE_WINDOW)
    if quote:
        author = author_label(quote_author) if quote_author else "житель"
        moment = f", {staff_moment(quote_sent_at, display_timezone)}" if quote_sent_at else ""
        lines.append(f"Цитата: «{quote}» — {author}{moment}")
    lines.append(_ALERT_TAIL)
    if cabinet_url:
        lines.append(f"{_ALERT_LINK_LEAD} {cabinet_url}")
    return PersonalMessage("\n".join(lines), ())


def chat_message(intent: ChatMessageIntent, ref: str | None = None) -> PersonalMessage:
    """Сообщение в чат: текст шаблона и, у сообщения о подключении, кнопка.

    Кнопка открывает mini app со ссылкой этой доставки `c_…`; ссылка лишь
    подсказывает, какой чат проверить, и доступа сама не даёт.
    """
    if intent.app_button and ref:
        return PersonalMessage(
            intent.text, ((MessageButton("open_app", OPEN_APP_LABEL, ref),),)
        )
    return PersonalMessage(intent.text, ())


__all__ = [
    "ALERT_REF_PREFIX",
    "CHAT_MESSAGE_INTENT_KIND",
    "CHAT_REF_PREFIX",
    "CONNECTION_NOTICE_PURPOSE",
    "READING_NOTICE_PURPOSE",
    "READING_PURPOSES",
    "REPORT_ACK_PURPOSE",
    "SAFETY_MEMO_PURPOSE",
    "SIGNAL_ALERT_INTENT_KIND",
    "ChatMessageIntent",
    "ChatPurpose",
    "SignalAlertIntent",
    "chat_message",
    "connection_notice_text",
    "operator_alert_message",
    "reading_notice_text",
    "safety_memo_text",
    "signal_cabinet_url",
]
