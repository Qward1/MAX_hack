"""Приём реплик подключённого чата, сборщик окон, срок хранения, выключатель.

Приём идёт **в транзакции вебхука**: структурный фильтр → реплика в буфер →
правила опасности (чистая функция ядра, без сети) → окно → предварительный
критический сигнал, оповещение оператора и памятка в чат. Модель здесь не
вызывается и никакой сети нет. Ошибка в правилах, сборщике окон или роутере
не роняет приём: исключение логируется, реплика остаётся в буфере, вебхук
отвечает 200.

Состояние окна живёт в БД, политика — в ядре (`WindowPolicy`, `split_stream`).
Окно закрывают в транзакции приёма число реплик, возраст и опасность, а тишину
проверяет отложенная задача `chat.window.tick`, одна на окно: она либо
закрывает окно, либо переносит себя.

Журналы не содержат ни текста реплик, ни `external_user_id` — только
идентификаторы окон, сигналов, привязок и коды состояний.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.ai import (
    DangerHit,
    WindowLine,
    chat_memo_hits,
    screen_message_for_danger,
    split_stream,
)
from domsignal.ai.masking import author_alias
from domsignal.bot.max_updates import MaxEvent
from domsignal.core.signals import BindingState, buffer_text, structural_drop_reason
from domsignal.db.models import (
    ChatBinding,
    ConversationWindow,
    HouseManagement,
    Job,
    ManagementCompany,
)
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.db.repositories.passive import BufferedLine, PassiveRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.chat_connections import ChatConnectionError, ChatConnectionService
from domsignal.services.chat_voice import (
    CHAT_MESSAGE_INTENT_KIND,
    CONNECTION_NOTICE_PURPOSE,
    READING_NOTICE_PURPOSE,
    SAFETY_MEMO_PURPOSE,
    ChatMessageIntent,
    connection_notice_text,
    reading_notice_text,
    safety_memo_text,
)
from domsignal.services.errors import RescheduleJob, ResourceNotFound
from domsignal.services.signals import PassiveConfig, SignalEngine

logger = logging.getLogger(__name__)

TICK_JOB = "chat.window.tick"
ANALYZE_JOB = "ai.window.analyze"
FALLBACK_JOB = "chat.window.fallback"
PURGE_JOB = "chat.buffer.purge"

TICK_PRIORITY = 40
#: Сторож разбора окна — как `report.fallback` явного пути.
FALLBACK_PRIORITY = 50
PURGE_PRIORITY = 90
#: Повтор сообщения с кнопкой из кабинета — не чаще раза за это время.
RESEND_INTERVAL_SECONDS = 600
#: Окно с опасностью разбирается раньше явного `/report` (30) и обычных окон.
DANGER_WINDOW_PRIORITY = 20
WINDOW_PRIORITY = 60

#: Как часто повторяется очистка буфера.
PURGE_INTERVAL = timedelta(hours=1)

#: Запас к моменту тишины: ядро сравнивает строго («больше»).
_TICK_MARGIN = timedelta(seconds=1)

#: Проба тишины для политики ядра: «реплика» в момент проверки без опасности.
_PROBE_TEXT = "."


@dataclass(frozen=True)
class PassiveToggle:
    binding_id: UUID
    binding_version: int
    passive_capture_enabled: bool
    notice_queued: bool


@dataclass(frozen=True)
class BindingRef:
    """Поля привязки, нужные приёму. Снимок, а не ORM-объект: откат точки
    сохранения не должен превращать чтение поля в ленивый запрос."""

    id: UUID
    house_id: UUID
    binding_version: int
    max_chat_id: str


def _window_line(line: BufferedLine) -> WindowLine:
    return WindowLine(
        line_id=line.mid if len(line.mid) <= 128 else f"id:{line.id}",
        author_ref=line.author_ref,
        text=line.text,
        sent_at=line.sent_at,
    )


class PassiveCaptureService:
    """Приём реплик, окна, срок хранения буфера и выключатель привязки."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        connections: ChatConnectionService,
        engine: SignalEngine,
    ) -> None:
        self.sessions = session_factory
        self.connections = connections
        self.engine = engine

    @property
    def config(self) -> PassiveConfig:
        """Параметры общие с движком сигналов: у выключателя один источник."""
        return self.engine.config

    # ------------------------------------------------------------------ приём

    async def capture(self, session: AsyncSession, event: MaxEvent) -> UUID | None:
        """Положить реплику в буфер в транзакции вебхука. Возвращает её id.

        Отброшенная структурным фильтром реплика не оставляет следа.
        """
        if not self.config.capture_enabled or event.kind != "message_created":
            return None
        binding = await ChatRepository(session).active_binding(event.chat_id or "")
        reason = structural_drop_reason(
            capture_enabled=self.config.capture_enabled,
            kind=event.kind,
            chat_id=event.chat_id,
            actor=event.actor,
            mid=event.mid,
            text=event.text,
            occurred_at=event.occurred_at,
            binding=(
                BindingState(
                    status=binding.status,
                    activated_at=binding.activated_at,
                    passive_capture_enabled=binding.passive_capture_enabled,
                )
                if binding is not None
                else None
            ),
        )
        if reason is not None or binding is None:
            return None
        assert event.chat_id and event.actor and event.mid and event.text
        ref = BindingRef(
            id=binding.id,
            house_id=binding.house_id,
            binding_version=binding.binding_version,
            max_chat_id=binding.max_chat_id,
        )
        repo = PassiveRepository(session)
        author_ref = author_alias(await repo.author_index(binding.house_id, event.actor))
        text, truncated = buffer_text(event.text)
        message_id = await repo.insert_message(
            {
                "max_chat_id": event.chat_id,
                "mid": event.mid,
                "chat_binding_id": binding.id,
                "binding_version": binding.binding_version,
                "external_user_id": event.actor,
                "author_ref": author_ref,
                "text": text,
                "text_truncated": truncated,
                "reply_to_mid": event.reply_to_mid,
                "sent_at": event.occurred_at,
            }
        )
        if message_id is None:
            return None  # Та же реплика уже в буфере.
        line = BufferedLine(
            id=message_id,
            mid=event.mid,
            author_ref=author_ref,
            text=text,
            sent_at=event.occurred_at,
            reply_to_mid=event.reply_to_mid,
        )
        # Правила опасности — по полному тексту, до окна и до любой обрезки.
        hits = screen_message_for_danger(event.text, line_id=event.mid)
        window_id: UUID | None = None
        try:
            async with session.begin_nested():
                window_id = await self._assign(session, ref, line, hits)
        except Exception as exc:  # noqa: BLE001 - приём не падает из-за сборщика окон
            logger.error(
                "passive_window_failed",
                extra={"chat_binding_id": str(ref.id), "error_type": type(exc).__name__},
            )
        if hits:
            outcome: tuple[UUID, bool] | None = None
            try:
                async with session.begin_nested():
                    outcome = await self._danger(session, ref, line, hits, window_id)
            except Exception as exc:  # noqa: BLE001 - приём не падает из-за опасности
                logger.error(
                    "passive_danger_failed",
                    extra={
                        "chat_binding_id": str(ref.id),
                        "window_id": str(window_id) if window_id else None,
                        "error_type": type(exc).__name__,
                    },
                )
            if outcome is not None:
                # Журнал пишется после точки сохранения: сбой журнала не
                # должен откатывать сигнал.
                logger.info(
                    "passive_preliminary_critical",
                    extra={
                        "signal_id": str(outcome[0]),
                        "window_id": str(window_id) if window_id else None,
                        "signal_created": outcome[1],
                    },
                )
        return message_id

    # ------------------------------------------------------------------ окна

    async def _assign(
        self,
        session: AsyncSession,
        binding: BindingRef,
        line: BufferedLine,
        hits: list[DangerHit],
    ) -> UUID:
        """Привязать реплику к открытому окну или открыть новое."""
        repo = PassiveRepository(session)
        await repo.lock(f"window:{binding.id}")
        window = await repo.open_window(binding.id)
        if window is not None:
            lines = await repo.window_lines(window.id)
            groups = split_stream(
                [*map(_window_line, lines), _window_line(line)], self.config.policy
            )
            if len(groups[-1]) != len(lines) + 1:
                await self.close(session, window, self._reason(window, line.sent_at, lines))
                window = None
        if window is None:
            window = ConversationWindow(
                house_id=binding.house_id,
                chat_binding_id=binding.id,
                binding_version=binding.binding_version,
                max_chat_id=binding.max_chat_id,
                state="open",
                line_count=0,
                has_danger=False,
                first_line_at=line.sent_at,
                last_line_at=line.sent_at,
            )
            session.add(window)
            await session.flush()
        await repo.attach(line.id, window.id)
        window.line_count += 1
        window.first_line_at = min(window.first_line_at, line.sent_at)
        window.last_line_at = max(window.last_line_at, line.sent_at)
        if any(not hit.negated for hit in hits):
            # Опасность закрывает окно сразу, и разбор идёт первым.
            window.has_danger = True
            await self.close(session, window, "danger")
        elif window.line_count >= self.config.policy.max_lines:
            await self.close(session, window, "max_lines")
        else:
            await self._schedule_tick(session, window)
        return window.id

    def _reason(
        self, window: ConversationWindow, at: datetime, lines: list[BufferedLine]
    ) -> str:
        """Подпись причины для аудита. Решение уже принято политикой ядра."""
        policy = self.config.policy
        if (at - window.last_line_at).total_seconds() > policy.silence_seconds:
            return "silence"
        if len(lines) >= policy.max_lines:
            return "max_lines"
        if (at - window.first_line_at).total_seconds() > policy.max_age_seconds:
            return "max_age"
        return "silence"

    def _due(self, window: ConversationWindow) -> datetime:
        policy = self.config.policy
        return (
            min(
                window.last_line_at + timedelta(seconds=policy.silence_seconds),
                window.first_line_at + timedelta(seconds=policy.max_age_seconds),
            )
            + _TICK_MARGIN
        )

    async def _schedule_tick(self, session: AsyncSession, window: ConversationWindow) -> None:
        """Одна задача тишины на окно: живая задача сама перенесёт себя."""
        repo = PassiveRepository(session)
        if await repo.job_alive(window.tick_job_id):
            return
        now = datetime.now(UTC)
        delay = max(0, math.ceil((self._due(window) - now).total_seconds()))
        job = await ReliabilityRepository(session).add_job(
            kind=TICK_JOB,
            payload={"window_id": str(window.id)},
            priority=TICK_PRIORITY,
            delay_seconds=delay,
            now=now,
        )
        window.tick_job_id = job.id

    async def close(self, session: AsyncSession, window: ConversationWindow, reason: str) -> bool:
        """Закрыть окно и поставить разбор. Закрытое окно не закрывается повторно."""
        if window.state != "open":
            return False
        window.state = "closed"
        window.close_reason = reason
        window.closed_at = datetime.now(UTC)
        window.tick_job_id = None
        await session.flush()
        jobs = ReliabilityRepository(session)
        await jobs.add_job(
            kind=ANALYZE_JOB,
            payload={"window_id": str(window.id)},
            priority=DANGER_WINDOW_PRIORITY if window.has_danger else WINDOW_PRIORITY,
        )
        # Сторож: остановленный AI-пул задерживает сигналы окна не дольше этого.
        await jobs.add_job(
            kind=FALLBACK_JOB,
            payload={"window_id": str(window.id)},
            priority=FALLBACK_PRIORITY,
            delay_seconds=self.config.fallback_seconds,
        )
        logger.info(
            "passive_window_closed",
            extra={
                "window_id": str(window.id),
                "chat_binding_id": str(window.chat_binding_id),
                "close_reason": reason,
                "line_count": window.line_count,
            },
        )
        return True

    async def tick(self, payload: dict[str, Any]) -> None:
        """Задача тишины: закрыть окно по тишине или возрасту, иначе перенести себя."""
        window_id = UUID(str(payload["window_id"]))
        async with self.sessions() as session, session.begin():
            probe = await session.get(ConversationWindow, window_id)
            if probe is None or probe.state != "open":
                return
            repo = PassiveRepository(session)
            await repo.lock(f"window:{probe.chat_binding_id}")
            window = await repo.window_for_update(window_id)
            if window is None or window.state != "open":
                return  # Повторный тик по закрытому окну ничего не делает.
            now = datetime.now(UTC)
            lines = await repo.window_lines(window.id)
            if lines and not self._silent(lines, now):
                raise RescheduleJob(self._due(window))
            await self.close(session, window, self._reason(window, now, lines))

    def _silent(self, lines: list[BufferedLine], now: datetime) -> bool:
        """Закрыла бы политика ядра окно, если бы следующая реплика пришла сейчас."""
        probe = WindowLine(
            line_id="__tick__", author_ref="__tick__", text=_PROBE_TEXT, sent_at=now
        )
        groups = split_stream([*map(_window_line, lines), probe], self.config.policy)
        return len(groups[-1]) == 1 and groups[-1][0].line_id == "__tick__"

    # -------------------------------------------------------------- опасность

    async def _danger(
        self,
        session: AsyncSession,
        binding: BindingRef,
        line: BufferedLine,
        hits: list[DangerHit],
        window_id: UUID | None,
    ) -> tuple[UUID, bool] | None:
        """Контур 1: правила опасности в транзакции приёма, до модели.

        Возвращает сигнал и признак «создан сейчас» или `None`, если опасность
        только отрицалась.
        """
        active = [hit for hit in hits if not hit.negated]
        if not active:
            # Только отрицание («газом не пахнет»): ни сигнала, ни памятки.
            self.engine.event(
                session,
                house_id=binding.house_id,
                window_id=window_id,
                line_mid=line.mid,
                kind="danger_negated",
                details=",".join(dict.fromkeys(hit.kind for hit in hits)),
            )
            return None
        signal, created = await self.engine.preliminary(
            session,
            house_id=binding.house_id,
            binding_id=binding.id,
            window_id=window_id,
            line=line,
            hits=hits,
        )
        signal_id = signal.id
        memo = chat_memo_hits(active)
        if memo:
            # Голос бота в чате — только высокоточные формулировки правил
            # (P6b): «в соседнем доме», учения, гипотеза, прошлое и «и дымом
            # тоже тянет» без места памятки не дают; оповещение оператора —
            # как было, на любое срабатывание без отрицания.
            await self._memo(session, binding, line, memo, signal_id)
        elif any(not hit.displaced for hit in active):
            self.engine.event(
                session,
                house_id=binding.house_id,
                signal_id=signal_id,
                line_mid=line.mid,
                kind="chat_memo_not_eligible",
                details=",".join(dict.fromkeys(hit.kind for hit in active)),
            )
        return signal_id, created

    async def _memo(
        self,
        session: AsyncSession,
        binding: BindingRef,
        line: BufferedLine,
        active: list[DangerHit],
        signal_id: UUID,
    ) -> None:
        """Памятка безопасности в чат — только проверенный блок справочника."""
        kinds = tuple(dict.fromkeys(hit.kind for hit in active))
        repo = PassiveRepository(session)
        house = await self.engine.routing.house_context(session, binding.house_id)
        safety = self.engine.routing.safety(house, kinds)
        if safety is None:
            self.engine.event(
                session,
                house_id=binding.house_id,
                signal_id=signal_id,
                line_mid=line.mid,
                kind="chat_memo_unavailable",
            )
            return
        if await repo.recent_chat_memo(
            binding.id, kinds, since=datetime.now(UTC) - self.config.memo_pause
        ):
            self.engine.event(
                session,
                house_id=binding.house_id,
                signal_id=signal_id,
                line_mid=line.mid,
                kind="chat_memo_suppressed",
                details="недавно уже была памятка этого вида",
            )
            return
        intent = ChatMessageIntent(
            purpose=SAFETY_MEMO_PURPOSE,
            chat_binding_id=binding.id,
            binding_version=binding.binding_version,
            text=safety_memo_text(safety),
            signal_id=signal_id,
            danger_kinds=list(kinds),
        )
        ReliabilityRepository(session).add_outbox(
            kind=CHAT_MESSAGE_INTENT_KIND,
            aggregate_id=binding.id,
            payload=intent.model_dump(mode="json"),
            dedupe_key=f"chat_memo:{binding.id}:{line.mid}"[:100],
        )
        self.engine.event(
            session,
            house_id=binding.house_id,
            signal_id=signal_id,
            line_mid=line.mid,
            kind="chat_memo_queued",
            details=",".join(kinds),
        )

    # ----------------------------------------------------------- выключатель

    async def set_capture(
        self,
        session: AsyncSession,
        *,
        binding_id: UUID,
        actor_id: UUID,
        enabled: bool,
    ) -> PassiveToggle:
        """Включить или выключить чтение чата. Транзакция — у вызывающего.

        Право то же, что у подключения чата (`chat.connect` в текущем периоде
        управления). Включение ставит сообщение о чтении чата — один раз на
        привязку и её версию. Выключение сразу прекращает приём; собранные
        сигналы остаются.
        """
        repo = ChatRepository(session)
        binding = await repo.binding(binding_id)
        if binding is None:
            raise ResourceNotFound("Resource was not found")
        request = await self.connections.locked_request(session, binding.connection_request_id)
        await self.connections.require_authority(session, request, actor_id)
        binding = await repo.binding(binding_id)
        assert binding is not None
        if binding.status != "active":
            raise ChatConnectionError("binding_not_active")
        if enabled and not self.config.capture_enabled:
            raise ChatConnectionError("passive_capture_disabled")
        changed = binding.passive_capture_enabled != enabled
        binding.passive_capture_enabled = enabled
        notice = await self._notice(session, binding) if enabled else False
        if changed:
            self.connections.audit(
                session, binding, "passive_enabled" if enabled else "passive_disabled"
            )
        await session.flush()
        return PassiveToggle(
            binding_id=binding.id,
            binding_version=binding.binding_version,
            passive_capture_enabled=binding.passive_capture_enabled,
            notice_queued=notice,
        )

    async def _notice(
        self, session: AsyncSession, binding: ChatBinding, *, dedupe: str | None = None
    ) -> bool:
        """Сообщение о чтении чата: один раз на привязку и версию.

        С кнопкой «Открыть ДомСигнал» (D1). Без пассивного чтения — сообщение
        о подключении: бот не утверждает, что читает переписку.
        """
        dedupe = dedupe or f"chat_notice:{binding.id}:{binding.binding_version}"
        repo = PassiveRepository(session)
        if await repo.outbox_exists(dedupe):
            return False
        company = await session.scalar(
            select(ManagementCompany.name)
            .join(HouseManagement, HouseManagement.tenant_id == ManagementCompany.id)
            .where(HouseManagement.id == binding.management_id)
        )
        reading = binding.passive_capture_enabled
        intent = ChatMessageIntent(
            purpose=READING_NOTICE_PURPOSE if reading else CONNECTION_NOTICE_PURPOSE,
            chat_binding_id=binding.id,
            binding_version=binding.binding_version,
            text=reading_notice_text(company) if reading else connection_notice_text(company),
            app_button=True,
        )
        ReliabilityRepository(session).add_outbox(
            kind=CHAT_MESSAGE_INTENT_KIND,
            aggregate_id=binding.id,
            payload=intent.model_dump(mode="json"),
            dedupe_key=dedupe,
        )
        return True

    async def resend_notice(
        self, session: AsyncSession, *, binding_id: UUID, actor_id: UUID
    ) -> bool:
        """«Отправить сообщение с кнопкой ещё раз» для подключённого чата.

        Право — как у подключения (`chat.connect`). Не чаще раза в 10 минут на
        привязку: повтор в том же интервале ничего не отправляет.
        """
        repo = ChatRepository(session)
        binding = await repo.binding(binding_id)
        if binding is None:
            raise ResourceNotFound("Resource was not found")
        request = await self.connections.locked_request(session, binding.connection_request_id)
        await self.connections.require_authority(session, request, actor_id)
        binding = await repo.binding(binding_id)
        assert binding is not None
        if binding.status != "active":
            raise ChatConnectionError("binding_not_active")
        bucket = int(datetime.now(UTC).timestamp()) // RESEND_INTERVAL_SECONDS
        queued = await self._notice(
            session,
            binding,
            dedupe=f"chat_notice_again:{binding.id}:{binding.binding_version}:{bucket}",
        )
        if queued:
            self.connections.audit(session, binding, "notice_resent")
        await session.flush()
        return queued

    # -------------------------------------------------------- срок хранения

    async def purge(self, payload: dict[str, Any]) -> None:
        """Очистка буфера по сроку и после разбора; затем перенос себя."""
        del payload
        now = datetime.now(UTC)
        async with self.sessions() as session, session.begin():
            expired, consumed, roles = await PassiveRepository(session).purge(
                older_than=now - timedelta(hours=self.config.buffer_hours),
                keep_context=self.config.policy.context_lines,
            )
        logger.info(
            "passive_buffer_purged",
            extra={"expired": expired, "consumed": consumed, "unlinked_roles": roles},
        )
        raise RescheduleJob(now + PURGE_INTERVAL)

    async def ensure_purge_scheduled(self) -> bool:
        """Поставить очистку при старте воркера, если её нет в очереди."""
        async with self.sessions() as session, session.begin():
            await ChatRepository(session).lock("purge-schedule")
            alive = await session.scalar(
                select(Job.id)
                .where(Job.kind == PURGE_JOB, Job.status.in_(("pending", "leased")))
                .limit(1)
            )
            if alive is not None:
                return False
            await ReliabilityRepository(session).add_job(
                kind=PURGE_JOB, payload={}, priority=PURGE_PRIORITY
            )
            return True


__all__ = [
    "ANALYZE_JOB",
    "FALLBACK_JOB",
    "PURGE_JOB",
    "TICK_JOB",
    "PassiveCaptureService",
    "PassiveToggle",
]
