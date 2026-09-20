"""Анализ окна без модели — вариант C эксперимента E0c.

Гейт по реплике → реплика-ответ на прошедшую тоже проходит → «горячее окно»:
после прошедшей реплики следующие не более четырёх реплик в пределах пяти
минут присоединяются как `me_too` или `more_info`.

Сила сигнала в этом режиме: опасность правил без отрицания → `critical`,
иначе `weak` — признаки остаются `unclear`, потому что без модели ответа на
вопросы «сейчас ли», «у нас ли» и «наблюдение ли» нет.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from domsignal.ai.contracts import (
    AuditEvent,
    DangerHit,
    Evidence,
    Facet,
    Facets,
    LineRole,
    LineVerdict,
    LinkCertainty,
    LocationEvidence,
    OpenItem,
    SignalDraft,
    WindowInput,
    WindowLine,
)
from domsignal.ai.engine import decide_strength, disposition_for
from domsignal.ai.fusion import fuse_emergency
from domsignal.ai.matching import Token, tokenize
from domsignal.ai.normalize import NormalizedText, normalize
from domsignal.ai.rules import location as location_rules
from domsignal.ai.rules.danger import screen_normalized
from domsignal.ai.rules.lexicon import (
    Lexicon,
    classify_role,
    has_chatter_marker,
    is_displaced,
    load_lexicon,
)
from domsignal.ai.taxonomy import UNSPECIFIED, SubtypeMatch, Taxonomy, load_taxonomy
from domsignal.core.incidents import ReportCategory

#: Горячее окно: сколько реплик и сколько времени после прошедшей реплики.
HOT_WINDOW_LINES = 4
HOT_WINDOW_SECONDS = 300

_UNCLEAR = Facet(value="unclear")
_UNCLEAR_FACETS = Facets(current=_UNCLEAR, local=_UNCLEAR, observed=_UNCLEAR)
_ATTACHING_ROLES: frozenset[str] = frozenset({"me_too", "more_info", "objection"})


@dataclass(frozen=True)
class LineFacts:
    """Всё, что правила знают об одной реплике окна."""

    line: WindowLine
    normalized: NormalizedText
    tokens: tuple[Token, ...]
    subtypes: tuple[SubtypeMatch, ...]
    danger: tuple[DangerHit, ...]
    place: location_rules.PlaceTime
    role: LineRole
    gate: bool
    displaced: bool
    chatter_marker: bool

    @property
    def line_id(self) -> str:
        return self.line.line_id

    @property
    def active_danger(self) -> tuple[DangerHit, ...]:
        return tuple(hit for hit in self.danger if not hit.negated)


@dataclass
class _Draft:
    ref: str
    subtype: str
    product_category: ReportCategory
    object_label: str
    line_ids: list[str] = field(default_factory=list)
    entrance: Evidence | None = None
    floor: Evidence | None = None
    since: Evidence | None = None
    scope: LocationEvidence = LocationEvidence(value="unknown")
    danger: list[DangerHit] = field(default_factory=list)


@dataclass(frozen=True)
class RulesOutcome:
    """Результат правил: используется и сам по себе, и как основа для модели."""

    facts: tuple[LineFacts, ...]
    lines: tuple[LineVerdict, ...]
    signals: tuple[SignalDraft, ...]
    danger_hits: tuple[DangerHit, ...]
    audit_events: tuple[AuditEvent, ...]
    categories: tuple[ReportCategory, ...]

    @property
    def has_signals(self) -> bool:
        return bool(self.signals)


def analyze_line(
    line: WindowLine,
    taxonomy: Taxonomy | None = None,
    lexicon: Lexicon | None = None,
) -> LineFacts:
    """Разбор одной реплики правилами."""
    tax = taxonomy or load_taxonomy()
    lex = lexicon or load_lexicon()
    normalized = normalize(line.text)
    tokens = tokenize(normalized.text)
    subtypes = tuple(tax.match(tokens, lex.negation_tokens))
    danger = tuple(screen_normalized(normalized, tokens, line.line_id))
    place = location_rules.extract(normalized, tokens, line.line_id, lex)
    displaced = is_displaced(tokens, lex)
    active_danger = any(hit for hit in danger if not hit.negated and not hit.displaced)
    role = classify_role(
        tokens,
        has_subtype=bool(subtypes),
        active_danger=active_danger,
        displaced=displaced,
        has_place_or_time=place.has_any,
        ends_with_question=line.text.rstrip().endswith("?"),
        lexicon=lex,
    )
    gate = bool(
        subtypes
        or any(not hit.negated for hit in danger)
        or lex.break_markers.find_all(tokens)
        or lex.complaint_markers.find_all(tokens)
        or lex.absence_markers.find_all(tokens)
    )
    return LineFacts(
        line=line,
        normalized=normalized,
        tokens=tokens,
        subtypes=subtypes,
        danger=danger,
        place=place,
        role=role,
        gate=gate,
        displaced=displaced,
        chatter_marker=has_chatter_marker(tokens, lex),
    )


def _distinct_subtypes(facts: LineFacts, limit: int = 3) -> list[SubtypeMatch]:
    """Не более одного подтипа на категорию заявки, в порядке таксономии."""
    seen: set[ReportCategory] = set()
    chosen: list[SubtypeMatch] = []
    for match in facts.subtypes:
        category = match.subtype.product_category
        if category in seen:
            continue
        seen.add(category)
        chosen.append(match)
        if len(chosen) == limit:
            break
    return chosen


def _open_item_ref(
    subtype: str,
    category: ReportCategory,
    entrance: Evidence | None,
    open_items: Sequence[OpenItem],
) -> str | None:
    candidates = [
        item
        for item in open_items
        if (item.subtype == subtype if item.subtype else item.category == category)
    ]
    if len(candidates) != 1:
        return None
    item = candidates[0]
    if item.entrance and (entrance is None or item.entrance != entrance.value):
        # «Лифт не работает» при открытом элементе во 2 подъезде — это вопрос
        # «в каком подъезде?», а не совпадение: без подъезда не привязываем.
        return None
    return item.ref


def _object_label(match: SubtypeMatch, facts: LineFacts) -> str:
    anchor = match.object_match
    if anchor is not None:
        quote = facts.normalized.quote(anchor.start, anchor.end)
        if quote:
            return quote
    return match.subtype.label


def _merge_place(draft: _Draft, facts: LineFacts) -> None:
    place = facts.place
    if draft.entrance is None and place.entrance is not None:
        draft.entrance = place.entrance
    if draft.floor is None and place.floor is not None:
        draft.floor = place.floor
    if draft.since is None and place.since is not None:
        draft.since = place.since
    if draft.scope.value == "unknown" and place.scope.value != "unknown":
        draft.scope = place.scope


def _passed_lines(facts: Sequence[LineFacts]) -> dict[str, bool]:
    """Вариант C: гейт, ответ на прошедшую реплику и горячее окно."""
    passed: dict[str, bool] = {}
    anchor_index: int | None = None
    anchor_time = None
    for index, item in enumerate(facts):
        replied = item.line.reply_to is not None and passed.get(item.line.reply_to, False)
        direct = item.gate or replied
        if direct:
            passed[item.line_id] = True
            anchor_index, anchor_time = index, item.line.sent_at
            continue
        if anchor_index is not None and anchor_time is not None:
            close_enough = index - anchor_index <= HOT_WINDOW_LINES
            in_time = item.line.sent_at - anchor_time <= timedelta(seconds=HOT_WINDOW_SECONDS)
            if close_enough and in_time:
                passed[item.line_id] = True
                anchor_index, anchor_time = index, item.line.sent_at
                continue
        passed[item.line_id] = False
    return passed


def analyze_with_rules(
    window: WindowInput,
    taxonomy: Taxonomy | None = None,
    lexicon: Lexicon | None = None,
) -> RulesOutcome:
    """Полный разбор окна правилами, без модели."""
    tax = taxonomy or load_taxonomy()
    lex = lexicon or load_lexicon()
    all_facts = tuple(analyze_line(line, tax, lex) for line in window.lines)
    own = tuple(item for item in all_facts if not item.line.is_context)
    passed = _passed_lines(own)

    drafts: list[_Draft] = []
    by_subtype: dict[str, _Draft] = {}
    verdicts: list[LineVerdict] = []
    danger_hits: list[DangerHit] = []
    counter = 0

    for facts in own:
        danger_hits.extend(facts.danger)
        role = facts.role
        joined = passed.get(facts.line_id, False)
        certainty: LinkCertainty | None = None
        refs: list[str] = []

        if role in ("chatter", "discussion") and joined and drafts and not facts.chatter_marker:
            # Реплика прошла гейт или горячее окно: она относится к ветке,
            # даже если по эвристикам сама по себе выглядит болтовнёй.
            role = "more_info" if facts.place.has_any and not facts.subtypes else "me_too"
            certainty = "sure" if facts.gate else "unsure"

        if role == "new_problem" and joined:
            matches = _distinct_subtypes(facts)
            if not matches:
                unspecified = tax.get(UNSPECIFIED)
                candidates = [
                    (UNSPECIFIED, unspecified.product_category, unspecified.label)
                ]
            else:
                candidates = [
                    (
                        match.subtype.code,
                        match.subtype.product_category,
                        _object_label(match, facts),
                    )
                    for match in matches
                ]
            for code, category, label in candidates:
                draft = by_subtype.get(code)
                if draft is None:
                    counter += 1
                    ref = _open_item_ref(code, category, facts.place.entrance, window.open_items)
                    draft = _Draft(
                        ref=ref or f"new:{counter}",
                        subtype=code,
                        product_category=category,
                        object_label=label,
                        scope=LocationEvidence(value="unknown"),
                    )
                    drafts.append(draft)
                    by_subtype[code] = draft
                draft.line_ids.append(facts.line_id)
                draft.danger.extend(facts.danger)
                _merge_place(draft, facts)
                refs.append(draft.ref)
            certainty = certainty or "sure"
        elif role in _ATTACHING_ROLES and joined and drafts:
            draft = drafts[-1]
            draft.line_ids.append(facts.line_id)
            draft.danger.extend(facts.danger)
            _merge_place(draft, facts)
            refs.append(draft.ref)
            certainty = certainty or "sure"
        elif role == "new_problem" and not joined:
            role = "chatter"

        verdicts.append(
            LineVerdict(
                line_id=facts.line_id,
                role=role,
                signal_refs=tuple(refs),
                link_certainty=certainty if refs else None,
            )
        )

    signals: list[SignalDraft] = []
    audit_events: list[AuditEvent] = []
    for draft in drafts:
        emergency, events = fuse_emergency(draft.danger, signal_ref=draft.ref)
        audit_events.extend(events)
        strength, reason = decide_strength(emergency, _UNCLEAR_FACETS)
        signals.append(
            SignalDraft(
                ref=draft.ref,
                subtype=draft.subtype,
                product_category=draft.product_category,
                object_label=draft.object_label,
                entrance=draft.entrance,
                floor=draft.floor,
                since=draft.since,
                location_scope=draft.scope,
                facets=_UNCLEAR_FACETS,
                emergency=emergency,
                strength=strength,
                strength_reason=reason,
                disposition=disposition_for(strength),
                line_ids=tuple(draft.line_ids),
                source="rules",
            )
        )
    return RulesOutcome(
        facts=all_facts,
        lines=tuple(verdicts),
        signals=tuple(signals),
        danger_hits=tuple(danger_hits),
        audit_events=tuple(audit_events),
        categories=tuple(dict.fromkeys(signal.product_category for signal in signals)),
    )
