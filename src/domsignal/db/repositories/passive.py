"""Запросы пассивного чтения чата: буфер, окна, сигналы и срок хранения.

Блокировки — рекомендательные ключи PostgreSQL в том же пространстве, что и у
подключения чатов. Порядок, общий для всех путей: событие вебхука →
`authors:<дом>` → `window:<привязка>` → `signals:<дом>`. Тик окна берёт только
`window:`, запись разбора — только `signals:`, поэтому цикла ожидания нет.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import Row, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.db.models import (
    ChatAuthorAlias,
    ChatMessage,
    ConversationWindow,
    Incident,
    Job,
    OutboxMessage,
    Signal,
    SignalLine,
    SignalQuote,
)
from domsignal.db.models.passive import OPEN_SIGNAL_STATUSES
from domsignal.db.repositories.chat_connections import ChatRepository
from domsignal.db.repositories.incidents import OPEN_STATUSES as OPEN_INCIDENT_STATUSES


@dataclass(frozen=True)
class BufferedLine:
    """Реплика буфера в том виде, в каком её читает сборщик окна и разбор."""

    id: uuid.UUID
    mid: str
    author_ref: str
    text: str
    sent_at: datetime
    reply_to_mid: str | None


def _line(row: Row[Any]) -> BufferedLine:
    return BufferedLine(
        id=row.id,
        mid=row.mid,
        author_ref=row.author_ref,
        text=row.text,
        sent_at=row.sent_at,
        reply_to_mid=row.reply_to_mid,
    )


_LINE_COLUMNS = (
    ChatMessage.id,
    ChatMessage.mid,
    ChatMessage.author_ref,
    ChatMessage.text,
    ChatMessage.sent_at,
    ChatMessage.reply_to_mid,
)

#: Удалить разобранные реплики, оставив последние `keep` разобранных на чат:
#: они нужны следующему окну как контекст.
_PURGE_CONSUMED = text(
    """
    DELETE FROM chat_messages
    WHERE id IN (
        SELECT id FROM (
            SELECT id, row_number() OVER (
                PARTITION BY max_chat_id ORDER BY sent_at DESC, id DESC
            ) AS position
            FROM chat_messages
            WHERE consumed_at IS NOT NULL
        ) ranked
        WHERE ranked.position > :keep
    )
    """
)

#: Счётчики сигнала — из его строк реплик. Счётчик не уменьшается: строка
#: предварительного сигнала без окна тоже учтена при создании. Каждое изменение
#: сигнала ядром увеличивает его версию: решение оператора по устаревшему
#: снимку получает 409 и перечитывает карточку.
_RECOUNT = text(
    """
    UPDATE signals AS s
    SET report_count = GREATEST(s.report_count, c.lines),
        author_count = GREATEST(s.author_count, c.authors),
        last_seen_at = GREATEST(s.last_seen_at, COALESCE(c.last_at, s.last_seen_at)),
        version = s.version + 1,
        updated_at = now()
    FROM (
        SELECT count(DISTINCT line_mid) AS lines,
               count(DISTINCT author_ref) AS authors,
               max(sent_at) AS last_at
        FROM signal_lines
        WHERE signal_id = :signal_id
    ) AS c
    WHERE s.id = :signal_id
    """
)


class PassiveRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.locks = ChatRepository(session)

    async def lock(self, key: str) -> None:
        await self.locks.lock(key)

    # ------------------------------------------------------------- буфер

    async def author_index(self, house_id: uuid.UUID, external_user_id: str) -> int:
        """Номер псевдонима автора в пределах дома; новый автор получает следующий."""
        await self.lock(f"authors:{house_id}")
        index = await self.session.scalar(
            select(ChatAuthorAlias.alias_index).where(
                ChatAuthorAlias.house_id == house_id,
                ChatAuthorAlias.external_user_id == external_user_id,
            )
        )
        if index is not None:
            return int(index)
        following = await self.session.scalar(
            select(func.coalesce(func.max(ChatAuthorAlias.alias_index) + 1, 0)).where(
                ChatAuthorAlias.house_id == house_id
            )
        )
        value = int(following or 0)
        self.session.add(
            ChatAuthorAlias(
                house_id=house_id, external_user_id=external_user_id, alias_index=value
            )
        )
        await self.session.flush()
        return value

    async def insert_message(self, values: dict[str, Any]) -> uuid.UUID | None:
        """Положить реплику; повтор той же пары чат + `mid` ничего не создаёт."""
        statement = (
            insert(ChatMessage)
            .values(id=uuid.uuid4(), **values)
            .on_conflict_do_nothing(constraint="uq_chat_messages_chat_mid")
            .returning(ChatMessage.id)
        )
        return cast(uuid.UUID | None, await self.session.scalar(statement))

    async def attach(self, message_id: uuid.UUID, window_id: uuid.UUID) -> None:
        await self.session.execute(
            update(ChatMessage).where(ChatMessage.id == message_id).values(window_id=window_id)
        )

    # -------------------------------------------------------------- окна

    async def open_window(self, binding_id: uuid.UUID) -> ConversationWindow | None:
        return cast(
            ConversationWindow | None,
            await self.session.scalar(
                select(ConversationWindow)
                .where(
                    ConversationWindow.chat_binding_id == binding_id,
                    ConversationWindow.state == "open",
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )

    async def window_for_update(self, window_id: uuid.UUID) -> ConversationWindow | None:
        return cast(
            ConversationWindow | None,
            await self.session.scalar(
                select(ConversationWindow)
                .where(ConversationWindow.id == window_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )

    async def window_lines(self, window_id: uuid.UUID) -> list[BufferedLine]:
        rows = await self.session.execute(
            select(*_LINE_COLUMNS)
            .where(ChatMessage.window_id == window_id)
            .order_by(ChatMessage.sent_at, ChatMessage.id)
        )
        return [_line(row) for row in rows]

    async def context_lines(
        self,
        binding_id: uuid.UUID,
        *,
        window_id: uuid.UUID,
        before: datetime,
        limit: int,
    ) -> list[BufferedLine]:
        """До `limit` предыдущих реплик той же привязки — только для чтения."""
        if limit <= 0:
            return []
        rows = await self.session.execute(
            select(*_LINE_COLUMNS)
            .where(
                ChatMessage.chat_binding_id == binding_id,
                ChatMessage.sent_at < before,
                (ChatMessage.window_id.is_(None)) | (ChatMessage.window_id != window_id),
            )
            .order_by(ChatMessage.sent_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        return list(reversed([_line(row) for row in rows]))

    async def job_alive(self, job_id: uuid.UUID | None) -> bool:
        if job_id is None:
            return False
        status = await self.session.scalar(select(Job.status).where(Job.id == job_id))
        return status in {"pending", "leased"}

    async def consume(self, window_id: uuid.UUID, at: datetime) -> None:
        await self.session.execute(
            update(ChatMessage)
            .where(ChatMessage.window_id == window_id, ChatMessage.consumed_at.is_(None))
            .values(consumed_at=at)
        )

    # ----------------------------------------------------------- сигналы

    async def open_signals(self, house_id: uuid.UUID, *, limit: int) -> list[Signal]:
        return list(
            await self.session.scalars(
                select(Signal)
                .where(
                    Signal.house_id == house_id,
                    Signal.status.in_(OPEN_SIGNAL_STATUSES),
                    Signal.disposition == "inbox",
                )
                .order_by(Signal.last_seen_at.desc(), Signal.id)
                .limit(limit)
            )
        )

    async def open_incidents(self, house_id: uuid.UUID, *, limit: int) -> list[Incident]:
        return list(
            await self.session.scalars(
                select(Incident)
                .where(
                    Incident.house_id == house_id,
                    Incident.status.in_(OPEN_INCIDENT_STATUSES),
                )
                .order_by(Incident.created_at.desc(), Incident.id)
                .limit(limit)
            )
        )

    async def signal_for_update(self, signal_id: uuid.UUID) -> Signal | None:
        return cast(
            Signal | None,
            await self.session.scalar(
                select(Signal)
                .where(Signal.id == signal_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ),
        )

    async def open_by_key(
        self,
        house_id: uuid.UUID,
        key: str,
        *,
        seen_after: datetime,
        filtered: bool,
    ) -> Signal | None:
        """Открытый сигнал дома с тем же ключом склейки, самый свежий.

        Отброшенное (`filtered`) и сигналы очереди не смешиваются: «в соседнем
        доме тоже не работает лифт» не должно наращивать счётчик проблемы дома.
        """
        strength = Signal.strength == "filtered" if filtered else Signal.strength != "filtered"
        return cast(
            Signal | None,
            await self.session.scalar(
                select(Signal)
                .where(
                    Signal.house_id == house_id,
                    Signal.dedupe_key == key,
                    Signal.status.in_(OPEN_SIGNAL_STATUSES),
                    Signal.last_seen_at >= seen_after,
                    strength,
                )
                .order_by(Signal.last_seen_at.desc(), Signal.id)
                .with_for_update()
                .limit(1)
            ),
        )

    async def recent_danger_signal(
        self,
        house_id: uuid.UUID,
        kinds: tuple[str, ...],
        *,
        seen_after: datetime,
    ) -> Signal | None:
        """Открытый критический сигнал дома с тем же видом опасности."""
        return cast(
            Signal | None,
            await self.session.scalar(
                select(Signal)
                .where(
                    Signal.house_id == house_id,
                    Signal.status.in_(OPEN_SIGNAL_STATUSES),
                    Signal.strength == "critical",
                    Signal.last_seen_at >= seen_after,
                    Signal.emergency["kinds"].has_any(array(list(kinds))),
                )
                .order_by(Signal.last_seen_at.desc(), Signal.id)
                .with_for_update()
                .limit(1)
            ),
        )

    async def weak_today(self, house_id: uuid.UUID, *, since: datetime) -> int:
        """Слабые сигналы дома, попавшие в очередь оператора за сутки."""
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(Signal)
                .where(
                    Signal.house_id == house_id,
                    Signal.strength == "weak",
                    Signal.disposition == "inbox",
                    Signal.created_at >= since,
                )
            )
            or 0
        )

    async def ingest_links(self, window_id: uuid.UUID) -> dict[str, uuid.UUID]:
        """Какие реплики окна уже привязаны к сигналу при приёме (опасность)."""
        rows = await self.session.execute(
            select(SignalLine.line_mid, SignalLine.signal_id)
            .where(SignalLine.window_id == window_id, SignalLine.signal_id.is_not(None))
            .order_by(SignalLine.created_at, SignalLine.id)
        )
        links: dict[str, uuid.UUID] = {}
        for mid, signal_id in rows:
            links.setdefault(mid, signal_id)
        return links

    async def link_line(
        self,
        *,
        window_id: uuid.UUID,
        signal_id: uuid.UUID | None,
        line: BufferedLine,
        role: str | None,
        certainty: str | None,
    ) -> None:
        """Роль реплики окна; для сигнала — повтор обновляет роль, а не дублирует."""
        statement = insert(SignalLine).values(
            id=uuid.uuid4(),
            window_id=window_id,
            signal_id=signal_id,
            line_mid=line.mid,
            author_ref=line.author_ref,
            role=role,
            link_certainty=certainty,
            sent_at=line.sent_at,
        )
        if signal_id is None:
            await self.session.execute(statement)
            return
        await self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_signal_line",
                set_={
                    "role": func.coalesce(statement.excluded.role, SignalLine.role),
                    "link_certainty": func.coalesce(
                        statement.excluded.link_certainty, SignalLine.link_certainty
                    ),
                },
            )
        )

    async def quote_count(self, signal_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(SignalQuote)
                .where(SignalQuote.signal_id == signal_id)
            )
            or 0
        )

    async def add_quote(self, signal_id: uuid.UUID, line: BufferedLine, text_value: str) -> None:
        await self.session.execute(
            insert(SignalQuote)
            .values(
                id=uuid.uuid4(),
                signal_id=signal_id,
                line_mid=line.mid,
                author_ref=line.author_ref,
                text=text_value,
                sent_at=line.sent_at,
            )
            .on_conflict_do_nothing(constraint="uq_signal_quote_line")
        )

    async def recount(self, signal_id: uuid.UUID) -> None:
        await self.session.execute(_RECOUNT, {"signal_id": signal_id})

    async def first_quote(self, signal_id: uuid.UUID) -> SignalQuote | None:
        return cast(
            SignalQuote | None,
            await self.session.scalar(
                select(SignalQuote)
                .where(SignalQuote.signal_id == signal_id)
                .order_by(SignalQuote.sent_at, SignalQuote.id)
                .limit(1)
            ),
        )

    async def recent_chat_memo(
        self, binding_id: uuid.UUID, kinds: tuple[str, ...], *, since: datetime
    ) -> bool:
        """Была ли уже памятка этого вида опасности в этот чат недавно."""
        found = await self.session.scalar(
            select(OutboxMessage.id)
            .where(
                OutboxMessage.aggregate_id == binding_id,
                OutboxMessage.kind == "chat.message.v1",
                OutboxMessage.payload["purpose"].astext == "chat_safety_memo",
                OutboxMessage.payload["danger_kinds"].has_any(array(list(kinds))),
                OutboxMessage.created_at >= since,
            )
            .limit(1)
        )
        return found is not None

    async def outbox_exists(self, dedupe_key: str) -> bool:
        found = await self.session.scalar(
            select(OutboxMessage.id).where(OutboxMessage.dedupe_key == dedupe_key)
        )
        return found is not None

    # --------------------------------------------------------- хранение

    async def purge(self, *, older_than: datetime, keep_context: int) -> tuple[int, int, int]:
        """Срок хранения буфера. Возвращает число удалённых строк по видам."""
        expired = await self.session.execute(
            delete(ChatMessage).where(ChatMessage.received_at < older_than)
        )
        consumed = await self.session.execute(_PURGE_CONSUMED, {"keep": keep_context})
        roles = await self.session.execute(
            delete(SignalLine).where(
                SignalLine.signal_id.is_(None), SignalLine.created_at < older_than
            )
        )
        return (
            _affected(expired),
            _affected(consumed),
            _affected(roles),
        )


def _affected(result: Any) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["BufferedLine", "PassiveRepository"]
