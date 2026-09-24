"""Семантическая проверка ответа модели против самого окна.

Ответ модели — предложение, а не разрешение. Здесь проверяется, что каждая
ссылка на реплику существует, каждая цитата действительно является подстрокой
именно той реплики, на которую ссылается, и что значения принадлежат
перечислениям контракта. Не прошедшее проверку поле отбрасывается, а не
«чинится».
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from domsignal.ai.contracts import (
    DANGER_KINDS,
    FACET_VALUES,
    LOCATION_SCOPES,
    REFUTATION_REASONS,
    ROLES,
    AuditEvent,
    DangerHit,
    DangerKind,
    Evidence,
    Facet,
    Facets,
    FacetValue,
    LineRole,
    LineVerdict,
    LocationEvidence,
    LocationScope,
    RefutationReason,
    SemanticDanger,
    SemanticEvidence,
    SignalDraft,
    TextBlock,
    WindowInput,
)
from domsignal.ai.engine import (
    decide_strength,
    disposition_for,
    may_join_open_item,
    rename_refs,
)
from domsignal.ai.facts import check_no_new_facts
from domsignal.ai.fallback import RulesOutcome
from domsignal.ai.fusion import Refutation, fuse_emergency
from domsignal.ai.model_output import (
    ModelFacet,
    ModelSignal,
    ModelText,
    ModelValue,
    WindowModelOutput,
)
from domsignal.ai.normalize import contains_quote
from domsignal.ai.providers.base import WindowMapping
from domsignal.ai.rules.location import normalize_place_number
from domsignal.ai.taxonomy import UNSPECIFIED, Taxonomy

_UNCLEAR = Facet(value="unclear")


@dataclass
class _Collector:
    dropped: int = 0
    events: list[AuditEvent] = field(default_factory=list)

    def drop(self, signal_ref: str | None, details: str) -> None:
        self.dropped += 1
        self.events.append(
            AuditEvent(kind="field_dropped", signal_ref=signal_ref, details=details)
        )


@dataclass(frozen=True)
class ValidatedWindow:
    lines: tuple[LineVerdict, ...]
    signals: tuple[SignalDraft, ...]
    semantic_danger: tuple[SemanticDanger, ...]
    audit_events: tuple[AuditEvent, ...]
    dropped_fields: int


#: Причина отказа для цитаты из реплики контекста (`is_context`).
CONTEXT_LINE = "реплика контекста, доказательства берутся только из реплик окна"

#: Поля, значение которых — номер подъезда или этажа.
_NUMBERED_FIELDS = frozenset({"entrance", "floor"})
#: Поля места и времени сигнала — только из правил (P6b, частное ограничение
#: §6.3: выдуманных цитат модели 10,1 % > 2 %, OWNER-DECISION-2026-09-24).
_PLACE_FIELDS = ("entrance", "floor", "since")


class _Context:
    def __init__(self, window: WindowInput, mapping: WindowMapping) -> None:
        self.texts = {line.line_id: line.text for line in window.lines}
        self.own = {line.line_id for line in window.lines if not line.is_context}
        self.mapping = mapping

    def line_id(self, msg: str | None) -> str | None:
        if not msg:
            return None
        line_id = self.mapping.line_id(msg)
        return line_id if line_id in self.texts else None

    def own_line(self, msg: str | None) -> tuple[str | None, str]:
        """Реплика окна по номеру `m…` или причина, по которой её нет.

        Реплики контекста — фон прошлого разговора: место, время, территория и
        доказательства опасности из них не берутся (дефект P7a: подъезд из
        реплики прошлого разговора).
        """
        line_id = self.line_id(msg)
        if line_id is None:
            return None, f"реплика {msg} не существует"
        if line_id not in self.own:
            return None, f"{msg} — {CONTEXT_LINE}"
        return line_id, ""

    def quote_valid(self, line_id: str, quote: str) -> bool:
        return contains_quote(self.texts.get(line_id, ""), quote)


def _evidence(
    context: _Context, raw: ModelValue | None, collector: _Collector, ref: str, name: str
) -> Evidence | None:
    if raw is None:
        return None
    line_id, reason = context.own_line(raw.msg)
    if line_id is None:
        collector.drop(ref, f"{name}: {reason}")
        return None
    if not context.quote_valid(line_id, raw.quote):
        collector.drop(ref, f"{name}: цитата не найдена в {raw.msg}")
        return None
    value = normalize_place_number(raw.value) if name in _NUMBERED_FIELDS else raw.value
    return Evidence(value=value, quote=raw.quote, line_id=line_id)


def _facet(context: _Context, raw: ModelFacet, collector: _Collector, ref: str, name: str) -> Facet:
    value = raw.v if raw.v in FACET_VALUES else None
    if value is None:
        collector.drop(ref, f"facets.{name}: неизвестное значение {raw.v!r}")
        return _UNCLEAR
    line_id, _reason = context.own_line(raw.msg)
    valid = (
        bool(raw.quote)
        and line_id is not None
        and context.quote_valid(line_id, raw.quote or "")
    )
    if value == "no" and not valid:
        collector.drop(ref, f"facets.{name}: «no» без валидной цитаты")
        return _UNCLEAR
    if not valid:
        return Facet(value=_as_facet(value))
    return Facet(value=_as_facet(value), quote=raw.quote, line_id=line_id)


def _as_facet(value: str) -> FacetValue:
    return "yes" if value == "yes" else "no" if value == "no" else "unclear"


def _scope(
    context: _Context, raw: ModelSignal, collector: _Collector, ref: str
) -> LocationEvidence:
    value = raw.location_scope.value
    if value not in LOCATION_SCOPES:
        collector.drop(ref, f"location_scope: неизвестное значение {value!r}")
        return LocationEvidence(value="unknown")
    if value == "unknown":
        return LocationEvidence(value="unknown")
    line_id, reason = context.own_line(raw.location_scope.msg)
    quote = raw.location_scope.quote or ""
    if line_id is None:
        collector.drop(ref, f"location_scope: {reason}")
        return LocationEvidence(value="unknown")
    if not context.quote_valid(line_id, quote):
        collector.drop(ref, "location_scope: без валидной цитаты")
        return LocationEvidence(value="unknown")
    scope: LocationScope = value
    return LocationEvidence(value=scope, quote=quote, line_id=line_id)


def _semantic(
    context: _Context, raw: ModelSignal, collector: _Collector, ref: str
) -> list[SemanticDanger]:
    result: list[SemanticDanger] = []
    for danger in raw.danger:
        if danger.kind not in DANGER_KINDS:
            collector.drop(ref, f"danger: неизвестный вид {danger.kind!r}")
            continue
        evidence: list[SemanticEvidence] = []
        from_context = False
        for item in danger.evidence:
            line_id, reason = context.own_line(item.msg)
            if line_id is None:
                from_context = from_context or context.line_id(item.msg) is not None
                collector.drop(ref, f"danger: {reason}")
                continue
            evidence.append(
                SemanticEvidence(
                    line_id=line_id,
                    quote=item.quote,
                    quote_valid=context.quote_valid(line_id, item.quote),
                )
            )
        if from_context and not evidence:
            # Опасность, доказанная только прошлым разговором, к этому окну не
            # относится: её уже разбирало предыдущее окно.
            collector.drop(ref, f"danger: {danger.kind} без реплик окна в доказательствах")
            continue
        kind: DangerKind = danger.kind
        result.append(
            SemanticDanger(kind=kind, evidence=tuple(evidence), contextual=danger.contextual)
        )
    return result


def _refutation(
    context: _Context, raw: ModelSignal, collector: _Collector, ref: str
) -> Refutation | None:
    refutation = raw.danger_refutation
    if refutation is None:
        return None
    if refutation.reason not in REFUTATION_REASONS:
        collector.drop(ref, f"danger_refutation: неизвестная причина {refutation.reason!r}")
        return None
    # Опровержение из реплики контекста не может понизить опасность окна.
    line_id, _reason = context.own_line(refutation.msg)
    valid = line_id is not None and context.quote_valid(line_id, refutation.quote)
    reason: RefutationReason = refutation.reason
    return Refutation(
        reason=reason,
        quote=refutation.quote,
        line_id=line_id or refutation.msg,
        quote_valid=valid,
    )


def _text_block(
    context: _Context,
    raw: ModelText | None,
    collector: _Collector,
    ref: str,
    name: str,
    default_lines: Sequence[str],
) -> TextBlock | None:
    if raw is None or not raw.text.strip():
        return None
    # Источники текста — только реплики окна: иначе проверка `no_new_facts`
    # пропустила бы факт из прошлого разговора (номер подъезда, срок).
    sources = [line_id for line_id in (context.own_line(msg)[0] for msg in raw.sources) if line_id]
    if not sources:
        sources = list(default_lines)
    texts = [context.texts[line_id] for line_id in sources if line_id in context.texts]
    verdict = check_no_new_facts(raw.text, texts)
    if not verdict.ok:
        collector.events.append(
            AuditEvent(
                kind="no_new_facts_violation",
                signal_ref=ref,
                details=f"{name}: "
                + ", ".join(f"{item.kind}={item.value}" for item in verdict.violations[:5]),
            )
        )
        return None
    return TextBlock(text=raw.text.strip(), source_line_ids=tuple(sources))


def _role(raw: str, fallback: LineRole, collector: _Collector, line_id: str) -> LineRole:
    if raw in ROLES:
        return raw
    collector.drop(None, f"{line_id}: неизвестная роль {raw!r}")
    return fallback


def validate_output(
    window: WindowInput,
    parsed: WindowModelOutput,
    mapping: WindowMapping,
    rules: RulesOutcome,
    taxonomy: Taxonomy,
) -> ValidatedWindow:
    """Свести проверенный ответ модели и результат правил в один результат."""
    context = _Context(window, mapping)
    collector = _Collector()
    rules_roles = {verdict.line_id: verdict.role for verdict in rules.lines}
    hits_by_line: dict[str, list[DangerHit]] = {}
    for hit in rules.danger_hits:
        hits_by_line.setdefault(hit.line_id, []).append(hit)

    ref_map: dict[str, str] = {}
    drafts: list[tuple[str, ModelSignal]] = []
    counter = 0
    for raw in parsed.signals:
        counter += 1
        if raw.ref.startswith("open:"):
            resolved = mapping.item_ref(raw.ref)
            if resolved is None:
                collector.drop(raw.ref, "ref: открытый элемент не существует")
                resolved = f"new:{counter}"
        else:
            resolved = f"new:{counter}"
        ref_map[raw.ref] = resolved
        drafts.append((resolved, raw))

    lines_by_ref: dict[str, list[str]] = {ref: [] for ref, _ in drafts}
    verdicts: list[LineVerdict] = []
    seen_lines: set[str] = set()
    for line in parsed.messages:
        line_id = context.line_id(line.id)
        if line_id is None or line_id not in context.own:
            collector.drop(None, f"messages: реплика {line.id} не существует в окне")
            continue
        if line_id in seen_lines:
            continue
        seen_lines.add(line_id)
        refs: list[str] = []
        for raw_ref in line.signals:
            resolved = ref_map.get(raw_ref)
            if resolved is None:
                collector.drop(None, f"{line.id}: ссылка на сигнал {raw_ref} не существует")
                continue
            refs.append(resolved)
            lines_by_ref[resolved].append(line_id)
        verdicts.append(
            LineVerdict(
                line_id=line_id,
                role=_role(line.role, rules_roles.get(line_id, "chatter"), collector, line.id),
                signal_refs=tuple(dict.fromkeys(refs)),
                link_certainty=line.link_certainty if refs else None,
            )
        )
    for window_line in window.lines:
        if window_line.is_context or window_line.line_id in seen_lines:
            continue
        collector.events.append(
            AuditEvent(
                kind="model_missing_line",
                details=f"{window_line.line_id}: роль взята из правил",
            )
        )
        verdicts.append(
            LineVerdict(
                line_id=window_line.line_id,
                role=rules_roles.get(window_line.line_id, "chatter"),
            )
        )
    order = {line.line_id: index for index, line in enumerate(window.lines)}
    verdicts.sort(key=lambda verdict: order.get(verdict.line_id, 0))

    covered = {line_id for ids in lines_by_ref.values() for line_id in ids}
    orphan_hits = [
        hit
        for hit in rules.danger_hits
        if not hit.negated and hit.line_id not in covered and hit.line_id in context.own
    ]

    open_items = {item.ref: item for item in window.open_items}
    renamed: dict[str, str] = {}
    signals: list[SignalDraft] = []
    semantic_all: list[SemanticDanger] = []
    for index, (ref, raw) in enumerate(drafts):
        line_ids = lines_by_ref[ref] or [
            line.line_id for line in window.lines if not line.is_context
        ][:1]
        code = raw.subtype if taxonomy.is_known(raw.subtype) else UNSPECIFIED
        if code != raw.subtype:
            collector.drop(ref, f"subtype: неизвестный код {raw.subtype!r}")
        hits = [hit for line_id in line_ids for hit in hits_by_line.get(line_id, [])]
        if index == 0:
            hits.extend(orphan_hits)
        semantic = _semantic(context, raw, collector, ref)
        semantic_all.extend(semantic)
        emergency, events = fuse_emergency(
            hits, semantic, _refutation(context, raw, collector, ref), signal_ref=ref
        )
        collector.events.extend(events)
        item = open_items.get(ref)
        if item is not None and not may_join_open_item(emergency, item):
            new_ref = f"new:{len(drafts) + len(renamed) + 1}"
            collector.drop(
                new_ref,
                f"ref: {raw.ref} — у открытого элемента нет опасности "
                f"{'/'.join(emergency.kinds)}, это новый сигнал",
            )
            renamed[ref] = new_ref
            ref = new_ref
        facets = Facets(
            current=_facet(context, raw.facets.current, collector, ref, "current"),
            local=_facet(context, raw.facets.local, collector, ref, "local"),
            observed=_facet(context, raw.facets.observed, collector, ref, "observed"),
        )
        strength, reason = decide_strength(emergency, facets)
        # Подъезд, этаж и «с какого времени» — только из правил по репликам
        # сигнала; значения модели не используются (P6b).
        place = {name: _rules_place(rules, line_ids, name) for name in _PLACE_FIELDS}
        from_rules = any(value is not None for value in place.values())
        signals.append(
            SignalDraft(
                ref=ref,
                subtype=code,
                product_category=taxonomy.product_category(code),
                object_label=raw.object.strip() or taxonomy.get(code).label,
                entrance=place["entrance"],
                floor=place["floor"],
                since=place["since"],
                location_scope=_rules_scope(rules, line_ids)
                or _scope(context, raw, collector, ref),
                facets=facets,
                emergency=emergency,
                strength=strength,
                strength_reason=reason,
                disposition=disposition_for(strength),
                line_ids=tuple(dict.fromkeys(line_ids)),
                source="rules+model" if hits else "model",
                flags=_flags(taxonomy, code, rules) + (("place_from_rules",) if from_rules else ()),
                clean_description=_text_block(
                    context, raw.clean_description, collector, ref, "clean_description", line_ids
                ),
                summary=_text_block(context, raw.summary, collector, ref, "summary", line_ids),
            )
        )

    if not signals and orphan_hits:
        signals.extend(_signals_from_rules(rules, orphan_hits))

    return ValidatedWindow(
        lines=rename_refs(verdicts, renamed),
        signals=tuple(signals),
        semantic_danger=tuple(semantic_all),
        audit_events=tuple(collector.events),
        dropped_fields=collector.dropped,
    )


def _rules_place(
    rules: RulesOutcome, line_ids: Sequence[str], name: str
) -> Evidence | None:
    """Подъезд, этаж или «с какого времени» из правил — по репликам сигнала.

    Единственный источник этих полей в режиме модели (P6b): у модели при
    минимальных рассуждениях 10,1 % цитат выдуманы (P6, holdout). Правила дают
    значение с дословной цитатой по построению, номера — цифрами; берётся
    первая по времени реплика самого сигнала, реплики контекста и чужих
    сигналов не участвуют.
    """
    wanted = set(line_ids)
    for facts in rules.facts:
        if facts.line_id in wanted and not facts.line.is_context:
            value: Evidence | None = getattr(facts.place, name)
            if value is not None:
                return value
    return None


def _rules_scope(rules: RulesOutcome, line_ids: Sequence[str]) -> LocationEvidence | None:
    """Территория правил с цитатой по репликам сигнала, если она определена.

    У правил `location_scope` точнее, чем у модели при минимальных
    рассуждениях (P6, holdout: 0,857 против 0,605): словарь «у остановки»,
    «во дворе» даёт значение с дословной цитатой. Иначе — значение модели.
    """
    wanted = set(line_ids)
    for facts in rules.facts:
        if facts.line_id in wanted and not facts.line.is_context:
            scope = facts.place.scope
            if scope.value != "unknown" and scope.quote:
                return scope
    return None


def _flags(taxonomy: Taxonomy, code: str, rules: RulesOutcome) -> tuple[str, ...]:
    """Согласие или расхождение подтипа правил и модели."""
    if len(rules.categories) != 1:
        return ()
    category = taxonomy.product_category(code)
    return ("rules_agree",) if rules.categories[0] == category else ("rules_disagree",)


def _signals_from_rules(
    rules: RulesOutcome, orphan_hits: Sequence[DangerHit]
) -> list[SignalDraft]:
    """Опасность правил не теряется, даже если модель не вернула сигналов."""
    lines = {hit.line_id for hit in orphan_hits}
    kept = [signal for signal in rules.signals if lines & set(signal.line_ids)]
    return kept or list(rules.signals)
