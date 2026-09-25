"""MAX webhook intake: group `/report`, passive capture, membership events, personal bot.

No bulk participant sync. Membership grants come only from `user_added` in a
chat with an active binding or from a point check of the MAX API
(RESIDENT-BY-CHAT-2026-09-25); `bot_added` and links grant nothing.

Две формы одной команды. `/report <код категории> <текст>` — прежний ручной
путь без разбора. `/report <свободный текст>` — запись приёма плюс две задачи:
разбор ядром в AI-пуле и сторожевой разбор правилами в операционном пуле.
Разбор в транзакции приёма не выполняется: вызов модели не должен держать
транзакцию вебхука.

Остальные реплики привязанного чата при включённом пассивном чтении уходят в
буфер (`PassiveCaptureService`) — в той же транзакции, после ветки `/report`.
Команды в буфер не попадают: у них свой путь.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.bot.max_updates import MaxEvent
from domsignal.contracts.chat_connections import GroupMessage
from domsignal.contracts.jobs import InboundAccepted
from domsignal.core.incidents import ReportCategory
from domsignal.db.models import ExplicitIntake, InboxReceipt
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.chat_connections import ChatConnectionService, typed_connect_token
from domsignal.services.passive_capture import PassiveCaptureService
from domsignal.services.ticket_chat import GROUP_CALLBACK_JOB

if TYPE_CHECKING:
    from domsignal.services.personal_bot import PersonalBotService
    from domsignal.services.resident_access import ResidentAccessService

REPORT_COMMAND = "/report "

#: Коды категорий прежнего ручного пути. Совпадение второго слова с кодом
#: оставляет команду на старом пути без разбора.
CATEGORY_CODES = frozenset(item.value for item in ReportCategory)

#: Минимальная длина свободного текста. Короче — команда считается неполной и
#: игнорируется так же, как раньше игнорировался `/report` без описания.
MIN_FREE_TEXT = 5

#: Сторожевая задача правил ждёт столько секунд, давая AI-пулу шанс ответить.
FALLBACK_DELAY_SECONDS = 30

ANALYZE_JOB = "ai.report.analyze"
FALLBACK_JOB = "report.fallback"
ANALYZE_PRIORITY = 30
FALLBACK_PRIORITY = 50


def is_category_command(text: str) -> bool:
    """Второе слово — валидный код категории: это прежний ручной путь."""
    parts = text.split(maxsplit=2)
    return len(parts) >= 2 and parts[1] in CATEGORY_CODES


def free_text_of(text: str) -> str | None:
    """Свободный текст команды или `None`, если его слишком мало для разбора.

    Возврат `None` не означает «прежний путь»: форму команды определяет
    `is_category_command`. Слишком короткая команда игнорируется так же, как
    раньше игнорировался `/report` без описания.
    """
    body = text[len(REPORT_COMMAND) :].strip() if text.startswith(REPORT_COMMAND) else ""
    return body if len(body) >= MIN_FREE_TEXT else None


class MaxWebhookService:
    def __init__(
        self,
        connections: ChatConnectionService,
        passive: PassiveCaptureService | None = None,
        resident_access: ResidentAccessService | None = None,
        bot: PersonalBotService | None = None,
    ) -> None:
        self.connections = connections
        self.passive = passive
        self.resident_access = resident_access
        self.bot = bot

    async def accept(self, session: AsyncSession, event: MaxEvent) -> InboundAccepted:
        async with session.begin():
            repo = ChatRepository(session)
            await repo.lock(f"event:{event.event_id}")
            reliability = ReliabilityRepository(session)
            if await reliability.inbox(event.event_id):
                return InboundAccepted(
                    event_id=event.event_id, accepted=True, duplicate=True, job_id=None
                )
            # Correlation secrets / raw unbound messages are never stored in the inbox.
            session.add(
                InboxReceipt(
                    event_id=event.event_id,
                    event_type=event.kind,
                    payload={"chat_id": event.chat_id},
                )
            )
            job_id = None
            typed = typed_connect_token(event.text) if event.in_dialog else None
            if event.kind == "message_callback" and event.callback:
                job = await reliability.add_job(
                    kind="max.ticket.callback",
                    payload=event.callback.model_dump(mode="json"),
                    priority=20,
                )
                job_id = job.id
            elif event.kind == "message_callback" and event.bot_callback and self.bot:
                job_id = await self.bot.on_callback(session, event)
            elif event.kind == "message_callback" and event.group_callback:
                # «Меня тоже касается» в посте о заявке (B-06): решение — в задаче.
                pressed = event.group_callback
                job = await reliability.add_job(
                    kind=GROUP_CALLBACK_JOB,
                    payload={
                        "event_id": event.event_id,
                        "callback_id": pressed.callback_id,
                        "actor": pressed.actor,
                        "chat_id": pressed.chat_id,
                        "message_id": pressed.message_id,
                        "action": pressed.action,
                        "ref": pressed.ref,
                    },
                    priority=15,
                )
                job_id = job.id
            elif event.kind == "bot_started" and event.actor:
                request = None
                if event.token:
                    request = await self.connections.claim(
                        session,
                        token=event.token,
                        connector=event.actor,
                        occurred_at=event.occurred_at,
                    )
                if self.bot and event.token and event.token.startswith("connect_"):
                    await self.bot.on_connect(session, event, request)
                elif self.bot:
                    job_id = await self.bot.on_started(session, event)
            elif event.kind == "bot_stopped" and self.bot:
                await self.bot.on_stopped(session, event)
            elif (
                event.kind == "user_added"
                and event.chat_id
                and event.actor
                and self.resident_access
                and not event.is_channel
            ):
                await self.resident_access.user_added(
                    session,
                    chat_id=event.chat_id,
                    max_user_id=event.actor,
                    display_name=None,
                    occurred_at=event.occurred_at,
                )
            elif (
                event.kind == "user_removed"
                and event.chat_id
                and event.actor
                and self.resident_access
            ):
                await self.resident_access.user_removed(
                    session,
                    chat_id=event.chat_id,
                    max_user_id=event.actor,
                    occurred_at=event.occurred_at,
                )
            elif (
                event.kind == "message_created"
                and event.in_dialog
                and not event.from_bot
                and event.actor
                and typed
            ):
                # `/start connect_…`, набранная вручную, — то же, что ссылка запуска
                # бота с этим токеном (A-07); текст с токеном нигде не сохраняется.
                request = await self.connections.claim(
                    session, token=typed, connector=event.actor, occurred_at=event.occurred_at
                )
                if self.bot:
                    await self.bot.on_connect(session, event, request)
            elif (
                event.kind == "message_created"
                and event.in_dialog
                and not event.from_bot
                and event.chat_id
                and event.actor
                and self.bot
            ):
                # Личка бота: команды и сообщения о проблемах (B-04).
                job_id = await self.bot.on_dialog_message(session, event)
            elif event.kind == "bot_added" and event.chat_id and event.actor:
                await self.connections.bot_added(
                    session,
                    chat_id=event.chat_id,
                    actor=event.actor,
                    occurred_at=event.occurred_at,
                    is_channel=event.is_channel,
                )
            elif event.kind == "bot_removed" and event.chat_id:
                await self.connections.bot_removed(
                    session, chat_id=event.chat_id, occurred_at=event.occurred_at
                )
            elif (
                event.kind == "message_created"
                and event.chat_type == "chat"
                and event.chat_id
                and event.actor
                and event.text
                and event.text.startswith(REPORT_COMMAND)
            ):
                binding = await repo.active_binding(event.chat_id)
                if (
                    binding is not None
                    and binding.activated_at is not None
                    and event.occurred_at >= binding.activated_at
                ):
                    by_code = is_category_command(event.text)
                    free_text = None if by_code else free_text_of(event.text)
                    if by_code:
                        message = GroupMessage(
                            event_id=event.event_id,
                            chat_id=event.chat_id,
                            external_user_id=event.actor,
                            occurred_at=event.occurred_at,
                            text=event.text,
                            chat_binding_id=binding.id,
                            binding_version=binding.binding_version,
                        )
                        job = await reliability.add_job(
                            kind="max.group.report",
                            payload=message.model_dump(mode="json"),
                            priority=50,
                        )
                        job_id = job.id
                    elif free_text is not None:
                        session.add(
                            ExplicitIntake(
                                event_id=event.event_id,
                                chat_id=event.chat_id,
                                chat_binding_id=binding.id,
                                binding_version=binding.binding_version,
                                external_user_id=event.actor,
                                text=free_text,
                                occurred_at=event.occurred_at,
                                state="pending",
                            )
                        )
                        payload = {"event_id": event.event_id}
                        now = datetime.now(UTC)
                        # Разбор ядром и сторож правил борются за одну запись:
                        # кто захватил, тот и обрабатывает. Остановленный
                        # AI-пул задерживает результат, но не отменяет его.
                        analyze = await reliability.add_job(
                            kind=ANALYZE_JOB, payload=payload, priority=ANALYZE_PRIORITY, now=now
                        )
                        await reliability.add_job(
                            kind=FALLBACK_JOB,
                            payload=payload,
                            priority=FALLBACK_PRIORITY,
                            delay_seconds=FALLBACK_DELAY_SECONDS,
                            now=now,
                        )
                        job_id = analyze.id
                    # Свободный текст короче минимума не создаёт ни записи,
                    # ни задач: команда неполная, как и раньше.
                    if self.bot and (by_code or free_text is not None):
                        # Бот не пишет первым: автору без диалога — ответ в группе.
                        await self.bot.on_group_report(
                            session,
                            binding=binding,
                            actor=event.actor,
                            event_id=event.event_id,
                            occurred_at=event.occurred_at,
                        )
            if (
                event.kind == "message_created"
                and event.chat_type == "chat"
                and self.passive is not None
            ):
                # Пассивное чтение: вся реплика привязанного чата, кроме команд.
                # Структурный фильтр внутри; приём не падает из-за правил,
                # сборщика окон или роутера.
                await self.passive.capture(session, event)
        return InboundAccepted(
            event_id=event.event_id, accepted=True, duplicate=False, job_id=job_id
        )
