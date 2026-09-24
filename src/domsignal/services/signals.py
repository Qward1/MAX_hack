"""Signal Engine продукта: запись сигналов, склейка веток, маршрут, оповещение.

Смысл сигнала решает AI-ядро: подтип, место, признаки, опасность после fusion,
сила и Inbox против Audit Pool. Продукт **не пересчитывает** силу и не
переопределяет fusion. Он делает своё:

- склеивает ветку об одном дефекте по ключу дедупликации (подтип +
  `dedupe_scope` таксономии + подъезд) в пределах `PASSIVE_DEDUPE_DAYS`;
- ограничивает слабые сигналы дома за сутки (`PASSIVE_WEAK_DAILY_LIMIT`),
  переполнение уходит в Audit Pool с причиной `weak_overflow`;
- примиряет предварительный критический сигнал правил с вердиктом окна:
  понижение — только если ядро понизило опасность по опровержению с цитатой и
  оставило событие `emergency_downgraded`; иначе сигнал остаётся критическим;
- считает маршрут детерминированным Responsibility Router при создании сигнала
  и при смене подтипа;
- ставит оповещение операторов о критическом сигнале — операционную задачу
  наивысшего приоритета, не зависящую от AI-пула; новый вид опасности у уже
  открытого сигнала (был газ, добавился дым) даёт отдельное оповещение, тот
  же вид — нет.

Заявка УК или обращение из сигнала автоматически не создаются никогда.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.ai import (
    DangerHit,
    Evidence,
    Facet,
    LocationEvidence,
    SignalDraft,
    WindowAnalysis,
    WindowPolicy,
    chat_memo_hits,
    load_taxonomy,
)
from domsignal.contracts.routing import LOCATION_SCOPES, DangerKind, LocationScope
from domsignal.core.routing import UNSPECIFIED_SUBTYPE, HouseRoutingContext
from domsignal.core.signals import (
    DANGER_LABELS,
    MAX_QUOTES,
    danger_key,
    dedupe_key,
    place_signal,
    quote_text,
    stronger,
)
from domsignal.db.models import OutboxMessage, RouteOutcome, Signal, SignalEvent
from domsignal.db.repositories.passive import BufferedLine, PassiveRepository
from domsignal.db.repositories.reliability import ReliabilityRepository
from domsignal.services.chat_voice import SIGNAL_ALERT_INTENT_KIND, SignalAlertIntent
from domsignal.services.routing import RoutingService
from domsignal.settings import Settings

#: Операционная задача оповещения операторов. Приоритет наивысший.
ALERT_JOB = "signal.alert"
ALERT_PRIORITY = 10

#: Маршруты, по которым заявка УК не создаётся и решение за внешним каналом.
_EXTERNAL_ROUTES = frozenset(
    {
        "municipality",
        "resource_supplier",
        "regional_operator",
        "other_authority",
        "emergency_service",
    }
)


@dataclass(frozen=True)
class PassiveConfig:
    """Параметры пассивного чтения. Политика окна — типа ядра."""

    capture_enabled: bool
    policy: WindowPolicy
    weak_daily_limit: int = 10
    dedupe_days: int = 7
    buffer_hours: int = 72
    danger_group_minutes: int = 30
    memo_pause_minutes: int = 30
    fallback_seconds: int = 90

    @classmethod
    def from_settings(cls, settings: Settings) -> PassiveConfig:
        return cls(
            capture_enabled=settings.passive_capture_enabled,
            policy=WindowPolicy(
                silence_seconds=settings.passive_window_silence_seconds,
                max_lines=settings.passive_window_max_lines,
                max_age_seconds=settings.passive_window_max_age_seconds,
            ),
            weak_daily_limit=settings.passive_weak_daily_limit,
            dedupe_days=settings.passive_dedupe_days,
            buffer_hours=settings.passive_buffer_hours,
            danger_group_minutes=settings.passive_danger_group_minutes,
            memo_pause_minutes=settings.passive_chat_memo_pause_minutes,
            fallback_seconds=settings.passive_analysis_fallback_seconds,
        )

    @property
    def danger_group_window(self) -> timedelta:
        """Окно склейки сообщений об опасности одного вида в одном доме."""
        return timedelta(minutes=self.danger_group_minutes)

    @property
    def memo_pause(self) -> timedelta:
        """Пауза памятки того же вида опасности в тот же чат."""
        return timedelta(minutes=self.memo_pause_minutes)


@dataclass
class LineIndex:
    """Реплики окна по идентификатору строки ядра."""

    by_line_id: dict[str, BufferedLine]

    def mid(self, line_id: str | None) -> str | None:
        if line_id is None:
            return None
        line = self.by_line_id.get(line_id)
        return line.mid if line else None

    def lines(self, line_ids: Sequence[str]) -> list[BufferedLine]:
        found = [self.by_line_id[item] for item in line_ids if item in self.by_line_id]
        return sorted(dict.fromkeys(found), key=lambda line: (line.sent_at, line.mid))


def _known_scope(value: str) -> LocationScope:
    for scope in LOCATION_SCOPES:
        if scope == value:
            return scope
    return "unknown"


def open_item_danger_kinds(emergency: dict[str, Any] | None) -> tuple[DangerKind, ...]:
    """Виды опасности открытого сигнала для ядра (`OpenItem.danger_kinds`).

    Опровергнутая опасность (`is_emergency = false`) не передаётся: новый
    сигнал того же вида должен стать отдельным, а не лечь в понижённый.
    """
    if not emergency or emergency.get("is_emergency") is False:
        return ()
    return _danger_kinds(emergency.get("kinds") or [])


def _danger_kinds(values: Sequence[str]) -> tuple[DangerKind, ...]:
    known: tuple[DangerKind, ...] = (
        "gas",
        "smoke_fire",
        "electric",
        "person_trapped",
        "flooding",
        "structural",
        "other_hazard",
    )
    return tuple(kind for kind in known if kind in values)


def _evidence(value: Evidence | None, index: LineIndex) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"value": value.value, "quote": value.quote, "line_mid": index.mid(value.line_id)}


def _location(value: LocationEvidence, index: LineIndex) -> dict[str, Any]:
    return {"value": value.value, "quote": value.quote, "line_mid": index.mid(value.line_id)}


def _facet(value: Facet, index: LineIndex) -> dict[str, Any]:
    return {"value": value.value, "quote": value.quote, "line_mid": index.mid(value.line_id)}


def _facets(draft: SignalDraft, index: LineIndex) -> dict[str, Any]:
    return {
        "current": _facet(draft.facets.current, index),
        "local": _facet(draft.facets.local, index),
        "observed": _facet(draft.facets.observed, index),
    }


def _hit(hit: DangerHit) -> dict[str, Any]:
    return {
        "kind": hit.kind,
        "line_mid": hit.line_id,
        "quote": hit.quote,
        "negated": hit.negated,
        "displaced": hit.displaced,
        "source": "rules",
    }


def draft_emergency(
    draft: SignalDraft, analysis: WindowAnalysis, index: LineIndex
) -> dict[str, Any]:
    """Решение fusion ядра как есть плюс доказательства из реплик сигнала."""
    lines = set(draft.line_ids)
    evidence: list[dict[str, Any]] = [
        {**_hit(hit), "line_mid": index.mid(hit.line_id)}
        for hit in analysis.danger_hits
        if hit.line_id in lines and not hit.negated
    ]
    for danger in analysis.semantic_danger:
        if danger.kind not in draft.emergency.kinds:
            continue
        for item in danger.evidence:
            if item.line_id in lines:
                evidence.append(
                    {
                        "kind": danger.kind,
                        "line_mid": index.mid(item.line_id),
                        "quote": item.quote,
                        "quote_valid": item.quote_valid,
                        "contextual": danger.contextual,
                        "source": "semantic",
                    }
                )
    decision = draft.emergency
    return {
        "is_emergency": decision.is_emergency,
        "kinds": list(decision.kinds),
        "sources": list(decision.sources),
        "memo_allowed": decision.memo_allowed,
        "downgraded": decision.downgraded,
        "downgrade_reason": decision.downgrade_reason,
        "evidence_unverified": decision.evidence_unverified,
        "evidence": evidence,
        "downgrades": [],
    }


def evidence_mid(evidence: Sequence[dict[str, Any]], kinds: Sequence[str]) -> str | None:
    """Реплика, в которой найдена опасность этих видов.

    Сначала срабатывание правил, затем подтверждённая цитата разбора, затем
    любая другая: оператор видит реплику-доказательство, а не первую реплику
    окна.
    """
    wanted = set(kinds)

    def rank(item: dict[str, Any]) -> int:
        if item.get("source") == "rules":
            return 0
        return 1 if item.get("quote_valid") else 2

    found = sorted(
        (
            item
            for item in evidence
            if item.get("line_mid") and (not wanted or item.get("kind") in wanted)
        ),
        key=rank,
    )
    return str(found[0]["line_mid"]) if found else None


def added_kinds(before: Sequence[str], after: Sequence[str]) -> list[str]:
    """Виды опасности, которых у сигнала раньше не было, в порядке появления."""
    known = set(before)
    return [kind for kind in dict.fromkeys(after) if kind not in known]


def versions_of(analysis: WindowAnalysis) -> dict[str, Any]:
    """Версии разбора для событий аудита: таксономия, правила, промпт, модель."""
    versions = analysis.versions
    return {
        "taxonomy": versions.taxonomy,
        "rules": versions.rules,
        "schema_id": versions.schema_id,
        "prompt": versions.prompt,
        "model": versions.model,
        "input_sha256": versions.input_sha256,
    }


class SignalEngine:
    """Запись сигналов в короткой транзакции вызывающего кода."""

    def __init__(self, routing: RoutingService, config: PassiveConfig) -> None:
        self.routing = routing
        self.config = config

    # -------------------------------------------------------------- события

    @staticmethod
    def event(
        session: AsyncSession,
        *,
        house_id: uuid.UUID,
        kind: str,
        signal_id: uuid.UUID | None = None,
        window_id: uuid.UUID | None = None,
        line_mid: str | None = None,
        details: str = "",
        versions: dict[str, Any] | None = None,
    ) -> None:
        session.add(
            SignalEvent(
                house_id=house_id,
                signal_id=signal_id,
                window_id=window_id,
                line_mid=line_mid,
                kind=kind,
                details=details,
                versions=versions,
            )
        )

    # -------------------------------------------------------------- маршрут

    async def route(
        self,
        session: AsyncSession,
        signal: Signal,
        *,
        danger_kinds: Sequence[str],
        house: HouseRoutingContext | None = None,
    ) -> RouteOutcome:
        """Маршрут по подтипу, территории и признакам опасности. Не бросает.

        Решения по сигналу исход не означает: заявку или внешний маршрут
        выбирает оператор. Поэтому `decision` — `external` для внешних
        маршрутов и `needs_clarification` для остальных.
        """
        context = house or await self.routing.house_context(session, signal.house_id)
        route = self.routing.route(
            subtype=signal.subtype,
            location_scope=_known_scope(signal.location_scope),
            house=context,
            danger_kinds=_danger_kinds(danger_kinds),
        )
        outcome = RouteOutcome(
            house_id=signal.house_id,
            source="passive",
            subtype=signal.subtype,
            location_scope=signal.location_scope,
            route_type=route.route_type,
            organization_id=route.organization_id,
            channel_id=route.channels[0].id if route.channels else None,
            decision="external" if route.route_type in _EXTERNAL_ROUTES else "needs_clarification",
            signal_id=signal.id,
        )
        session.add(outcome)
        await session.flush()
        signal.route_outcome_id = outcome.id
        self.event(
            session,
            house_id=signal.house_id,
            signal_id=signal.id,
            kind="route_assigned",
            details=f"{route.route_type} ({route.match})",
        )
        return outcome

    # ------------------------------------------------------------ оповещение

    @staticmethod
    def alert_key(signal_id: uuid.UUID, new_kinds: Sequence[str] = ()) -> str:
        """Ключ дедупликации: одно первое оповещение и одно — на каждый новый вид."""
        base = f"signal_alert:{signal_id}"
        return f"{base}:{'+'.join(sorted(new_kinds))}"[:100] if new_kinds else base

    def queue_alert(
        self,
        session: AsyncSession,
        signal: Signal,
        *,
        new_kinds: Sequence[str] = (),
        evidence: str | None = None,
    ) -> uuid.UUID:
        """Оповещение операторов: outbox + операционная задача приоритета 10."""
        outbox_id = uuid.uuid4()
        session.add(
            OutboxMessage(
                id=outbox_id,
                kind=SIGNAL_ALERT_INTENT_KIND,
                aggregate_id=signal.id,
                payload=SignalAlertIntent(
                    signal_id=signal.id,
                    house_id=signal.house_id,
                    new_kinds=list(new_kinds),
                    evidence_mid=evidence,
                ).model_dump(mode="json"),
                status="pending",
                dedupe_key=self.alert_key(signal.id, new_kinds),
            )
        )
        return outbox_id

    async def enqueue_alert(
        self,
        session: AsyncSession,
        signal: Signal,
        *,
        new_kinds: Sequence[str] = (),
        evidence: str | None = None,
    ) -> None:
        """Поставить оповещение. Уже поставленное по тому же ключу не повторяется."""
        if await PassiveRepository(session).outbox_exists(self.alert_key(signal.id, new_kinds)):
            self.event(
                session,
                house_id=signal.house_id,
                signal_id=signal.id,
                kind="operator_alert_repeat_skipped",
                details=",".join(new_kinds),
            )
            return
        outbox_id = self.queue_alert(session, signal, new_kinds=new_kinds, evidence=evidence)
        await session.flush()
        await ReliabilityRepository(session).add_job(
            kind=ALERT_JOB,
            payload={"outbox_message_id": str(outbox_id), "signal_id": str(signal.id)},
            priority=ALERT_PRIORITY,
        )
        if new_kinds:
            self.event(
                session,
                house_id=signal.house_id,
                signal_id=signal.id,
                kind="danger_kind_added",
                details=",".join(new_kinds),
            )
        self.event(
            session, house_id=signal.house_id, signal_id=signal.id, kind="operator_alert_requested"
        )

    # --------------------------------------------------------------- цитаты

    async def add_quotes(
        self, session: AsyncSession, signal_id: uuid.UUID, lines: Sequence[BufferedLine]
    ) -> None:
        """Дописать цитаты реплик ветки, пока их не станет три."""
        repo = PassiveRepository(session)
        room = MAX_QUOTES - await repo.quote_count(signal_id)
        for line in lines:
            if room <= 0:
                return
            await repo.add_quote(signal_id, line, quote_text(line.text))
            room = MAX_QUOTES - await repo.quote_count(signal_id)

    # ---------------------------------------------- предварительный сигнал

    async def preliminary(
        self,
        session: AsyncSession,
        *,
        house_id: uuid.UUID,
        binding_id: uuid.UUID,
        window_id: uuid.UUID | None,
        line: BufferedLine,
        hits: Sequence[DangerHit],
    ) -> tuple[Signal, bool]:
        """Предварительный критический сигнал правил или присоединение к нему.

        Возвращает сигнал и признак «создан сейчас». Повторное сообщение об
        опасности того же вида в доме в течение окна склейки не создаёт второго
        сигнала и второго оповещения: оно наращивает счётчики.
        """
        repo = PassiveRepository(session)
        active = [hit for hit in hits if not hit.negated]
        kinds = tuple(dict.fromkeys(hit.kind for hit in active))
        await repo.lock(f"signals:{house_id}")
        existing = await repo.recent_danger_signal(
            house_id, kinds, seen_after=line.sent_at - self.config.danger_group_window
        )
        if existing is not None:
            emergency = dict(existing.emergency)
            new_kinds = added_kinds(emergency.get("kinds", []), kinds)
            emergency["kinds"] = list(dict.fromkeys([*emergency.get("kinds", []), *kinds]))
            emergency["evidence"] = [*emergency.get("evidence", []), *map(_hit, active)]
            existing.emergency = emergency
            if window_id is not None:
                await repo.link_line(
                    window_id=window_id, signal_id=existing.id, line=line, role=None, certainty=None
                )
            await self.add_quotes(session, existing.id, [line])
            await session.flush()
            await repo.recount(existing.id)
            self.event(
                session,
                house_id=house_id,
                signal_id=existing.id,
                window_id=window_id,
                line_mid=line.mid,
                kind="danger_grouped",
                details=",".join(kinds),
            )
            if new_kinds:
                # Тот же вид в окне склейки молчит, новый вид — повод оповестить.
                await self.enqueue_alert(session, existing, new_kinds=new_kinds, evidence=line.mid)
            return existing, False
        displaced = all(hit.displaced for hit in active)
        signal = Signal(
            house_id=house_id,
            chat_binding_id=binding_id,
            window_id=window_id,
            subtype=UNSPECIFIED_SUBTYPE,
            product_category="other",
            object_label=", ".join(DANGER_LABELS.get(kind, kind) for kind in kinds)[:200],
            location_scope="unknown",
            location={"value": "unknown", "quote": None, "line_mid": None},
            facets={},
            strength="critical",
            strength_reason="rules_danger_preliminary",
            disposition="inbox",
            source="rules",
            flags=["preliminary", *(["displaced"] if displaced else [])],
            emergency={
                "is_emergency": True,
                "kinds": list(kinds),
                "sources": ["rules"],
                "memo_allowed": bool(chat_memo_hits(active)),
                "downgraded": False,
                "downgrade_reason": None,
                "evidence_unverified": False,
                "evidence": [_hit(hit) for hit in active],
                "downgrades": [],
                "preliminary": True,
            },
            dedupe_key=danger_key(kinds),
            report_count=1,
            author_count=1,
            first_seen_at=line.sent_at,
            last_seen_at=line.sent_at,
        )
        session.add(signal)
        await session.flush()
        if window_id is not None:
            await repo.link_line(
                window_id=window_id, signal_id=signal.id, line=line, role=None, certainty=None
            )
        await self.add_quotes(session, signal.id, [line])
        self.event(
            session,
            house_id=house_id,
            signal_id=signal.id,
            window_id=window_id,
            line_mid=line.mid,
            kind="preliminary_critical",
            details=",".join(kinds) + (" (displaced)" if displaced else ""),
        )
        await self.route(session, signal, danger_kinds=kinds)
        await self.enqueue_alert(session, signal, evidence=line.mid)
        return signal, True

    # ------------------------------------------------------ сигналы из окна

    async def _placement(
        self,
        session: AsyncSession,
        house_id: uuid.UUID,
        draft: SignalDraft,
        now: datetime,
    ) -> tuple[str, str | None]:
        weak_today = 0
        if draft.strength == "weak":
            weak_today = await PassiveRepository(session).weak_today(
                house_id, since=now - DAY
            )
        return place_signal(
            draft.strength,
            draft.disposition,
            audit_sample=draft.audit_sample,
            weak_today=weak_today,
            weak_limit=self.config.weak_daily_limit,
        )

    def key_for(self, draft: SignalDraft, entrance_hint: str | None) -> str:
        scope = load_taxonomy().get(draft.subtype).dedupe_scope
        entrance = draft.entrance.value if draft.entrance else entrance_hint
        return dedupe_key(draft.subtype, scope, entrance)

    async def create(
        self,
        session: AsyncSession,
        *,
        house_id: uuid.UUID,
        binding_id: uuid.UUID,
        window_id: uuid.UUID,
        draft: SignalDraft,
        analysis: WindowAnalysis,
        index: LineIndex,
        key: str,
        now: datetime,
    ) -> Signal:
        disposition, audit_reason = await self._placement(session, house_id, draft, now)
        lines = index.lines(draft.line_ids)
        first = lines[0].sent_at if lines else now
        last = lines[-1].sent_at if lines else now
        signal = Signal(
            house_id=house_id,
            chat_binding_id=binding_id,
            window_id=window_id,
            subtype=draft.subtype,
            product_category=draft.product_category.value,
            object_label=draft.object_label[:200],
            entrance=_evidence(draft.entrance, index),
            floor=_evidence(draft.floor, index),
            since=_evidence(draft.since, index),
            location_scope=draft.location_scope.value,
            location=_location(draft.location_scope, index),
            facets=_facets(draft, index),
            strength=draft.strength,
            strength_reason=draft.strength_reason,
            disposition=disposition,
            audit_reason=audit_reason,
            source=draft.source,
            flags=list(draft.flags),
            emergency=draft_emergency(draft, analysis, index),
            dedupe_key=key,
            report_count=0,
            author_count=0,
            first_seen_at=first,
            last_seen_at=last,
        )
        session.add(signal)
        await session.flush()
        self.event(
            session,
            house_id=house_id,
            signal_id=signal.id,
            window_id=window_id,
            kind="signal_created",
            details=f"{draft.strength}/{disposition}",
        )
        if audit_reason == "weak_overflow":
            self.event(
                session,
                house_id=house_id,
                signal_id=signal.id,
                window_id=window_id,
                kind="weak_overflow",
                details=f"limit={self.config.weak_daily_limit}",
            )
        await self.route(session, signal, danger_kinds=draft.emergency.kinds)
        if draft.emergency.is_emergency:
            # Опасность, которую нашло окно, а не правила приёма: оператора
            # оповещаем, в чат не пишем.
            await self.enqueue_alert(
                session,
                signal,
                evidence=evidence_mid(signal.emergency["evidence"], draft.emergency.kinds),
            )
        return signal

    async def group(
        self,
        session: AsyncSession,
        signal: Signal,
        *,
        window_id: uuid.UUID,
        draft: SignalDraft,
        analysis: WindowAnalysis,
        index: LineIndex,
        now: datetime,
        reason: str,
    ) -> None:
        """Ветка той же проблемы: растут счётчики, сила только растёт."""
        was_critical = signal.strength == "critical"
        before = list((signal.emergency or {}).get("kinds", []))
        fresh: dict[str, Any] | None = None
        if stronger(signal.strength, draft.strength):
            disposition, audit_reason = await self._placement(
                session, signal.house_id, draft, now
            )
            signal.strength = draft.strength
            signal.strength_reason = draft.strength_reason
            signal.disposition = disposition
            signal.audit_reason = audit_reason
        if draft.emergency.is_emergency:
            emergency = dict(signal.emergency or {})
            fresh = draft_emergency(draft, analysis, index)
            emergency["is_emergency"] = True
            emergency["kinds"] = list(dict.fromkeys([*emergency.get("kinds", []), *fresh["kinds"]]))
            emergency["sources"] = list(
                dict.fromkeys([*emergency.get("sources", []), *fresh["sources"]])
            )
            emergency["evidence"] = [*emergency.get("evidence", []), *fresh["evidence"]]
            signal.emergency = emergency
        self.event(
            session,
            house_id=signal.house_id,
            signal_id=signal.id,
            window_id=window_id,
            kind="signal_grouped",
            details=reason,
        )
        if fresh is None:
            return
        if not was_critical:
            await self.enqueue_alert(
                session, signal, evidence=evidence_mid(fresh["evidence"], fresh["kinds"])
            )
        elif new_kinds := added_kinds(before, fresh["kinds"]):
            # Открытый критический сигнал получил вид опасности, которого у
            # него не было (P7a: «человек не может выйти» у газового сигнала).
            await self.enqueue_alert(
                session,
                signal,
                new_kinds=new_kinds,
                evidence=evidence_mid(fresh["evidence"], new_kinds),
            )

    async def reconcile(
        self,
        session: AsyncSession,
        signal: Signal,
        *,
        window_id: uuid.UUID,
        draft: SignalDraft,
        analysis: WindowAnalysis,
        index: LineIndex,
        key: str,
        now: datetime,
    ) -> None:
        """Предварительный критический сигнал против вердикта окна.

        Модель может добавить опасность и не может молча её отменить: понижение
        принимается, только если ядро понизило опасность по опровержению с
        валидной цитатой и оставило событие `emergency_downgraded`.
        """
        decision = draft.emergency
        downgrade = next(
            (
                event
                for event in analysis.audit_events
                if event.kind == "emergency_downgraded" and event.signal_ref == draft.ref
            ),
            None,
        )
        emergency = dict(signal.emergency or {})
        before = list(emergency.get("kinds", []))
        fresh = draft_emergency(draft, analysis, index)
        emergency["preliminary"] = False
        emergency["sources"] = list(
            dict.fromkeys([*emergency.get("sources", []), *fresh["sources"]])
        )
        emergency["evidence"] = [*emergency.get("evidence", []), *fresh["evidence"]]
        emergency["evidence_unverified"] = fresh["evidence_unverified"]
        if decision.is_emergency:
            emergency["kinds"] = list(
                dict.fromkeys([*emergency.get("kinds", []), *fresh["kinds"]])
            )
            signal.strength_reason = draft.strength_reason
        elif decision.downgraded and downgrade is not None:
            disposition, audit_reason = await self._placement(
                session, signal.house_id, draft, now
            )
            signal.strength = draft.strength
            signal.strength_reason = draft.strength_reason
            signal.disposition = disposition
            signal.audit_reason = audit_reason
            emergency["is_emergency"] = False
            emergency["memo_allowed"] = False
            emergency["downgraded"] = True
            emergency["downgrade_reason"] = decision.downgrade_reason
            emergency["downgrades"] = [
                *emergency.get("downgrades", []),
                {
                    "reason": decision.downgrade_reason,
                    "details": downgrade.details,
                    "window_id": str(window_id),
                    "at": now.isoformat(),
                },
            ]
        else:
            # Вердикт окна не подтвердил опасность, но и не опроверг её цитатой:
            # сигнал остаётся критическим.
            self.event(
                session,
                house_id=signal.house_id,
                signal_id=signal.id,
                window_id=window_id,
                kind="emergency_kept",
                details="окно не опровергло опасность цитатой",
            )
        signal.emergency = emergency
        signal.subtype = draft.subtype
        signal.product_category = draft.product_category.value
        signal.object_label = draft.object_label[:200]
        signal.entrance = _evidence(draft.entrance, index)
        signal.floor = _evidence(draft.floor, index)
        signal.since = _evidence(draft.since, index)
        signal.location_scope = draft.location_scope.value
        signal.location = _location(draft.location_scope, index)
        signal.facets = _facets(draft, index)
        signal.source = "rules+model" if draft.source != "rules" else "rules"
        kept = [flag for flag in signal.flags if flag != "preliminary"]
        signal.flags = list(dict.fromkeys([*kept, "reconciled", *draft.flags]))
        signal.dedupe_key = key
        self.event(
            session,
            house_id=signal.house_id,
            signal_id=signal.id,
            window_id=window_id,
            kind="preliminary_reconciled",
            details=f"{signal.strength}/{signal.subtype}",
        )
        await session.flush()
        await self.route(
            session,
            signal,
            danger_kinds=emergency.get("kinds", []) if signal.strength == "critical" else (),
        )
        if decision.is_emergency and (new_kinds := added_kinds(before, fresh["kinds"])):
            # Разбор окна нашёл у предварительного сигнала ещё один вид опасности.
            await self.enqueue_alert(
                session,
                signal,
                new_kinds=new_kinds,
                evidence=evidence_mid(fresh["evidence"], new_kinds),
            )

    async def keep_unmatched(
        self, session: AsyncSession, signal: Signal, *, window_id: uuid.UUID
    ) -> None:
        """Окно не вернуло сигнала на реплику опасности: опасность остаётся."""
        emergency = dict(signal.emergency or {})
        emergency["preliminary"] = False
        signal.emergency = emergency
        signal.flags = list(
            dict.fromkeys([*(flag for flag in signal.flags if flag != "preliminary"), "reconciled"])
        )
        signal.version += 1
        self.event(
            session,
            house_id=signal.house_id,
            signal_id=signal.id,
            window_id=window_id,
            kind="emergency_kept",
            details="окно не вернуло сигнала на реплику опасности",
        )


DAY = timedelta(days=1)


__all__ = [
    "ALERT_JOB",
    "ALERT_PRIORITY",
    "LineIndex",
    "PassiveConfig",
    "SignalEngine",
    "added_kinds",
    "draft_emergency",
    "evidence_mid",
    "open_item_danger_kinds",
    "versions_of",
]
