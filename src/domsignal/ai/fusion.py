"""Emergency Fusion: правила ИЛИ семантика, с журналом аудита.

Модель может **добавить** опасность, но не может молча её **отменить**.
Никакого AND и голосования: понижение возможно только по явному опровержению
с валидной цитатой, и каждое понижение записывается событием аудита.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from domsignal.ai.contracts import (
    AuditEvent,
    DangerHit,
    DangerKind,
    EmergencyDecision,
    EmergencySource,
    RefutationReason,
    SemanticDanger,
)


@dataclass(frozen=True)
class Refutation:
    """Опровержение опасности, предложенное моделью."""

    reason: RefutationReason
    quote: str
    line_id: str
    quote_valid: bool


NO_EMERGENCY = EmergencyDecision(is_emergency=False)


def _kinds(
    rule_hits: Sequence[DangerHit], semantic: Sequence[SemanticDanger]
) -> tuple[DangerKind, ...]:
    ordered: list[DangerKind] = []
    for hit in rule_hits:
        if hit.kind not in ordered:
            ordered.append(hit.kind)
    for danger in semantic:
        if danger.kind not in ordered:
            ordered.append(danger.kind)
    return tuple(ordered)


def fuse_emergency(
    rule_hits: Sequence[DangerHit],
    semantic: Sequence[SemanticDanger] = (),
    refutation: Refutation | None = None,
    *,
    signal_ref: str | None = None,
) -> tuple[EmergencyDecision, list[AuditEvent]]:
    """Свести срабатывания правил и семантику модели в одно решение."""
    events: list[AuditEvent] = []
    active_rules = [hit for hit in rule_hits if not hit.negated]
    rules_hit = bool(active_rules)
    semantic_hit = bool(semantic)
    if not rules_hit and not semantic_hit:
        return NO_EMERGENCY, events

    evidence_unverified = False
    for danger in semantic:
        if not any(item.quote_valid for item in danger.evidence):
            evidence_unverified = True
    if evidence_unverified:
        events.append(
            AuditEvent(
                kind="evidence_unverified",
                signal_ref=signal_ref,
                details="семантическая опасность без подтверждённой цитаты",
            )
        )

    downgraded = False
    downgrade_reason: RefutationReason | None = None
    if rules_hit and refutation is not None:
        if refutation.quote_valid and not semantic_hit:
            downgraded = True
            downgrade_reason = refutation.reason
            events.append(
                AuditEvent(
                    kind="emergency_downgraded",
                    signal_ref=signal_ref,
                    details=(
                        f"{'/'.join(hit.kind for hit in active_rules)}: "
                        f"{refutation.reason} — «{refutation.quote}» ({refutation.line_id})"
                    ),
                )
            )
        else:
            events.append(
                AuditEvent(
                    kind="refutation_rejected",
                    signal_ref=signal_ref,
                    details=(
                        f"{refutation.reason}: цитата не подтверждена"
                        if not refutation.quote_valid
                        else f"{refutation.reason}: модель одновременно сообщила об опасности"
                    ),
                )
            )

    sources: list[EmergencySource] = []
    if rules_hit and not downgraded:
        sources.append("rules")
    if semantic_hit:
        sources.append("semantic")
    is_emergency = bool(sources)
    # Памятка в чат — только по высокоточному срабатыванию правил (P6b):
    # семантика модели права на голос бота в чате не даёт.
    memo_allowed = (
        is_emergency
        and not downgraded
        and any(
            hit.chat_memo_eligible and not hit.negated and not hit.displaced for hit in rule_hits
        )
    )
    return (
        EmergencyDecision(
            is_emergency=is_emergency,
            sources=tuple(sources),
            kinds=_kinds(active_rules, semantic) if is_emergency else (),
            memo_allowed=memo_allowed,
            downgraded=downgraded,
            downgrade_reason=downgrade_reason,
            evidence_unverified=evidence_unverified,
        ),
        events,
    )
