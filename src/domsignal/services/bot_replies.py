"""Ответы личного бота: шаблоны продукта и постановка в существующий outbox.

Каждый ответ — запись outbox с ключом `bot:<вид>:<event_id>`: повтор того же
входящего события не создаёт второго ответа. Доставка — общий механизм A-05
(`NotificationDelivery`, назначение `bot_reply`), второго транспорта нет.

Текст модели сюда не попадает: только шаблоны и проверенные данные (адрес
дома, заголовок проблемы по категории, блок безопасности справочника). Слова
жителя в ответ не повторяются. Формулировки проверяет тот же список
`FORBIDDEN_PHRASES`, что и карточку маршрута.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bot.messaging import MessageButton, PersonalMessage
from domsignal.contracts.common import ContractModel
from domsignal.db.models import OutboxMessage

#: Вид сообщения в outbox: ответ личного бота.
BOT_REPLY_INTENT_KIND = "bot.reply.v1"

#: Префикс `launch_ref` доставки ответа. Резолвер запуска его не принимает.
BOT_REF_PREFIX = "b_"

#: Задачи личного бота (операционный пул).
DM_JOB = "bot.dm"
CALLBACK_JOB = "bot.callback"
#: Истечение ожидания выбора дома или ответа «та же проблема».
HOLD_JOB = "bot.hold.expire"

#: Стартовый параметр кнопки «Открыть ДомСигнал» без контекста: mini app его
#: не разрешает, а открывает обычный экран. Доступа параметр не даёт.
OPEN_APP_PAYLOAD = "home"

OPEN_APP_LABEL = "Открыть ДомСигнал"
CHOOSE_HOUSE_LABEL = "Выбрать дом"
SAME_PROBLEM_LABEL = "Это та же проблема"
OTHER_PROBLEM_LABEL = "Другое"

GREETING = (
    "Здравствуйте! Я ДомСигнал — помощник вашего дома в MAX.\n"
    "Напишите сюда, что случилось в доме, например: «в первом подъезде не работает лифт».\n"
    "Если это зона управляющей компании, у неё появится заявка; если нет — подскажу, "
    "куда обратиться.\n"
    "Ход работ и результат — в ДомСигнале."
)
HELP = (
    "Как пользоваться ДомСигналом:\n"
    "• напишите сюда, что случилось в доме и где — я разберу сообщение и подскажу "
    "следующий шаг;\n"
    "• в домовом чате — команда /report и описание;\n"
    "• «Открыть ДомСигнал» — проблемы дома, карточки и черновики обращений.\n"
    "Команды: /start — начало, /help — эта справка, /version — версия."
)
NOT_A_PROBLEM = "Не похоже на описание проблемы. Напишите, что случилось и где."
#: Кнопки-примеры первого экрана (D4, У-3): текст кнопки → текст сообщения о проблеме.
#: Фонарь — на улице, а не во дворе: уличное освещение ведёт к официальному каналу с
#: черновиком обращения, двор решает диспетчер УК. Лифт — заявка управляющей компании.
EXAMPLES = {
    "Попробовать: на улице не горит фонарь": "На улице у дома не горит фонарь",
    "Попробовать: лифт во 2 подъезде стоит": "Лифт во 2 подъезде стоит",
}
PICK_OPEN_HOUSE = "Пока не вижу вашего дома. Выберите его — и я разберу сообщение:"
# Код подключения домового чата (A-07) из кабинета УК: что делать дальше.
CONNECT_CLAIMED = (
    "Код подключения принят. Теперь добавьте бота ДомСигнал в группу дома и сделайте "
    "его администратором с правом читать все сообщения. Затем вернитесь в кабинет УК "
    "и нажмите «Подтвердить подключение»."
)
CONNECT_BUSY = (
    "У вас уже идёт подключение другого чата. Завершите или отмените его в кабинете УК "
    "и отправьте код ещё раз."
)
CONNECT_INVALID = (
    "Код подключения не подошёл: он устарел, уже использован или скопирован не целиком. "
    "Создайте новый в кабинете УК, раздел «MAX-чаты»."
)
NO_HOUSES = (
    "Пока не вижу вашего дома. Откройте ДомСигнал кнопкой из вашего домового чата — "
    "так я узнаю, в каком доме вы живёте."
)
CHOOSE_HOUSE = "В каком доме это случилось?"
OPEN_HOUSES_LEAD = "Выберите ваш дом:"
NO_OPEN_HOUSES = (
    "Сейчас нет домов, которые можно выбрать. Откройте ДомСигнал кнопкой из вашего "
    "домового чата."
)
HOUSE_JOINED = "Дом выбран: {address}.\nНапишите, что случилось и где."
HOUSE_UNAVAILABLE = "Этот дом сейчас нельзя выбрать."
HOUSE_PICKED = "Дом: {address}. Разбираю сообщение — ответ придёт следующим сообщением."
DUPLICATE_LEAD = "Похоже, об этом уже сообщали: «{title}»."
DUPLICATE_QUESTION = "Это та же проблема?"
JOINED = "Готово: вы присоединились к проблеме «{title}». Ход работ — в ДомСигнале."
JOIN_CLOSED = "Эта проблема уже закрыта. Напишите о ней ещё раз — разберу как новую."
OTHER_CHOSEN = "Отмечено: это другая проблема. Ответ придёт следующим сообщением."
EXPIRED = "Время выбора истекло. Напишите о проблеме ещё раз."
LIMIT = (
    "Сегодня вы уже отправили {limit} сообщений о проблемах — это предел на сутки. "
    "Продолжить можно завтра."
)
NO_ACCESS = "Нет доступа к этому дому. Откройте ДомСигнал кнопкой из вашего домового чата."
VERSION = "ДомСигнал, версия {version}."
GROUP_ACK = "Принято. Подробности пришлю в личные сообщения — откройте диалог с ботом."
GROUP_ACK_LINK = "Диалог с ботом: https://max.ru/{bot}"


class ReplyButton(ContractModel):
    kind: Literal["open_app", "callback", "message"]
    text: str = Field(min_length=1, max_length=64)
    payload: str = Field(min_length=1, max_length=1024)


class BotReplyIntent(ContractModel):
    """Снимок ответа бота: текст шаблона и кнопки, без слов жителя."""

    recipient_user_id: UUID
    reply_event_id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=4000)
    buttons: list[list[ReplyButton]] = Field(default_factory=list, max_length=12)


def open_app_button() -> ReplyButton:
    return ReplyButton(kind="open_app", text=OPEN_APP_LABEL, payload=OPEN_APP_PAYLOAD)


def callback_button(text: str, payload: str) -> ReplyButton:
    return ReplyButton(kind="callback", text=text[:64], payload=payload)


def example_button(label: str) -> ReplyButton:
    """Кнопка-пример (D4): MAX отправляет её текст боту от имени нажавшего."""
    return ReplyButton(kind="message", text=label, payload=label)


def render_bot_reply(intent: BotReplyIntent) -> PersonalMessage:
    return PersonalMessage(
        intent.text,
        tuple(
            tuple(MessageButton(button.kind, button.text, button.payload) for button in row)
            for row in intent.buttons
        ),
    )


def as_message(text: str, buttons: Sequence[Sequence[ReplyButton]] = ()) -> PersonalMessage:
    """Ответ на нажатие кнопки: тот же вид, что и ответ в outbox."""
    return PersonalMessage(
        text,
        tuple(
            tuple(MessageButton(button.kind, button.text, button.payload) for button in row)
            for row in buttons
        ),
    )


async def enqueue_reply(
    session: AsyncSession,
    *,
    user_id: UUID,
    event_id: str,
    key: str,
    text: str,
    buttons: Sequence[Sequence[ReplyButton]] = (),
) -> None:
    """Положить ответ в outbox один раз на пару «вид ответа, событие»."""
    intent = BotReplyIntent(
        recipient_user_id=user_id,
        reply_event_id=event_id,
        text=text,
        buttons=[list(row) for row in buttons],
    )
    await session.execute(
        insert(OutboxMessage)
        .values(
            kind=BOT_REPLY_INTENT_KIND,
            aggregate_id=user_id,
            payload=intent.model_dump(mode="json"),
            status="pending",
            dedupe_key=f"bot:{key}:{event_id}"[:100],
        )
        .on_conflict_do_nothing(index_elements=[OutboxMessage.dedupe_key])
    )


__all__ = [
    "BOT_REF_PREFIX",
    "BOT_REPLY_INTENT_KIND",
    "BotReplyIntent",
    "OPEN_APP_PAYLOAD",
    "ReplyButton",
    "as_message",
    "callback_button",
    "enqueue_reply",
    "open_app_button",
    "render_bot_reply",
]
