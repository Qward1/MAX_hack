"""In-memory chat stream grouping. Decisions are preliminary, not product tickets."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

STOP = {"это", "тоже", "есть", "нет", "нас", "вам", "уже", "сейчас", "когда", "сегодня",
        "соседи", "добрый", "день", "всем", "очень", "только", "подъезд", "этаже"}
WORDS = re.compile(r"[а-яёa-z]{4,}", re.I)


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
        if merge_policy not in {"conservative", "broad_6h", "broad_24h"}:
            raise ValueError("unknown merge policy")
        self.max_gap_hours = max_gap_hours
        self.merge_policy = merge_policy
        self.cases: list[Case] = []
        self.next_id = 1

    def _candidate(self, house: str, name: str, entrance: int | None,
                   object_kind: str | None, tokens: set[str], reply_to: str | None,
                   now: datetime, closing: bool) -> Case | None:
        best: tuple[float, Case] | None = None
        for case in self.cases:
            if case.status != "open" or case.house_id != house or case.fine_class != name:
                continue
            if entrance is not None and case.entrance is not None and entrance != case.entrance:
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
            if not (linked or same_named_entrance or (gap <= 2 and similarity >= 0.34) or broad):
                continue
            rank = (3 if linked else 0) + (2 if same_named_entrance else 0) + similarity - gap / 100
            if best is None or rank > best[0]:
                best = (rank, case)
        return best[1] if best else None

    def consume(self, message: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
        message_id = str(message.get("id") or f"line-{len(self.cases)+1}-{self.next_id}")
        now = _time(message.get("ts"))
        if not prediction["is_problem"] or not prediction["fine_class"]:
            action = "urgent_human_review" if prediction.get("urgent_human_review") else "ignored"
            return {"message_id": message_id, "action": action, "case_id": None,
                    "open_cases": self.open_cases()}
        name = prediction["fine_class"]
        utterance = prediction.get("utterance")
        if utterance == "planned_outage_info":
            return {"message_id": message_id, "action": "notice", "case_id": None,
                    "open_cases": self.open_cases()}
        house = str(message.get("house_id") or "single_house")
        entrance = prediction["slots"]["entrance"]
        tokens = _tokens(str(message["text"]))
        object_kind = _object(str(message["text"]))
        case = self._candidate(house, name, entrance, object_kind, tokens,
                               message.get("reply_to"), now, utterance == "resolved_notice")
        if utterance == "resolved_notice":
            if case is not None:
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
            if case.entrance is None:
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
