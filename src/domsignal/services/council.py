"""Совет дома и предложения жителей (D4, домовое сообщество).

* **Совет дома.** Администратор УК отмечает жителя дома (с действующим
  основанием жителя — участник чата или открытый доступ) членом совета и
  снимает отметку; оба действия — события аудита с основанием.
* **Права совета — только в своём доме.** Объявления и опросы совета идут тем
  же механизмом D3 (`Broadcast.origin = 'council'`): те же настройки чата, что
  у сообщений УК, тихие часы, доставка и аудит; подпись «Сообщение от совета
  дома». Канала два: чат дома и лента «Объявления».
* **«Предложить вопрос».** Житель предлагает тему; совет и УК видят список и
  одним действием превращают предложение в опрос: совет — сразу публикует,
  УК — получает черновик опроса в кабинете. Автор видит статус своего.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.community import (
    BroadcastAudience,
    BroadcastConfirm,
    BroadcastCreate,
    BroadcastView,
    CouncilAdminView,
    CouncilAnnouncementCreate,
    CouncilMemberChange,
    CouncilMemberRevoke,
    CouncilMemberView,
    CouncilPollCreate,
    CouncilPublished,
    CouncilResident,
    CouncilView,
    PollDraft,
    ProposalCreate,
    ProposalView,
)
from domsignal.db.models import HouseCouncilMember, HouseProposal, Poll, User
from domsignal.db.repositories.access import AccessRepository
from domsignal.db.repositories.reliability import ReliabilityRepository, stable_hash
from domsignal.services.broadcasts import BroadcastConflict, BroadcastService
from domsignal.services.errors import (
    AccessDenied,
    FieldValidationError,
    IdempotencyConflict,
    ResourceNotFound,
)
from domsignal.services.membership import MembershipService
from domsignal.services.onboarding import audit, require_company

#: Сколько нерассмотренных предложений житель может держать в одном доме.
MAX_OPEN_PROPOSALS = 3
#: Варианты и срок опроса, в который УК превращает предложение (правятся в черновике).
PROPOSAL_POLL_OPTIONS = ("За", "Против", "Нужно обсудить")
PROPOSAL_POLL_DAYS = 3
TOO_MANY_PROPOSALS = (
    f"Можно предложить не больше {MAX_OPEN_PROPOSALS} тем, пока их не рассмотрели совет "
    "дома или управляющая компания."
)
NOT_A_RESIDENT = "В совет дома можно отметить только жителя этого дома."


def _proposal(row: HouseProposal, *, user_id: UUID | None, poll_id: UUID | None) -> ProposalView:
    return ProposalView(
        id=row.id,
        house_id=row.house_id,
        text=row.text,
        status=row.status,
        created_at=row.created_at,
        mine=row.author_id == user_id,
        poll_id=poll_id,
    )


class CouncilService:
    def __init__(self, broadcasts: BroadcastService) -> None:
        self.broadcasts = broadcasts
        self.memberships = MembershipService()

    # ================================================================== житель

    async def _resident(self, session: AsyncSession, user_id: UUID, house_id: UUID) -> None:
        context = await self.memberships.require_house(
            session, user_id=user_id, house_id=house_id
        )
        self.memberships.require_permission(context, "report.create")

    async def is_member(self, session: AsyncSession, user_id: UUID, house_id: UUID) -> bool:
        found = await session.scalar(
            select(HouseCouncilMember.id).where(
                HouseCouncilMember.house_id == house_id,
                HouseCouncilMember.user_id == user_id,
                HouseCouncilMember.status == "active",
            )
        )
        return found is not None

    async def _proposals(
        self,
        session: AsyncSession,
        house_id: UUID,
        *,
        user_id: UUID | None,
        only_author: bool,
    ) -> list[ProposalView]:
        query = select(HouseProposal).where(HouseProposal.house_id == house_id)
        if only_author:
            query = query.where(HouseProposal.author_id == user_id)
        rows = list(
            await session.scalars(query.order_by(HouseProposal.created_at.desc()).limit(100))
        )
        polls = {
            poll.broadcast_id: poll.id
            for poll in await session.scalars(
                select(Poll).where(
                    Poll.broadcast_id.in_([row.broadcast_id for row in rows if row.broadcast_id])
                )
            )
        }
        return [
            _proposal(
                row,
                user_id=user_id,
                poll_id=polls.get(row.broadcast_id) if row.broadcast_id else None,
            )
            for row in rows
        ]

    async def resident_view(
        self, session: AsyncSession, *, user_id: UUID, house_id: UUID
    ) -> CouncilView:
        await self._resident(session, user_id, house_id)
        member = await self.is_member(session, user_id, house_id)
        return CouncilView(
            house_id=house_id,
            is_member=member,
            proposals=await self._proposals(
                session, house_id, user_id=user_id, only_author=not member
            ),
        )

    async def propose(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        house_id: UUID,
        payload: ProposalCreate,
        idempotency_key: str,
    ) -> ProposalView:
        await self._resident(session, user_id, house_id)
        reliability = ReliabilityRepository(session)
        action = f"proposal.create:{house_id}"
        digest = stable_hash(payload.model_dump(mode="json"))
        await reliability.lock_idempotency(actor_id=user_id, action=action, key=idempotency_key)
        receipt = await reliability.idempotency_record(
            actor_id=user_id, action=action, key=idempotency_key
        )
        if receipt is not None:
            if receipt.request_hash != digest:
                raise IdempotencyConflict("Idempotency-Key was already used with a different body")
            existing = await session.get(HouseProposal, UUID(receipt.response_body["id"]))
            assert existing is not None
            return _proposal(existing, user_id=user_id, poll_id=None)
        open_count = await session.scalar(
            select(func.count())
            .select_from(HouseProposal)
            .where(
                HouseProposal.house_id == house_id,
                HouseProposal.author_id == user_id,
                HouseProposal.status == "new",
            )
        )
        if (open_count or 0) >= MAX_OPEN_PROPOSALS:
            raise FieldValidationError(TOO_MANY_PROPOSALS, field="text", code="limit")
        row = HouseProposal(id=uuid4(), house_id=house_id, author_id=user_id, text=payload.text)
        session.add(row)
        await session.flush()
        await session.refresh(row)
        reliability.add_idempotency(
            actor_id=user_id,
            action=action,
            key=idempotency_key,
            request_hash=digest,
            response_status=201,
            response_body={"id": str(row.id)},
        )
        audit(session, "proposal.created", user_id, row.id)
        return _proposal(row, user_id=user_id, poll_id=None)

    async def _publish(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        house_id: UUID,
        payload: BroadcastCreate,
        idempotency_key: str,
    ) -> BroadcastView:
        """Черновик и подтверждение одним действием — тот же механизм D3."""
        draft = await self.broadcasts.create(
            session,
            actor_id=user_id,
            company_id=None,
            council_house_id=house_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
        if draft.status != "draft":
            return draft  # Повтор того же запроса: уже подтверждено.
        return await self.broadcasts.confirm(
            session,
            actor_id=user_id,
            broadcast_id=draft.id,
            payload=BroadcastConfirm(expected_version=draft.version, service_only=True),
        )

    async def publish_announcement(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        house_id: UUID,
        payload: CouncilAnnouncementCreate,
        idempotency_key: str,
    ) -> CouncilPublished:
        view = await self._publish(
            session,
            user_id=user_id,
            house_id=house_id,
            payload=BroadcastCreate(
                kind="announcement",
                topic="other",
                title=payload.title,
                body=payload.body,
                audience=BroadcastAudience(mode="houses", house_ids=[house_id]),
                channels=["chat", "feed"],
            ),
            idempotency_key=idempotency_key,
        )
        return CouncilPublished(broadcast_id=view.id, status=view.status)

    async def publish_poll(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        house_id: UUID,
        payload: CouncilPollCreate,
        idempotency_key: str,
    ) -> CouncilPublished:
        proposal = await self._open_proposal(session, payload.proposal_id, house_id)
        view = await self._publish(
            session,
            user_id=user_id,
            house_id=house_id,
            payload=BroadcastCreate(
                kind="poll",
                title=payload.poll.question[:200],
                audience=BroadcastAudience(mode="houses", house_ids=[house_id]),
                channels=["chat", "feed"],
                poll=payload.poll,
            ),
            idempotency_key=idempotency_key,
        )
        if proposal is not None and proposal.status == "new":
            self._convert(proposal, view.id, user_id)
        poll_id = await session.scalar(select(Poll.id).where(Poll.broadcast_id == view.id))
        return CouncilPublished(broadcast_id=view.id, status=view.status, poll_id=poll_id)

    async def _open_proposal(
        self, session: AsyncSession, proposal_id: UUID | None, house_id: UUID
    ) -> HouseProposal | None:
        if proposal_id is None:
            return None
        proposal = await session.get(HouseProposal, proposal_id, with_for_update=True)
        if proposal is None or proposal.house_id != house_id:
            raise ResourceNotFound("Предложение не найдено")
        return proposal

    @staticmethod
    def _convert(proposal: HouseProposal, broadcast_id: UUID, actor_id: UUID) -> None:
        proposal.status = "converted"
        proposal.broadcast_id = broadcast_id
        proposal.decided_by = actor_id
        proposal.decided_at = datetime.now(UTC)

    # ================================================================ кабинет УК

    async def _staff_house(
        self, session: AsyncSession, actor_id: UUID, company_id: UUID, house_id: UUID
    ) -> bool:
        """Сотрудник УК с доступом к дому. Возвращает, администратор ли он."""
        member = await require_company(session, actor_id, company_id, admin=False)
        context = await self.memberships.require_house(
            session, user_id=actor_id, house_id=house_id
        )
        if context.tenant_id.value != company_id:
            raise ResourceNotFound("Дом не найден")
        self.memberships.require_permission(context, "ticket.read")
        return member.role == "company_admin"

    async def admin_view(
        self, session: AsyncSession, *, actor_id: UUID, company_id: UUID, house_id: UUID
    ) -> CouncilAdminView:
        admin = await self._staff_house(session, actor_id, company_id, house_id)
        members = list(
            (
                await session.execute(
                    select(HouseCouncilMember, User.display_name)
                    .join(User, User.id == HouseCouncilMember.user_id)
                    .where(
                        HouseCouncilMember.house_id == house_id,
                        HouseCouncilMember.status == "active",
                    )
                    .order_by(HouseCouncilMember.granted_at)
                )
            ).tuples()
        )
        member_ids = {row.user_id for row, _ in members}
        residents: list[CouncilResident] = []
        if admin:
            pairs = await AccessRepository(session).resident_ids(
                [house_id], now=datetime.now(UTC)
            )
            ids = list(dict.fromkeys(user_id for user_id, _ in pairs))
            names = {
                user.id: user.display_name
                for user in await session.scalars(select(User).where(User.id.in_(ids)))
            }
            residents = [
                CouncilResident(
                    user_id=user_id,
                    display_name=names.get(user_id) or "Житель",
                    is_member=user_id in member_ids,
                )
                for user_id in ids
            ]
        return CouncilAdminView(
            house_id=house_id,
            can_manage=admin,
            members=[
                CouncilMemberView(
                    user_id=row.user_id, display_name=name or "Житель", since=row.granted_at
                )
                for row, name in members
            ],
            residents=residents,
            proposals=await self._proposals(session, house_id, user_id=None, only_author=False),
        )

    async def grant(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        house_id: UUID,
        payload: CouncilMemberChange,
    ) -> CouncilAdminView:
        if not await self._staff_house(session, actor_id, company_id, house_id):
            raise AccessDenied("Совет дома отмечает администратор УК")
        pairs = await AccessRepository(session).resident_ids([house_id], now=datetime.now(UTC))
        if payload.user_id not in {user_id for user_id, _ in pairs}:
            raise FieldValidationError(NOT_A_RESIDENT, field="user_id")
        if not await self.is_member(session, payload.user_id, house_id):
            row = HouseCouncilMember(
                id=uuid4(), house_id=house_id, user_id=payload.user_id, granted_by=actor_id
            )
            session.add(row)
            await session.flush()
            audit(session, "council.member_granted", actor_id, row.id, payload.reason)
        return await self.admin_view(
            session, actor_id=actor_id, company_id=company_id, house_id=house_id
        )

    async def revoke(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        house_id: UUID,
        user_id: UUID,
        payload: CouncilMemberRevoke,
    ) -> CouncilAdminView:
        if not await self._staff_house(session, actor_id, company_id, house_id):
            raise AccessDenied("Совет дома отмечает администратор УК")
        row = await session.scalar(
            select(HouseCouncilMember)
            .where(
                HouseCouncilMember.house_id == house_id,
                HouseCouncilMember.user_id == user_id,
                HouseCouncilMember.status == "active",
            )
            .with_for_update()
        )
        if row is not None:
            row.status = "revoked"
            row.revoked_by = actor_id
            row.revoked_at = datetime.now(UTC)
            audit(session, "council.member_revoked", actor_id, row.id, payload.reason)
        return await self.admin_view(
            session, actor_id=actor_id, company_id=company_id, house_id=house_id
        )

    async def proposal_to_poll(
        self,
        session: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        proposal_id: UUID,
        idempotency_key: str,
    ) -> BroadcastView:
        """УК: черновик опроса из предложения — отправка обычным подтверждением."""
        proposal = await session.get(HouseProposal, proposal_id, with_for_update=True)
        if proposal is None:
            raise ResourceNotFound("Предложение не найдено")
        await self._staff_house(session, actor_id, company_id, proposal.house_id)
        if proposal.status != "new":
            raise BroadcastConflict("Предложение уже вынесено на опрос")
        view = await self.broadcasts.create(
            session,
            actor_id=actor_id,
            company_id=company_id,
            payload=BroadcastCreate(
                kind="poll",
                title=proposal.text[:200],
                audience=BroadcastAudience(mode="houses", house_ids=[proposal.house_id]),
                channels=["chat", "feed"],
                poll=PollDraft(
                    question=proposal.text[:300],
                    options=list(PROPOSAL_POLL_OPTIONS),
                    closes_at=datetime.now(UTC) + timedelta(days=PROPOSAL_POLL_DAYS),
                ),
            ),
            idempotency_key=idempotency_key,
        )
        self._convert(proposal, view.id, actor_id)
        await session.flush()
        return view


__all__ = ["CouncilService", "MAX_OPEN_PROPOSALS"]
