"""Разбор закрытого окна: `ai.window.analyze` и сторож `chat.window.fallback`.

Образец — `ExplicitReportService`: короткая транзакция захвата → чтение окна,
контекста и открытых элементов дома → **один** вызов `WindowAnalyzer.analyze`
вне транзакции БД → короткая транзакция записи. Маскирование делает ядро на
пути к провайдеру; продукт передаёт ему только `WindowInput`.

Идемпотентность по `window_id`: запись результата подтверждает захват
(`state = analyzing` и свой `claimed_by`) и переводит окно в `done` в той же
транзакции, поэтому гонка двух задач и повторный запуск дают один набор
сигналов. Отказ провайдера, таймаут или исчерпанный бюджет не ломают разбор:
ядро отвечает результатом правил, окно закрывается с состоянием `fallback_*`.

Сторож — по образцу `report.fallback` явного пути: при закрытии окна в
операционный пул ставится `chat.window.fallback` с задержкой
`PASSIVE_ANALYSIS_FALLBACK_SECONDS`. Он делает тот же атомарный захват и
разбирает окно только правилами, без модели и без бюджета. Кто захватил
первым, тот и обрабатывает; второй тихо выходит. Остановленный AI-пул поэтому
задерживает сигналы окна не дольше задержки сторожа. В окне записывается, кто
его разобрал (`analyzed_by = ai | fallback`).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domsignal.ai import (
    OpenItem,
    SignalDraft,
    WindowAnalysis,
    WindowAnalyzer,
    WindowInput,
    WindowLine,
)
from domsignal.core.incidents import ReportCategory
from domsignal.db.models import ChatBinding, ConversationWindow, Signal
from domsignal.db.models.passive import OPEN_SIGNAL_STATUSES
from domsignal.db.repositories.passive import BufferedLine, PassiveRepository
from domsignal.services.ai_budget import PostgresBudgetGuard
from domsignal.services.ai_provenance import execution_provenance
from domsignal.services.errors import RescheduleJob
from domsignal.services.signals import (
    LineIndex,
    SignalEngine,
    danger_fits,
    open_item_danger_kinds,
    versions_of,
)

logger = logging.getLogger(__name__)

#: Захват старше этого возраста считается брошенным упавшим воркером.
CLAIM_STALE_SECONDS = 600

#: Открытых сигналов и заявок дома в окне — не больше.
MAX_OPEN_ITEMS = 10

#: Предел реплик окна ядра вместе с контекстом.
MAX_WINDOW_LINES = 40

#: Через сколько сторож проверяет снова, если окно прямо сейчас разбирают.
FALLBACK_RECHECK_SECONDS = 60

_CLAIM = text(
    """
    UPDATE conversation_windows
    SET state = 'analyzing', claimed_at = now(), claimed_by = :worker
    WHERE id = :window_id
      AND (
        state = 'closed'
        OR (state = 'analyzing' AND claimed_at < now() - make_interval(secs => :stale))
      )
    RETURNING house_id, chat_binding_id, binding_version, max_chat_id, has_danger
    """
)

_RELEASE = text(
    """
    UPDATE conversation_windows
    SET state = 'closed', claimed_at = NULL, claimed_by = NULL
    WHERE id = :window_id AND state = 'analyzing' AND claimed_by = :worker
    """
)

_SETTLE = text(
    """
    UPDATE conversation_windows
    SET state = 'done', completed_at = now(), analysis_mode = :mode,
        execution_state = :state, analysis = CAST(:analysis AS jsonb),
        analyzed_by = :analyzed_by
    WHERE id = :window_id AND state = 'analyzing' AND claimed_by = :worker
    RETURNING id
    """
)


class _LostClaim(Exception):
    """Окно успел перехватить другой воркер: запись отменяется целиком."""


@dataclass(frozen=True)
class ClaimedWindow:
    id: uuid.UUID
    worker: str
    analyzed_by: str
    house_id: uuid.UUID
    chat_binding_id: uuid.UUID
    binding_version: int
    max_chat_id: str
    has_danger: bool


@dataclass(frozen=True)
class WindowSnapshot:
    lines: list[BufferedLine]
    context: list[BufferedLine]
    open_items: tuple[OpenItem, ...]
    entrance_hint: str | None
    capturing: bool


def _line_id(line: BufferedLine) -> str:
    """Идентификатор реплики для ядра: `mid`, а длинный — стабильная замена."""
    return line.mid if len(line.mid) <= 128 else f"id:{line.id}"


def _category(value: str) -> ReportCategory:
    try:
        return ReportCategory(value)
    except ValueError:
        return ReportCategory.OTHER


class PassiveWindowAnalysis:
    """Задача AI-пула: окно → один вызов ядра → сигналы."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        engine: SignalEngine,
        analyzer: WindowAnalyzer,
        budget: PostgresBudgetGuard | None = None,
        rules_analyzer: WindowAnalyzer | None = None,
    ) -> None:
        self.sessions = session_factory
        self.engine = engine
        self.analyzer = analyzer
        self.budget = budget
        # Сторож разбирает только правилами: анализатор без провайдера.
        self.rules_analyzer = rules_analyzer or WindowAnalyzer()

    async def analyze_window(self, payload: dict[str, Any]) -> None:
        """Задача AI-пула: разбор окна ядром (с моделью, если она включена)."""
        await self._run(payload, analyzed_by="ai")

    async def analyze_with_rules(self, payload: dict[str, Any]) -> None:
        """Сторож операционного пула: то же окно, только правилами.

        Окно уже разобрано — задача тихо выходит. Окно прямо сейчас разбирает
        AI-пул — сторож проверит ещё раз позже: если тот захват окажется
        брошенным, окно разберут правила, второго набора сигналов не будет.
        """
        if await self._run(payload, analyzed_by="fallback"):
            return
        window_id = uuid.UUID(str(payload["window_id"]))
        async with self.sessions() as session:
            state = await session.scalar(
                select(ConversationWindow.state).where(ConversationWindow.id == window_id)
            )
        if state == "analyzing":
            raise RescheduleJob(datetime.now(UTC) + timedelta(seconds=FALLBACK_RECHECK_SECONDS))

    async def _run(self, payload: dict[str, Any], *, analyzed_by: str) -> bool:
        """Захват → разбор → запись. `False`, если окно захватить не удалось."""
        window_id = uuid.UUID(str(payload["window_id"]))
        prefix = "ai.window.analyze" if analyzed_by == "ai" else "chat.window.fallback"
        worker = f"{prefix}:{uuid.uuid4().hex[:16]}"
        claimed = await self._claim(window_id, worker, analyzed_by=analyzed_by)
        if claimed is None:
            return False  # Окно уже разобрано или его разбирает другой воркер.
        try:
            snapshot = await self._read(claimed)
            if not snapshot.capturing or not snapshot.lines:
                await self._settle_without_analysis(claimed, snapshot)
                return True
            analysis = await self._analyze(claimed, snapshot)
            await self._write(claimed, snapshot, analysis)
        except _LostClaim:
            logger.info("passive_window_claim_lost", extra={"window_id": str(window_id)})
        except Exception:
            await self._release(claimed)
            raise
        return True

    # ------------------------------------------------------------- захват

    async def _claim(
        self, window_id: uuid.UUID, worker: str, *, analyzed_by: str
    ) -> ClaimedWindow | None:
        async with self.sessions() as session, session.begin():
            row = (
                await session.execute(
                    _CLAIM,
                    {"window_id": window_id, "worker": worker, "stale": CLAIM_STALE_SECONDS},
                )
            ).one_or_none()
        if row is None:
            return None
        return ClaimedWindow(id=window_id, worker=worker, analyzed_by=analyzed_by, **row._mapping)

    async def _release(self, claimed: ClaimedWindow) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(_RELEASE, {"window_id": claimed.id, "worker": claimed.worker})

    # -------------------------------------------------------------- чтение

    async def _read(self, claimed: ClaimedWindow) -> WindowSnapshot:
        async with self.sessions() as session, session.begin():
            repo = PassiveRepository(session)
            binding = await session.get(ChatBinding, claimed.chat_binding_id)
            capturing = bool(
                self.engine.config.capture_enabled
                and binding is not None
                and binding.status == "active"
                and binding.binding_version == claimed.binding_version
                and binding.passive_capture_enabled
            )
            lines = await repo.window_lines(claimed.id)
            context: list[BufferedLine] = []
            if lines:
                context = await repo.context_lines(
                    claimed.chat_binding_id,
                    window_id=claimed.id,
                    before=lines[0].sent_at,
                    limit=self.engine.config.policy.context_lines,
                )
            items: list[tuple[datetime, OpenItem]] = []
            for signal in await repo.open_signals(claimed.house_id, limit=MAX_OPEN_ITEMS):
                items.append(
                    (
                        signal.last_seen_at,
                        OpenItem(
                            ref=f"signal:{signal.id}",
                            kind="signal",
                            category=_category(signal.product_category),
                            subtype=signal.subtype,
                            entrance=(signal.entrance or {}).get("value"),
                            title=signal.object_label[:200],
                            # P6: опасность вида K не ляжет в элемент без K.
                            danger_kinds=open_item_danger_kinds(signal.emergency),
                        ),
                    )
                )
            for incident in await repo.open_incidents(claimed.house_id, limit=MAX_OPEN_ITEMS):
                items.append(
                    (
                        incident.created_at,
                        OpenItem(
                            ref=f"incident:{incident.id}",
                            kind="incident",
                            category=_category(incident.category),
                            entrance=incident.location_entrance,
                            title=incident.title[:200],
                        ),
                    )
                )
            items.sort(key=lambda pair: pair[0], reverse=True)
            entrance = (
                binding.scope_value
                if binding is not None and binding.scope_type == "entrance"
                else None
            )
        # Окно ядра — не больше 40 реплик: лишний контекст отрезается первым.
        room = max(0, MAX_WINDOW_LINES - len(lines))
        return WindowSnapshot(
            lines=lines[:MAX_WINDOW_LINES],
            context=context[-room:] if room else [],
            open_items=tuple(item for _, item in items[:MAX_OPEN_ITEMS]),
            entrance_hint=entrance,
            capturing=capturing,
        )

    # --------------------------------------------------------------- разбор

    async def _analyze(self, claimed: ClaimedWindow, snapshot: WindowSnapshot) -> WindowAnalysis:
        """Один вызов ядра вне транзакции БД. Сторож — только правила."""
        analyzer = self.analyzer if claimed.analyzed_by == "ai" else self.rules_analyzer
        window = WindowInput(
            channel="group_passive",
            lines=(
                *(
                    WindowLine(
                        line_id=_line_id(line),
                        author_ref=line.author_ref,
                        text=line.text,
                        sent_at=line.sent_at,
                        reply_to=line.reply_to_mid,
                        is_context=True,
                    )
                    for line in snapshot.context
                ),
                *(
                    WindowLine(
                        line_id=_line_id(line),
                        author_ref=line.author_ref,
                        text=line.text,
                        sent_at=line.sent_at,
                        reply_to=line.reply_to_mid,
                    )
                    for line in snapshot.lines
                ),
            ),
            open_items=snapshot.open_items,
            entrance_hint=snapshot.entrance_hint,
        )
        if self.budget is None or claimed.analyzed_by != "ai":
            return await analyzer.analyze(window)
        # Единица бюджета списывается до обращения к провайдеру; исчерпанный
        # бюджет даёт `fallback_budget` и результат правил без вызова.
        async with self.budget.reserve(str(claimed.chat_binding_id)):
            return await analyzer.analyze(window)

    # --------------------------------------------------------------- запись

    async def _settle_without_analysis(
        self, claimed: ClaimedWindow, snapshot: WindowSnapshot
    ) -> None:
        """Чтение выключено или реплик нет: окно закрывается без разбора."""
        state = "capture_stopped" if not snapshot.capturing else "empty"
        async with self.sessions() as session, session.begin():
            row = await session.execute(
                _SETTLE,
                {
                    "window_id": claimed.id,
                    "worker": claimed.worker,
                    "mode": "manual",
                    "state": state,
                    "analysis": '{"provider_called": false}',
                    "analyzed_by": claimed.analyzed_by,
                },
            )
            if row.one_or_none() is None:
                raise _LostClaim()
            await PassiveRepository(session).consume(claimed.id, datetime.now(UTC))
        logger.info(
            "passive_window_skipped", extra={"window_id": str(claimed.id), "state": state}
        )

    async def _write(
        self,
        claimed: ClaimedWindow,
        snapshot: WindowSnapshot,
        analysis: WindowAnalysis,
    ) -> None:
        now = datetime.now(UTC)
        index = LineIndex({_line_id(line): line for line in snapshot.lines})
        versions = versions_of(analysis)
        summary = {
            **execution_provenance(analysis),
            "versions": versions,
            "signals": len(analysis.signals),
            "dropped_fields": analysis.dropped_fields,
            "context_lines": len(snapshot.context),
        }
        engine = self.engine
        async with self.sessions() as session, session.begin():
            repo = PassiveRepository(session)
            await repo.lock(f"signals:{claimed.house_id}")
            settled = await session.execute(
                _SETTLE,
                {
                    "window_id": claimed.id,
                    "worker": claimed.worker,
                    "mode": analysis.mode,
                    "state": analysis.execution.state,
                    "analysis": json.dumps(summary, ensure_ascii=False),
                    "analyzed_by": claimed.analyzed_by,
                },
            )
            if settled.one_or_none() is None:
                raise _LostClaim()
            ingest = await repo.ingest_links(claimed.id)
            used: set[uuid.UUID] = set()
            by_ref: dict[str, uuid.UUID] = {}
            touched: dict[uuid.UUID, list[BufferedLine]] = {}
            for draft in analysis.signals:
                signal = await self._apply(
                    session,
                    claimed,
                    draft,
                    analysis,
                    index,
                    ingest=ingest,
                    used=used,
                    entrance_hint=snapshot.entrance_hint,
                    now=now,
                )
                by_ref[draft.ref] = signal.id
                touched.setdefault(signal.id, []).extend(index.lines(draft.line_ids))
            for signal_id in set(ingest.values()) - used:
                prelim = await repo.signal_for_update(signal_id)
                if (
                    prelim is not None
                    and "preliminary" in prelim.flags
                    and prelim.status in OPEN_SIGNAL_STATUSES
                ):
                    await engine.keep_unmatched(session, prelim, window_id=claimed.id)
            await self._link_lines(session, claimed, analysis, index, by_ref, touched)
            for signal_id, lines in touched.items():
                await engine.add_quotes(session, signal_id, lines)
                await session.flush()
                await repo.recount(signal_id)
            for event in analysis.audit_events:
                engine.event(
                    session,
                    house_id=claimed.house_id,
                    signal_id=by_ref.get(event.signal_ref or ""),
                    window_id=claimed.id,
                    kind=event.kind,
                    details=event.details,
                    versions=versions,
                )
            await repo.consume(claimed.id, now)
        logger.info(
            "passive_window_analyzed",
            extra={
                "window_id": str(claimed.id),
                "analyzed_by": claimed.analyzed_by,
                "ai_mode": analysis.mode,
                "ai_state": analysis.execution.state,
                "signal_ids": [str(value) for value in dict.fromkeys(by_ref.values())],
            },
        )

    async def _apply(
        self,
        session: AsyncSession,
        claimed: ClaimedWindow,
        draft: SignalDraft,
        analysis: WindowAnalysis,
        index: LineIndex,
        *,
        ingest: dict[str, uuid.UUID],
        used: set[uuid.UUID],
        entrance_hint: str | None,
        now: datetime,
    ) -> Signal:
        """Куда ложится сигнал окна: примирение, открытый сигнал, склейка, новый."""
        engine = self.engine
        repo = PassiveRepository(session)
        key = engine.key_for(draft, entrance_hint)
        # 1. Реплика опасности уже дала предварительный сигнал при приёме.
        for line in index.lines(draft.line_ids):
            linked = ingest.get(line.mid)
            if linked is not None and linked not in used:
                used.add(linked)
                signal = await repo.signal_for_update(linked)
                if signal is not None and signal.status not in OPEN_SIGNAL_STATUSES:
                    # Оператор уже решил предварительный сигнал: решение не
                    # переписывается вердиктом окна, реплики лишь привязываются.
                    engine.event(
                        session,
                        house_id=signal.house_id,
                        signal_id=signal.id,
                        window_id=claimed.id,
                        kind="window_after_decision",
                        details=signal.status,
                    )
                    return signal
                if signal is not None:
                    if "preliminary" in signal.flags:
                        await engine.reconcile(
                            session,
                            signal,
                            window_id=claimed.id,
                            draft=draft,
                            analysis=analysis,
                            index=index,
                            key=key,
                            now=now,
                        )
                    else:
                        await engine.group(
                            session,
                            signal,
                            window_id=claimed.id,
                            draft=draft,
                            analysis=analysis,
                            index=index,
                            now=now,
                            reason="danger_line",
                        )
                    return signal
        # 2. Ядро привязало окно к открытому сигналу дома.
        if draft.ref.startswith("signal:"):
            try:
                open_id = uuid.UUID(draft.ref.removeprefix("signal:"))
            except ValueError:
                open_id = None
            signal = await repo.signal_for_update(open_id) if open_id else None
            if (
                signal is not None
                and signal.house_id == claimed.house_id
                and signal.status in ("new", "in_review")
                and (signal.strength == "filtered") == (draft.strength == "filtered")
            ):
                await engine.group(
                    session,
                    signal,
                    window_id=claimed.id,
                    draft=draft,
                    analysis=analysis,
                    index=index,
                    now=now,
                    reason="open_item",
                )
                return signal
        # 3. Ветка той же проблемы по ключу дедупликации.
        signal = await repo.open_by_key(
            claimed.house_id,
            key,
            seen_after=now - timedelta(days=engine.config.dedupe_days),
            filtered=draft.strength == "filtered",
        )
        if signal is not None and danger_fits(signal.emergency, draft.emergency):
            await engine.group(
                session,
                signal,
                window_id=claimed.id,
                draft=draft,
                analysis=analysis,
                index=index,
                now=now,
                reason="dedupe_key",
            )
            return signal
        if signal is not None:
            # Тот же ключ, но новый вид опасности: отдельный сигнал (P6b, шаг 6).
            engine.event(
                session,
                house_id=claimed.house_id,
                signal_id=signal.id,
                window_id=claimed.id,
                kind="danger_not_joined",
                details=",".join(draft.emergency.kinds),
            )
        # 4. Новая проблема.
        created = await engine.create(
            session,
            house_id=claimed.house_id,
            binding_id=claimed.chat_binding_id,
            window_id=claimed.id,
            draft=draft,
            analysis=analysis,
            index=index,
            key=key,
            now=now,
        )
        if draft.ref.startswith("incident:"):
            # Слияния с заявкой здесь нет: решение за оператором.
            engine.event(
                session,
                house_id=claimed.house_id,
                signal_id=created.id,
                window_id=claimed.id,
                kind="open_incident_match",
                details=draft.ref,
            )
        return created

    async def _link_lines(
        self,
        session: AsyncSession,
        claimed: ClaimedWindow,
        analysis: WindowAnalysis,
        index: LineIndex,
        by_ref: dict[str, uuid.UUID],
        touched: dict[uuid.UUID, list[BufferedLine]],
    ) -> None:
        """Роли реплик окна и их связь с сигналами. Без текста."""
        repo = PassiveRepository(session)
        linked: set[tuple[str, uuid.UUID]] = set()
        for verdict in analysis.lines:
            line = index.by_line_id.get(verdict.line_id)
            if line is None:
                continue
            signal_ids = list(
                dict.fromkeys(by_ref[ref] for ref in verdict.signal_refs if ref in by_ref)
            )
            if not signal_ids:
                await repo.link_line(
                    window_id=claimed.id,
                    signal_id=None,
                    line=line,
                    role=verdict.role,
                    certainty=None,
                )
                continue
            for signal_id in signal_ids:
                linked.add((line.mid, signal_id))
                await repo.link_line(
                    window_id=claimed.id,
                    signal_id=signal_id,
                    line=line,
                    role=verdict.role,
                    certainty=verdict.link_certainty,
                )
        # Реплики сигнала, которым ядро не назначило роль, всё равно считаются.
        for signal_id, lines in touched.items():
            for line in lines:
                if (line.mid, signal_id) not in linked:
                    await repo.link_line(
                        window_id=claimed.id,
                        signal_id=signal_id,
                        line=line,
                        role=None,
                        certainty=None,
                    )


__all__ = ["CLAIM_STALE_SECONDS", "FALLBACK_RECHECK_SECONDS", "PassiveWindowAnalysis"]
