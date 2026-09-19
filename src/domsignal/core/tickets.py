"""A-16 lifecycle; no routing model, normative calculator or delivery transport."""

from enum import StrEnum


class TicketStatus(StrEnum):
    NEW = "new"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    VERIFICATION_PENDING = "verification_pending"
    NEEDS_CLARIFICATION = "needs_clarification"
    WAITING_EXTERNAL = "waiting_external"
    CLOSED = "closed"
    CANCELLED = "cancelled"


ACTIVE = frozenset(s.value for s in TicketStatus) - {"closed", "cancelled"}
WORKING = frozenset({"new", "accepted", "in_progress"})
WAITING = frozenset({"needs_clarification", "waiting_external"})


class TicketAction(StrEnum):
    ASSIGN = "assign"
    ACCEPT = "accept"
    START = "start"
    CLARIFY = "clarify"
    WAIT_EXTERNAL = "wait-external"
    RESUME = "resume"
    WORK_REPORT = "work-attempts"
    CANCEL = "cancel"
    DEADLINE = "deadlines"


class TicketEventKind(StrEnum):
    CREATED = "created"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    STARTED = "started"
    CLARIFICATION_REQUESTED = "clarification_requested"
    EXTERNAL_WAIT_RECORDED = "external_wait_recorded"
    RESUMED = "resumed"
    WORK_REPORTED = "work_reported"
    RESULT_CONFIRMED = "result_confirmed"
    RESULT_OBJECTED = "result_objected"
    OBSERVATION_RECORDED = "observation_recorded"
    CANCELLED = "cancelled"
    DEADLINE_RECORDED = "deadline_recorded"


def transition_allowed(action: TicketAction, status: str, *, accepted: bool) -> bool:
    match action:
        case TicketAction.ASSIGN | TicketAction.CANCEL | TicketAction.DEADLINE:
            return status in ACTIVE
        case TicketAction.ACCEPT:
            return status == "new" or (status in {"accepted", "in_progress"} and not accepted)
        case TicketAction.START:
            return status == "accepted"
        case TicketAction.CLARIFY | TicketAction.WAIT_EXTERNAL:
            return status in WORKING
        case TicketAction.RESUME:
            return status in WAITING
        case TicketAction.WORK_REPORT:
            return status == "in_progress"


def observation_status(
    status: str, *, resolved: bool, unresolved: bool, rework_required: bool
) -> str:
    if unresolved:
        return "in_progress"
    if resolved and not rework_required and status == "verification_pending":
        return "closed"
    return status
