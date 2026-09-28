"""In-memory chat stream grouping. Decisions are preliminary, not product tickets."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

STOP = {"это", "тоже", "есть", "нет", "нас", "вам", "уже", "сейчас", "когда", "сегодня",
        "соседи", "добрый", "день", "всем", "очень", "только", "подъезд", "этаже"}
WORDS = re.compile(r"[а-яёa-z]{4,}", re.I)
BUILDING_SERVICES = {"no_hot_water", "heating_none", "power_outage"}
CONTEXT_CUE = re.compile(r"\b(тоже|также|снова|опять|появил[а-я]*|пошл[а-я]*|дали|"
                         r"заработал[а-я]*|исправил[а-я]*|у нас|у меня|до сих пор|"
                         r"всё ещё|все еще|так и нет)\b", re.I)
SERVICE_CUES = {
    "no_hot_water": re.compile(r"горяч[а-я]*\s+вод|вод[а-я]*\s+горяч|гвс", re.I),
    "heating_none": re.compile(r"отоплен|батаре|радиатор|тепл[а-я]*\s+в\s+квартир", re.I),
    "power_outage": re.compile(r"электричеств|электроэнерг|нет\s+света|свет\s+дали", re.I),
}


def _tokens(text: str) -> set[str]:
    return {word.lower().replace("ё", "е")[:5] for word in WORDS.findall(text)
            if word.lower() not in STOP}


def _object(text: str) -> str | None:
    low = text.lower()
    if "грузов" in low:
        return "freight_elevator"
    if "пассажир" in low:
        return "passenger_elevator"
    return None


def _time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def gap_hours(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 3600


@dataclass
class Case:
    case_id: str
    house_id: str
    fine_class: str
    entrance: int | None
    object_kind: str | None
    created_at: datetime
    last_at: datetime
    tokens: set[str] = field(default_factory=set)
    message_ids: set[str] = field(default_factory=set)
    status: str = "open"
    message_count: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "class": self.fine_class,
            "entrance": self.entrance, "status": self.status,
            "messages": self.message_count,
        }


class ChatTracker:
    def __init__(self, max_gap_hours: float = 24.0,
                 merge_policy: str = "conservative") -> None:
        if merge_policy not in {"conservative", "broad_6h", "broad_24h",
                                "service_context_6h"}:
            raise ValueError("unknown merge policy")
        self.max_gap_hours = max_gap_hours
        self.merge_policy = merge_policy
        self.cases: list[Case] = []
        self.next_id = 1

    def _referenced_case(self, reply_to: str | None, house: str, now: datetime) -> Case | None:
        if not reply_to:
            return None
        for case in reversed(self.cases):
            gap = (now - case.last_at).total_seconds() / 3600
            if (case.house_id == house and case.status == "open"
                    and 0 <= gap <= 6 and reply_to in case.message_ids):
                return case
        return None

    @staticmethod
    def _context_evidence(text: str, case: Case) -> bool:
        cue = SERVICE_CUES.get(case.fine_class)
        return bool((cue and cue.search(text)) or CONTEXT_CUE.search(text))

    def _context_case(self, text: str, reply_to: str | None, house: str,
                      now: datetime) -> Case | None:
        referenced = self._referenced_case(reply_to, house, now)
        if referenced and self._context_evidence(text, referenced):
            return referenced
        return None

    def _candidate(self, house: str, name: str, entrance: int | None,
                   object_kind: str | None, tokens: set[str], reply_to: str | None,
                   now: datetime, closing: bool) -> Case | None:
        best: tuple[float, Case] | None = None
        for case in self.cases:
            if case.status != "open" or case.house_id != house or case.fine_class != name:
                continue
            shared_service = (self.merge_policy == "service_context_6h"
                              and name in BUILDING_SERVICES and gap_hours(now, case.last_at) <= 6)
            if (entrance is not None and case.entrance is not None
                    and entrance != case.entrance and not shared_service):
                continue
            if object_kind and case.object_kind and object_kind != case.object_kind:
                continue
            gap = (now - case.last_at).total_seconds() / 3600
            if gap < 0 or gap > (72 if closing else self.max_gap_hours):
                continue
            linked = bool(reply_to and reply_to in case.message_ids)
            intersection = len(tokens & case.tokens)
            union = len(tokens | case.tokens)
            similarity = intersection / union if union else 0.0
            same_named_entrance = entrance is not None and entrance == case.entrance
            broad = ((self.merge_policy == "broad_6h" and gap <= 6)
                     or (self.merge_policy == "broad_24h" and gap <= 24))
            if not (linked or same_named_entrance or (gap <= 2 and similarity >= 0.34)
                    or broad or shared_service):
                continue
            rank = (3 if linked else 0) + (2 if same_named_entrance else 0) + similarity - gap / 100
            if best is None or rank > best[0]:
                best = (rank, case)
        return best[1] if best else None

    def consume(self, message: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
        message_id = str(message.get("id") or f"line-{len(self.cases)+1}-{self.next_id}")
        now = _time(message.get("ts"))
        house = str(message.get("house_id") or "single_house")
        text = str(message["text"])
        reply_to = message.get("reply_to")
        if self.merge_policy == "service_context_6h" and (
                not prediction["is_problem"] or prediction.get("utterance") == "offtopic"):
            context_case = self._context_case(text, reply_to, house, now)
            if context_case:
                context_case.last_at = now
                context_case.message_count += 1
                context_case.message_ids.add(message_id)
                return {"message_id": message_id, "action": "attached_context_preliminary",
                        "case_id": context_case.case_id, "open_cases": self.open_cases()}
        if not prediction["is_problem"] or not prediction["fine_class"]:
            action = "urgent_human_review" if prediction.get("urgent_human_review") else "ignored"
            return {"message_id": message_id, "action": action, "case_id": None,
                    "open_cases": self.open_cases()}
        name = prediction["fine_class"]
        utterance = prediction.get("utterance")
        if utterance == "planned_outage_info":
            return {"message_id": message_id, "action": "notice", "case_id": None,
                    "open_cases": self.open_cases()}
        entrance = prediction["slots"]["entrance"]
        tokens = _tokens(text)
        object_kind = _object(text)
        case = self._candidate(house, name, entrance, object_kind, tokens,
                               reply_to, now, utterance == "resolved_notice")
        if utterance == "resolved_notice":
            if case is not None:
                if self.merge_policy == "service_context_6h" and name in BUILDING_SERVICES:
                    case.last_at = now
                    case.message_count += 1
                    case.message_ids.add(message_id)
                    return {"message_id": message_id, "action": "resolution_pending_human",
                            "case_id": case.case_id, "open_cases": self.open_cases()}
                case.status = "closed_by_message_unverified"
                case.last_at = now
                case.message_count += 1
                case.message_ids.add(message_id)
                return {"message_id": message_id, "action": "closed_unverified",
                        "case_id": case.case_id, "open_cases": self.open_cases()}
            return {"message_id": message_id, "action": "unmatched_resolution",
                    "case_id": None, "open_cases": self.open_cases()}
        if case is not None:
            case.last_at = now
            case.message_count += 1
            case.message_ids.add(message_id)
            case.tokens |= tokens
            if (self.merge_policy == "service_context_6h" and name in BUILDING_SERVICES
                    and case.entrance is not None and entrance is not None
                    and case.entrance != entrance):
                case.entrance = None
            if case.entrance is None:
                if self.merge_policy != "service_context_6h" or name not in BUILDING_SERVICES:
                    case.entrance = entrance
            return {"message_id": message_id, "action": "attached",
                    "case_id": case.case_id, "open_cases": self.open_cases()}
        if utterance not in {"report", "status_inquiry"}:
            return {"message_id": message_id, "action": "unmatched_update",
                    "case_id": None, "open_cases": self.open_cases()}
        case = Case(case_id=f"case-{self.next_id}", house_id=house, fine_class=name,
                    entrance=entrance, object_kind=object_kind, created_at=now,
                    last_at=now, tokens=tokens, message_ids={message_id}, message_count=1)
        self.next_id += 1
        self.cases.append(case)
        return {"message_id": message_id, "action": "created_preliminary",
                "case_id": case.case_id, "open_cases": self.open_cases()}

    def open_cases(self) -> list[dict[str, Any]]:
        return [case.public() for case in self.cases if case.status == "open"]
