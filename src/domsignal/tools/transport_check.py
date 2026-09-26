"""Проверка доставки в MAX от имени бота — транспорт и отрисовка продукта (D5 §7).

Проверяет в настоящем MAX то, что в D3–D4 проверено только автотестами:
пост объявления в домовой чат и правку того же поста, пост опроса с кнопкой
«Голосовать» и правку итогов, личное сообщение рассылки и пропуск
отписавшегося. Тексты — отрисовка продукта (`community_texts`), отправка —
тот же клиент MAX, что у доставок (`POST /messages`, `PUT /messages`).

Объекты рассылки и опроса в базе не создаются: их подтверждает и заново
проверяет при отправке человек, а писать от имени людей инструменту нельзя.
Адресаты — только явно названные: активная привязка чата и пользователи с
начатым диалогом; личные сообщения — только 09:00–22:00 МСК. Каждый запуск
оставляет квитанцию `operator.transport_check` (оператор, основание, исходы,
id сообщений MAX — без текстов). Посты в конце удаляются (`DELETE /messages`);
если MAX не удалил — правятся в короткую служебную строку.

    python -m domsignal.tools.transport_check --binding <id привязки чата> \\
        --dm-user <id> [--dm-user <id>] [--unsubscribed-user <id>] \\
        --operator "dev-agent по поручению владельца" --reason "<основание>"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from domsignal.bootstrap import build_container
from domsignal.bot.messaging import MessageButton, MessagingError, PersonalMessage
from domsignal.contracts.community import ResidentPreferences
from domsignal.core.quiet_hours import MSK
from domsignal.db.models import (
    ChatBinding,
    HouseManagement,
    InboxReceipt,
    ManagementCompany,
    MAXChat,
    User,
)
from domsignal.services.bot_replies import OPEN_APP_PAYLOAD
from domsignal.services.community_delivery import UNSUBSCRIBE_CALLBACK
from domsignal.services.community_texts import (
    OPEN_APP_LABEL,
    UNSUBSCRIBE_LABEL,
    VOTE_LABEL,
    OptionLine,
    broadcast_text,
    poll_lines,
    sender_label,
)
from domsignal.settings import get_settings
from domsignal.tools import print_json

TITLE = "Служебная проверка доставки"
BODY = "Проверяем, что сообщения ДомСигнала доходят. Отвечать не нужно, пост будет удалён."
CLEANED = "Служебная проверка доставки ДомСигнала завершена."
DM_START, DM_END = time(9, 0), time(22, 0)


def dm_allowed(now: datetime) -> bool:
    local = now.astimezone(MSK).time()
    return DM_START <= local < DM_END


def announcement(sender: str, *, edited: datetime | None = None) -> PersonalMessage:
    text = broadcast_text(
        kind="announcement", topic="other", title=TITLE, body=BODY, sender=sender, edited_at=edited
    )
    return PersonalMessage(text, ((MessageButton("open_app", OPEN_APP_LABEL, OPEN_APP_PAYLOAD),),))


def poll(sender: str, *, closed: bool, closes_at: datetime) -> PersonalMessage:
    options = [OptionLine("Да", 0, 0.0), OptionLine("Нет", 0, 0.0)]
    lines = poll_lines("Сообщение дошло?", options, voters=0, closes_at=closes_at, closed=closed)
    text = broadcast_text(kind="poll", topic=None, title=TITLE, body="", sender=sender, poll=lines)
    label = OPEN_APP_LABEL if closed else VOTE_LABEL
    return PersonalMessage(text, ((MessageButton("open_app", label, OPEN_APP_PAYLOAD),),))


async def attempt(coro: Any) -> tuple[bool, str | None]:
    try:
        await coro
    except MessagingError as exc:
        return False, exc.code
    return True, None


async def delete(provider: Any, message_id: str) -> tuple[bool, str | None]:
    """`DELETE /messages` тем же клиентом; нет метода — правка в служебную строку."""
    remove = getattr(provider, "_boolean", None)
    if remove is None:
        return False, "DELETE_UNSUPPORTED"
    try:
        await remove("DELETE", "/messages", {"message_id": message_id}, {})
    except MessagingError as exc:
        return False, exc.code
    return True, None


async def run(args: argparse.Namespace) -> int:
    container = build_container(get_settings())
    try:
        return await check(container, args)
    finally:
        await container.aclose()


async def check(container: Any, args: argparse.Namespace) -> int:
    """Проверка на собранном контейнере (тест подставляет записывающий MAX)."""
    provider = container.notifications.provider
    results: list[dict[str, Any]] = []
    now = datetime.now(UTC)
    async with container.session_factory() as session:
        binding = await session.get(ChatBinding, args.binding)
        if binding is None or binding.status != "active":
            print_json({"error": "binding_not_active"})
            return 2
        chat = await session.scalar(
            select(MAXChat).where(MAXChat.max_chat_id == binding.max_chat_id)
        )
        if chat is None or not chat.bot_present:
            print_json({"error": "bot_not_in_chat"})
            return 2
        management = await session.get(HouseManagement, binding.management_id)
        company = await session.get(ManagementCompany, management.tenant_id) if management else None
        sender = sender_label("company", company.name if company else None)
        users = {user_id: await session.get(User, user_id) for user_id in args.dm_user}
    chat_id = binding.max_chat_id
    posts: list[str] = []

    # 1. Объявление и правка того же поста.
    try:
        sent = await provider.send_chat_message(chat_id, announcement(sender))
        posts.append(sent.message_id)
        edited, code = await attempt(
            provider.edit_message(sent.message_id, announcement(sender, edited=now))
        )
        results.append(
            {
                "kind": "announcement",
                "accepted": True,
                "message_id": sent.message_id,
                "edit_ok": edited,
                "edit_error": code,
            }
        )
    except MessagingError as exc:
        results.append({"kind": "announcement", "accepted": False, "error": exc.code})

    # 2. Опрос с «Голосовать» и правка итогов того же сообщения.
    closes = now + timedelta(minutes=10)
    try:
        sent = await provider.send_chat_message(
            chat_id, poll(sender, closed=False, closes_at=closes)
        )
        posts.append(sent.message_id)
        edited, code = await attempt(
            provider.edit_message(sent.message_id, poll(sender, closed=True, closes_at=now))
        )
        results.append(
            {
                "kind": "poll",
                "accepted": True,
                "message_id": sent.message_id,
                "edit_ok": edited,
                "edit_error": code,
            }
        )
    except MessagingError as exc:
        results.append({"kind": "poll", "accepted": False, "error": exc.code})

    # 3. Личные сообщения рассылки: отписка выставляется сервисом и возвращается.
    if args.dm_user and not dm_allowed(datetime.now(UTC)):
        results.append({"kind": "dm", "skipped_all": "OUTSIDE_09_22_MSK"})
    elif args.dm_user:
        restore = False
        if args.unsubscribed_user:
            async with container.session_factory() as session, session.begin():
                before = await container.broadcasts.preferences(
                    session, actor_id=args.unsubscribed_user
                )
                restore = not before.broadcast_opt_out
                await container.broadcasts.set_preferences(
                    session,
                    actor_id=args.unsubscribed_user,
                    payload=ResidentPreferences(broadcast_opt_out=True),
                )
        dm_ids: list[str] = []
        for user_id, user in users.items():
            if user is None or not user.max_user_id or user.max_dialog_at is None:
                results.append({"kind": "dm", "user": str(user_id), "skipped": "NO_DIALOG"})
                continue
            async with container.session_factory() as session:
                fresh = await session.get(User, user_id)
            if fresh is not None and fresh.broadcast_opt_out_at is not None:
                results.append({"kind": "dm", "user": str(user_id), "skipped": "UNSUBSCRIBED"})
                continue
            message = announcement(sender)
            message = PersonalMessage(
                message.text,
                (
                    *message.buttons,
                    (MessageButton("callback", UNSUBSCRIBE_LABEL, UNSUBSCRIBE_CALLBACK),),
                ),
            )
            try:
                sent = await provider.send_personal_message(user.max_user_id, message)
                dm_ids.append(sent.message_id)
                results.append(
                    {
                        "kind": "dm",
                        "user": str(user_id),
                        "accepted": True,
                        "message_id": sent.message_id,
                    }
                )
            except MessagingError as exc:
                results.append(
                    {"kind": "dm", "user": str(user_id), "accepted": False, "error": exc.code}
                )
        if args.unsubscribed_user and restore:
            # Возвращаем прежнее состояние: до проверки аккаунт получал рассылки.
            async with container.session_factory() as session, session.begin():
                await container.broadcasts.set_preferences(
                    session,
                    actor_id=args.unsubscribed_user,
                    payload=ResidentPreferences(broadcast_opt_out=False),
                )
        posts.extend(dm_ids)

    # 4. Уборка: удалить свои сообщения, иначе — служебная строка.
    cleanup = []
    for message_id in posts:
        deleted, code = await delete(provider, message_id)
        if not deleted:
            edited, _ = await attempt(
                provider.edit_message(message_id, PersonalMessage(CLEANED, ()))
            )
            cleanup.append(
                {
                    "message_id": message_id,
                    "deleted": False,
                    "error": code,
                    "edited_to_service_line": edited,
                }
            )
        else:
            cleanup.append({"message_id": message_id, "deleted": True})

    async with container.session_factory() as session, session.begin():
        session.add(
            InboxReceipt(
                event_id=f"transport-check:{uuid4()}",
                event_type="operator.transport_check",
                payload={
                    "operator": args.operator[:200],
                    "reason": args.reason[:500],
                    "binding_id": str(args.binding),
                    "results": results,
                    "cleanup": cleanup,
                },
            )
        )
    print_json({"results": results, "cleanup": cleanup})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--binding", type=UUID, required=True)
    parser.add_argument("--dm-user", type=UUID, action="append", default=[])
    parser.add_argument("--unsubscribed-user", type=UUID, default=None)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.unsubscribed_user and args.unsubscribed_user not in args.dm_user:
        parser.error("--unsubscribed-user must also be one of --dm-user")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
