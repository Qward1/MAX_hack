"""Сила сигнала, Inbox против Audit Pool и помощник явного пути.

Компетенция управляющей организации на силу сигнала не влияет: проблема вне
зоны УК остаётся сигналом с внешним маршрутом. Кто отвечает — решает
детерминированный Responsibility Router продукта, не это ядро.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from domsignal.ai.contracts import (
    AuditEvent,
    Disposition,
    EmergencyDecision,
    ExplicitReportDecision,
    Facets,
    LineVerdict,
    OpenItem,
    SignalDraft,
    SignalStrength,
    WindowAnalysis,
    WindowInput,
)
from domsignal.ai.taxonomy import UNSPECIFIED, Taxonomy
from domsignal.core.incidents import ReportCategory

#: Доля окон без сигналов в Inbox, попадающих в выборочный аудит, в процентах.
DEFAULT_AUDIT_RATE = 10

NO_EMERGENCY = EmergencyDecision(is_emergency=False)


def decide_strength(emergency: EmergencyDecision, facets: Facets) -> tuple[SignalStrength, str]:
    """Сила сигнала сверху вниз, первая подошедшая строка, с кодом причины."""
    if emergency.is_emergency:
        return "critical", "emergency"
    for name in ("local", "observed", "current"):
        facet = getattr(facets, name)
        if facet.value == "no" and facet.quote:
            return "filtered", f"facet_no_{name}"
    # «no» без подтверждающей цитаты считается «unclear»: уклон в захват.
    values = tuple(
        "unclear" if facet.value == "no" and not facet.quote else facet.value
        for facet in (facets.current, facets.local, facets.observed)
    )
    if all(value == "yes" for value in values):
        return "strong", "all_facets_yes"
    if values[2] == "yes" and all(value in ("yes", "unclear") for value in values):
        return "medium", "observed_yes"
    return "weak", "facets_unclear"


def disposition_for(strength: SignalStrength) -> Disposition:
    return "audit_pool" if strength == "filtered" else "inbox"


def may_join_open_item(emergency: EmergencyDecision, item: OpenItem) -> bool:
    """Инвариант привязки: опасность вида K — только к элементу, где K уже есть.

    Живой прогон P7a: «женщина стучит, двери не открываются» ушло в открытый
    сигнал о газе, и новый вид опасности растворился в старом сигнале. Такой
    черновик становится новым сигналом. Проверка в коде, а не в промпте.
    """
    if not emergency.is_emergency:
        return True
    return all(kind in item.danger_kinds for kind in emergency.kinds)


def subtype_from_danger(
    signals: Sequence[SignalDraft], taxonomy: Taxonomy
) -> tuple[tuple[SignalDraft, ...], tuple[AuditEvent, ...]]:
    """Подтип по виду опасности, если модель или правила его не определили.

    Живой шаг 4 P6b: газовый сигнал после разбора стал «Другое». Опасность
    при подтипе `other.unspecified` даёт подтип таксономии, когда вид
    опасности задаёт его однозначно (`Taxonomy.subtype_for_danger`); иначе
    сигнал не меняется. Проверка в коде, а не в промпте.
    """
    fallback_label = taxonomy.get(UNSPECIFIED).label
    fixed: list[SignalDraft] = []
    events: list[AuditEvent] = []
    for signal in signals:
        code = (
            taxonomy.subtype_for_danger(signal.emergency.kinds)
            if signal.subtype == UNSPECIFIED and signal.emergency.is_emergency
            else None
        )
        if code is None:
            fixed.append(signal)
            continue
        subtype = taxonomy.get(code)
        label = signal.object_label
        fixed.append(
            signal.model_copy(
                update={
                    "subtype": code,
                    "product_category": subtype.product_category,
                    "object_label": subtype.label if label in ("", fallback_label) else label,
                    "flags": (*signal.flags, "subtype_from_danger"),
                }
            )
        )
        events.append(
            AuditEvent(
                kind="subtype_from_danger",
                signal_ref=signal.ref,
                details=f"{UNSPECIFIED} → {code} по опасности {'/'.join(signal.emergency.kinds)}",
            )
        )
    return tuple(fixed), tuple(events)


def rename_refs(
    verdicts: Sequence[LineVerdict], renamed: dict[str, str]
) -> tuple[LineVerdict, ...]:
    """Переписать ссылки реплик на сигналы после переименования черновиков."""
    if not renamed:
        return tuple(verdicts)

    def resolve(ref: str) -> str:
        seen: set[str] = set()
        while ref in renamed and ref not in seen:
            seen.add(ref)
            ref = renamed[ref]
        return ref

    return tuple(
        verdict.model_copy(
            update={
                "signal_refs": tuple(dict.fromkeys(resolve(ref) for ref in verdict.signal_refs))
            }
        )
        if any(ref in renamed for ref in verdict.signal_refs)
        else verdict
        for verdict in verdicts
    )


def input_sha256(window: WindowInput) -> str:
    """Стабильный отпечаток входа окна: одинаковый вход — одинаковый хэш."""
    payload = {
        "channel": window.channel,
        "entrance_hint": window.entrance_hint,
        "lines": [
            {
                "line_id": line.line_id,
                "author_ref": line.author_ref,
                "text": line.text,
                "sent_at": line.sent_at.isoformat(),
                "reply_to": line.reply_to,
                "is_context": line.is_context,
            }
            for line in window.lines
        ],
        "open_items": [
            {
                "ref": item.ref,
                "kind": item.kind,
                "category": item.category.value,
                "subtype": item.subtype,
                "entrance": item.entrance,
                "title": item.title,
                # Новое поле попадает в отпечаток, только когда задано: прежние
                # окна сохраняют прежний хэш.
                **({"danger_kinds": list(item.danger_kinds)} if item.danger_kinds else {}),
            }
            for item in window.open_items
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def audit_sample(digest: str, audit_rate: int = DEFAULT_AUDIT_RATE) -> bool:
    """Детерминированная выборка окон, где не осталось сигналов в Inbox."""
    if audit_rate <= 0:
        return False
    if audit_rate >= 100:
        return True
    bucket = int(hashlib.sha256(digest.encode("utf-8")).hexdigest(), 16) % 100
    return bucket < audit_rate


def apply_audit_sample(
    signals: Sequence[SignalDraft], digest: str, audit_rate: int = DEFAULT_AUDIT_RATE
) -> tuple[SignalDraft, ...]:
    """Пометить сигналы окна, попавшего в выборочный аудит."""
    if any(signal.disposition == "inbox" for signal in signals):
        return tuple(signals)
    if not audit_sample(digest, audit_rate):
        return tuple(signals)
    return tuple(signal.model_copy(update={"audit_sample": True}) for signal in signals)


def _aggregate_emergency(signals: Sequence[SignalDraft]) -> EmergencyDecision:
    for signal in signals:
        if signal.emergency.is_emergency:
            return signal.emergency
    return signals[0].emergency if signals else NO_EMERGENCY


def decide_explicit_report(analysis: WindowAnalysis) -> ExplicitReportDecision:
    """Правило «уверенной зоны» D6 для формы mini app и `/report`.

    Уверенность объявляется только когда в Inbox ровно один сигнал и методы
    согласованы: в режиме модели категория модели совпала с единственной
    категорией правил, в режиме правил словарь дал ровно одну категорию.
    Иначе продукт получает `other` и спрашивает жителя.
    """
    inbox = [signal for signal in analysis.signals if signal.disposition == "inbox"]
    emergency = _aggregate_emergency(analysis.signals)
    single = inbox[0] if len(inbox) == 1 else None
    entrance = single.entrance if single else None
    floor = single.floor if single else None
    since = single.since if single else None

    if analysis.mode == "manual" or not inbox:
        reason = "no_signals"
    elif len(inbox) > 1:
        reason = "multiple_signals"
    elif analysis.mode == "model":
        reason = (
            "confident" if "rules_agree" in (single.flags if single else ()) else ("rules_disagree")
        )
    else:
        categories = {signal.product_category for signal in analysis.signals}
        reason = "confident" if len(categories) == 1 else "multiple_categories"

    confident = reason == "confident" and single is not None
    return ExplicitReportDecision(
        product_category=(
            single.product_category if confident and single else ReportCategory.OTHER
        ),
        subtype=single.subtype if confident and single else None,
        location_scope=single.location_scope.value if confident and single else "unknown",
        analysis_mode=analysis.mode,
        confident=confident,
        reason=reason,
        entrance=entrance,
        floor=floor,
        since=since,
        emergency=emergency,
    )
