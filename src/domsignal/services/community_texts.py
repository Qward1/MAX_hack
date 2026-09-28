"""Тексты среза D3: посты бота в чат, личные сообщения, ответы на кнопки.

Голос бота по решению человека (BOT-VOICE-HUMAN-2026-09-27): здесь только
шаблоны продукта и слова автора-сотрудника (заголовок и текст объявления,
вопрос и варианты опроса). Текст модели сюда не попадает никогда. Слова и
имена жителей в чат не выводятся: у статуса заявки — категория, подъезд,
номер и состояние. Формулировки проверяет тот же список `FORBIDDEN_PHRASES`,
что и карточку маршрута; юридических сроков тексты не называют.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from domsignal.core.quiet_hours import MSK

#: Подпись опроса: он не заменяет общее собрание собственников.
POLL_DISCLAIMER = "Предварительный опрос. Не является решением общего собрания собственников."
CHAT_DISCLAIMER = "Сообщение в этом чате не является официальным обращением."
#: Правило формы рассылки.
SERVICE_ONLY_RULE = "Только сервисные сообщения для жителей. Реклама запрещена."

PLATFORM_SENDER = "Сообщение от ДомСигнала"
#: Подпись объявлений и опросов совета дома (D4).
COUNCIL_SENDER = "Сообщение от совета дома"
UNNAMED_COMPANY_SENDER = "Сообщение от управляющей компании дома"

KIND_LABELS = {"announcement": "Объявление", "mailing": "Рассылка", "poll": "Опрос"}
TOPIC_LABELS = {
    "outage": "Отключение",
    "works": "Работы",
    "meeting": "Собрание",
    "other": "Объявление",
}

RETRACTED = "Сообщение удалено автором."

# Кнопки.
VOTE_LABEL = "Голосовать"
OPEN_LABEL = "Открыть"
OPEN_APP_LABEL = "Открыть ДомСигнал"
UNSUBSCRIBE_LABEL = "Не получать рассылки"
ME_TOO_LABEL = "Меня тоже касается"

# Статус заявки в чате (B-06): категория, подъезд, номер и состояние.
TICKET_STATUS_LABELS = {
    "new": "Заявка создана и ждёт принятия в работу",
    "accepted": "УК приняла в работу",
    "in_progress": "В работе",
    "verification_pending": "Исполнитель сообщил о выполнении, жители проверяют",
    "needs_clarification": "Уточняются подробности",
    "waiting_external": "Ожидается внешняя организация",
    "closed": "Закрыта",
    "cancelled": "Отменена",
}
TICKET_RETURNED_LABEL = "Возвращена в работу"
TICKET_CHAT_TAIL = "Ход работ — в ДомСигнале. " + CHAT_DISCLAIMER

# Ответы на «Меня тоже касается» — всплывающее уведомление нажавшему.
ME_TOO_JOINED = "Отмечено: вас это тоже касается. Ход работ придёт в личные сообщения бота."
ME_TOO_JOINED_NO_DIALOG = (
    "Отмечено: вас это тоже касается. Чтобы получать ход работ, начните диалог с ботом ДомСигнал."
)
ME_TOO_ALREADY = "Вы уже отмечены в этой заявке."
ME_TOO_CLOSED = "Заявка уже закрыта — отметиться нельзя."
ME_TOO_NOT_RESIDENT = "Отметиться могут жители этого дома — участники домового чата."
ME_TOO_STALE = "Кнопка устарела. Откройте ДомСигнал, чтобы увидеть актуальное состояние."
ME_TOO_ERROR = "Не получилось отметить. Попробуйте ещё раз чуть позже."

# «Не получать рассылки».
UNSUBSCRIBED = (
    "Готово: рассылки управляющей компании и ДомСигнала больше не придут в личные сообщения. "
    "Статусы ваших заявок и ответы бота приходят как раньше. Вернуть рассылки можно в "
    "ДомСигнале, раздел «Объявления»."
)

# Сопровождение обращения (A-09). Юридических сроков текст не называет.
FOLLOWUP_QUESTION = (
    "Вы отметили, что отправили обращение сами ({when}). Пришёл ли ответ?\n"
    "Ответ поможет подсказать следующий шаг. ДомСигнал не видит переписку с ведомством."
)
FOLLOWUP_RESOLVED_LABEL = "Решено"
FOLLOWUP_ANSWERED_LABEL = "Ответ пришёл, не решено"
FOLLOWUP_NONE_LABEL = "Ответа нет"
FOLLOWUP_RESOLVED = "Спасибо! Отметили: вопрос решён."
FOLLOWUP_ALREADY = "Ответ уже записан. Спасибо!"
FOLLOWUP_NEXT_LEAD = "Что можно сделать дальше — проверенные каналы из справочника:"
FOLLOWUP_NO_CHANNELS = (
    "Других проверенных каналов для этой проблемы в справочнике нет. "
    "Можно сообщить о проблеме в управляющую компанию дома через ДомСигнал — "
    "если ответственный не определён, вопрос разберёт диспетчер."
)
FOLLOWUP_REPORT_LABEL = "Сообщить в УК"

# Ежедневная сводка сотруднику.
DIGEST_LEAD = "ДомСигнал — сводка на {day} · {company}"
DIGEST_SIGNALS = (
    "Новые сигналы за сутки: {total} (критические {critical}, сильные {strong}, "
    "средние {medium}, слабые {weak})"
)
DIGEST_UNASSIGNED = "Заявки без исполнителя: {count}"
DIGEST_VERIFICATION = "Ждут проверки жителями: {count}"
DIGEST_RETURNED = "Возвращены в работу: {count}"
DIGEST_LINK = "Кабинет: {url}"

# Запись на приём.
RECEPTION_REMINDER = (
    "Напоминание: завтра, {when}, — приём в управляющей компании {company}.\nТема: {topic}"
)
RECEPTION_PLACE = "Место: {place}"

# Сообщение платформы сотруднику.
STAFF_NOTICE_LEAD = "ДомСигнал: сообщение платформы"
STAFF_NOTICE_LINK = "В кабинете: {url}"


_OWN_QUOTES = re.compile(r"[«\"“]")
_LEGAL_FORM = re.compile(r"^(?:УК|ООО|АО|ОАО|ПАО|ТСЖ|ТСН|ЖСК|МУП|ГУП|ИП)(?=\s|«|\"|$)")


def company_quoted(name: str) -> str:
    """Название УК внутри текста: «Солнечная» — в кавычках, а «УК «Пилотная, 7»»,
    «ООО Ромашка» и другие названия с формой или своими кавычками — как есть,
    без «УК «УК …»»."""
    cleaned = name.strip()
    if _OWN_QUOTES.search(cleaned) or _LEGAL_FORM.match(cleaned):
        return cleaned
    return f"«{cleaned}»"


def sender_label(origin: str, company_name: str | None) -> str:
    if origin == "platform":
        return PLATFORM_SENDER
    if origin == "council":
        return COUNCIL_SENDER
    cleaned = (company_name or "").strip()
    if not cleaned:
        return UNNAMED_COMPANY_SENDER
    if cleaned.startswith("УК"):
        return f"Сообщение от {company_quoted(cleaned)}"
    return f"Сообщение от УК {company_quoted(cleaned)}"


def moment(value: datetime) -> str:
    """«27.09.2026 18:00 МСК»."""
    return value.astimezone(MSK).strftime("%d.%m.%Y %H:%M") + " МСК"


def heading(kind: str, topic: str | None) -> str:
    label = KIND_LABELS.get(kind, "Сообщение")
    if kind == "announcement" and topic in TOPIC_LABELS and topic != "other":
        return f"{label} · {TOPIC_LABELS[topic]}"
    return label


@dataclass(frozen=True)
class OptionLine:
    label: str
    votes: int
    share: float


def poll_lines(
    question: str,
    options: Sequence[OptionLine],
    *,
    voters: int,
    closes_at: datetime,
    closed: bool,
) -> list[str]:
    lines = [question, ""]
    for index, option in enumerate(options, start=1):
        percent = round(option.share * 100)
        lines.append(f"{index}. {option.label} — {option.votes} ({percent}%)")
    lines.append("")
    lines.append(f"Проголосовали: {voters}")
    lines.append(
        f"Опрос закрыт {moment(closes_at)}." if closed else f"Голосование до {moment(closes_at)}."
    )
    lines.append(POLL_DISCLAIMER)
    return lines


def broadcast_text(
    *,
    kind: str,
    topic: str | None,
    title: str,
    body: str,
    sender: str,
    edited_at: datetime | None = None,
    retracted: bool = False,
    poll: list[str] | None = None,
) -> str:
    """Пост в чат и личное сообщение: заголовок, текст автора, подпись."""
    if retracted:
        return "\n".join((RETRACTED, f"— {sender}"))
    parts = [heading(kind, topic), title]
    if body.strip():
        parts += ["", body.strip()]
    if poll:
        parts += ["", *poll]
    if edited_at is not None:
        parts += ["", f"Изменено {moment(edited_at)}."]
    parts += ["", f"— {sender}"]
    return "\n".join(parts)[:4000]


def ticket_chat_text(
    *,
    number: int,
    category_title: str,
    entrance: str | None,
    status: str,
    returned: bool,
    participants: int,
) -> str:
    label = (
        TICKET_RETURNED_LABEL
        if returned and status == "in_progress"
        else TICKET_STATUS_LABELS.get(status, "Состояние обновлено")
    )
    lines = [f"Заявка T-{number} · {category_title}"]
    if entrance:
        lines.append(f"Подъезд {entrance}")
    lines.append(f"Статус: {label}")
    if participants > 0:
        lines.append(f"Касается жителей: {participants}")
    lines.append(TICKET_CHAT_TAIL)
    return "\n".join(lines)


def staff_notice_text(title: str, body: str, url: str | None) -> str:
    parts = [STAFF_NOTICE_LEAD, title]
    if body.strip():
        parts += ["", body.strip()]
    if url:
        parts += ["", STAFF_NOTICE_LINK.format(url=url)]
    return "\n".join(parts)[:4000]


__all__ = [
    "CHAT_DISCLAIMER",
    "KIND_LABELS",
    "ME_TOO_LABEL",
    "OPEN_APP_LABEL",
    "OPEN_LABEL",
    "POLL_DISCLAIMER",
    "SERVICE_ONLY_RULE",
    "TICKET_STATUS_LABELS",
    "TOPIC_LABELS",
    "UNSUBSCRIBE_LABEL",
    "VOTE_LABEL",
    "OptionLine",
    "broadcast_text",
    "heading",
    "moment",
    "poll_lines",
    "sender_label",
    "staff_notice_text",
    "ticket_chat_text",
]
