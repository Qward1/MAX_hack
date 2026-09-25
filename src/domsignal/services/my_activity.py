"""«Мои обращения» (B-05, D3): всё своё одним списком.

* карточки внешнего маршрута — исходы, по которым заявки УК нет (обращение
  житель отправляет сам);
* черновики обращений с отметкой «Я отправил» — это утверждение жителя
  (`user_reported`), а не регистрация во внешней системе;
* свои сообщения о проблемах и заявки с текущим статусом;
* проблемы, где житель нажал «Меня тоже касается» или «Это та же проблема».

Показываются только дома, к которым у жителя сейчас есть доступ. Порядок —
по времени, пагинация — одним запросом по объединению.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.ai import load_taxonomy
from domsignal.contracts.common import PageMeta
from domsignal.contracts.community import ActivityItem, ActivityList
from domsignal.db.models import (
    AppealDraft,
    House,
    Incident,
    Report,
    RouteOutcome,
    Signal,
    Ticket,
    WorkAttempt,
)
from domsignal.services.membership import MembershipService
from domsignal.services.signal_texts import subtype_title

#: Подписи состояния заявки для жителя (без внутренних причин).
TICKET_LABELS = {
    "new": "Заявка у УК: ждёт принятия в работу",
    "accepted": "УК приняла в работу",
    "in_progress": "В работе",
    "verification_pending": "Исполнитель сообщил о выполнении — проверьте результат",
    "needs_clarification": "Уточняются подробности",
    "waiting_external": "Ожидается внешняя организация",
    "closed": "Закрыта",
    "cancelled": "Отменена",
}
RETURNED_LABEL = "Возвращена в работу"
INCIDENT_LABELS = {
    "open": "Открыта, заявки УК нет",
    "reported": "Вы отметили, что отправили обращение",
    "closed": "Закрыта",
}
EXTERNAL_LABEL = "Обращение отправляете вы сами — карточка подскажет куда"
DRAFT_LABEL = "Черновик: ещё не отмечен как отправленный"
FILED_LABEL = "Вы отметили: «Я отправил»"
FOLLOWUP_LABELS = {
    "resolved": "Вы ответили: решено",
    "answered_unresolved": "Вы ответили: ответ пришёл, не решено",
    "no_answer": "Вы ответили: ответа нет",
}


def _subtype(code: str) -> str:
    taxonomy = load_taxonomy()
    try:
        return subtype_title(taxonomy.get(code).label)
    except KeyError:
        return "Проблема дома"


class MyActivityService:
    def __init__(self) -> None:
        self.memberships = MembershipService()

    async def list(
        self, session: AsyncSession, *, actor_id: UUID, limit: int, offset: int
    ) -> ActivityList:
        houses = [
            house.id
            for house, _ in await self.memberships.contexts_with(
                session, user_id=actor_id, permission="incident.read"
            )
        ]
        if not houses:
            return ActivityList(items=[], page=PageMeta(limit=limit, offset=offset, total=0))
        from_signal = select(Signal.id).where(Signal.report_id == Report.id).exists()
        cards = select(
            literal("route_card").label("kind"),
            RouteOutcome.id.label("id"),
            RouteOutcome.created_at.label("occurred_at"),
        ).where(
            RouteOutcome.author_id == actor_id,
            RouteOutcome.decision == "external",
            RouteOutcome.house_id.in_(houses),
        )
        drafts = select(
            literal("appeal_draft").label("kind"),
            AppealDraft.id.label("id"),
            AppealDraft.created_at.label("occurred_at"),
        ).where(AppealDraft.author_id == actor_id, AppealDraft.house_id.in_(houses))
        own = (
            select(
                literal("report").label("kind"),
                Report.incident_id.label("id"),
                func.min(Report.created_at).label("occurred_at"),
            )
            .where(
                Report.author_id == actor_id,
                Report.house_id.in_(houses),
                Report.joined.is_(False),
                ~from_signal,
            )
            .group_by(Report.incident_id)
        )
        joined = (
            select(
                literal("joined").label("kind"),
                Report.incident_id.label("id"),
                func.min(Report.created_at).label("occurred_at"),
            )
            .where(
                Report.author_id == actor_id,
                Report.house_id.in_(houses),
                Report.joined.is_(True),
            )
            .group_by(Report.incident_id)
        )
        union = union_all(cards, drafts, own, joined).subquery()
        total = await session.scalar(select(func.count()).select_from(union)) or 0
        rows = (
            await session.execute(
                select(union.c.kind, union.c.id, union.c.occurred_at)
                .order_by(union.c.occurred_at.desc(), union.c.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items = [await self._item(session, kind, item_id, at) for kind, item_id, at in rows]
        return ActivityList(
            items=[item for item in items if item is not None],
            page=PageMeta(limit=limit, offset=offset, total=total),
        )

    async def _address(self, session: AsyncSession, house_id: UUID) -> str:
        house = await session.get(House, house_id)
        return house.address if house else ""

    async def _item(
        self, session: AsyncSession, kind: str, item_id: UUID, at: datetime
    ) -> ActivityItem | None:
        if kind == "route_card":
            outcome = await session.get(RouteOutcome, item_id)
            if outcome is None:
                return None
            draft = await session.scalar(
                select(AppealDraft.id).where(AppealDraft.route_outcome_id == outcome.id)
            )
            return ActivityItem(
                kind="route_card",
                id=outcome.id,
                house_id=outcome.house_id,
                house_address=await self._address(session, outcome.house_id),
                title=_subtype(outcome.subtype),
                status_label=EXTERNAL_LABEL,
                occurred_at=at,
                route_outcome_id=outcome.id,
                appeal_draft_id=draft,
            )
        if kind == "appeal_draft":
            appeal = await session.get(AppealDraft, item_id)
            if appeal is None:
                return None
            outcome = await session.get(RouteOutcome, appeal.route_outcome_id)
            label = FOLLOWUP_LABELS.get(appeal.followup_answer or "") or (
                FILED_LABEL if appeal.filed_at else DRAFT_LABEL
            )
            return ActivityItem(
                kind="appeal_draft",
                id=appeal.id,
                house_id=appeal.house_id,
                house_address=await self._address(session, appeal.house_id),
                title="Черновик обращения · "
                + (_subtype(outcome.subtype) if outcome else "Проблема"),
                status_label=label,
                occurred_at=at,
                route_outcome_id=appeal.route_outcome_id,
                appeal_draft_id=appeal.id,
                filed_at=appeal.filed_at,
            )
        incident = await session.get(Incident, item_id)
        if incident is None:
            return None
        ticket = await session.scalar(
            select(Ticket)
            .where(Ticket.incident_id == incident.id)
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        label, number = self._status(incident, ticket, await self._returned(session, ticket))
        return ActivityItem(
            kind="joined" if kind == "joined" else "report",
            id=incident.id,
            house_id=incident.house_id,
            house_address=await self._address(session, incident.house_id),
            title=incident.title or "Проблема дома",
            status_label=label,
            occurred_at=at,
            incident_id=incident.id,
            ticket_number=number,
        )

    @staticmethod
    async def _returned(session: AsyncSession, ticket: Ticket | None) -> bool:
        if ticket is None or ticket.latest_attempt_id is None:
            return False
        attempt = await session.get(WorkAttempt, ticket.latest_attempt_id)
        return bool(attempt and attempt.rework_required)

    @staticmethod
    def _status(
        incident: Incident, ticket: Ticket | None, returned: bool
    ) -> tuple[str, str | None]:
        if ticket is None:
            return INCIDENT_LABELS.get(incident.status, "Состояние неизвестно"), None
        label = (
            RETURNED_LABEL
            if returned and ticket.status == "in_progress"
            else TICKET_LABELS.get(ticket.status, "Состояние обновлено")
        )
        return label, f"T-{ticket.number}"


__all__ = ["MyActivityService"]
