"""Квота подключения чатов УК (CHAT-QUOTA-2026-09-26). Транзакцией владеет вызывающий.

Единица — активная привязка бота к домовому чату УК (`ChatBinding.status =
'active'` на управлении этой УК); каждый чат, включая чаты подъездов, — один
слот. Удаление бота из чата (привязка приостановлена) и отзыв привязки
освобождают слот. Снижение квоты ниже числа подключённых чатов их не
отключает: УК «превышена», новые подключения заблокированы.

Окончательная проверка — в транзакции активации привязки A-07, под
блокировкой строки УК (`FOR UPDATE`). Порядок блокировок активации: общий
authority-lock → дом → чат → запрос подключения → строка УК. Изменения квоты
берут authority-lock исключительно, затем строку УК: они не пересекаются с
активацией, пока та держит общий authority-lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domsignal.contracts.quota import (
    ChatQuotaGrantView,
    ChatQuotaRequestView,
    ChatQuotaView,
    CompanyQuotaView,
    GrantKind,
    QuotaRequestStatus,
)
from domsignal.db.models import (
    ChatBinding,
    ChatQuotaGrant,
    ChatQuotaRequest,
    HouseManagement,
    ManagementCompany,
)
from domsignal.db.repositories.reliability import ReliabilityRepository, authority_lock, stable_hash
from domsignal.services import showcase
from domsignal.services.errors import IdempotencyConflict, ResourceNotFound, ServiceError

#: Код problem+json и `last_error_code` запроса подключения при исчерпанной квоте.
QUOTA_EXCEEDED = "CHAT_QUOTA_EXCEEDED"


class QuotaConflict(ServiceError):
    status = 409
    code = "chat_quota_conflict"
    title = "Квота не изменена"


@dataclass(frozen=True)
class QuotaState:
    limit: int | None
    used: int

    @property
    def remaining(self) -> int | None:
        return None if self.limit is None else max(self.limit - self.used, 0)

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    @property
    def over_limit(self) -> bool:
        return self.limit is not None and self.used > self.limit

    def view(self) -> ChatQuotaView:
        return ChatQuotaView(
            limit=self.limit,
            used=self.used,
            remaining=self.remaining,
            over_limit=self.over_limit,
            exhausted=self.exhausted,
        )

    def exceeded_detail(self) -> str:
        return (
            f"Лимит подключённых чатов исчерпан: {self.used} из {self.limit}. "
            "Запросите расширение квоты в кабинете."
        )


async def company_of_management(db: AsyncSession, management_id: UUID) -> UUID | None:
    return cast(
        UUID | None,
        await db.scalar(
            select(HouseManagement.tenant_id).where(HouseManagement.id == management_id)
        ),
    )


async def current_limit(db: AsyncSession, company_id: UUID) -> int | None:
    """Квота из последней записи истории; нет записей — без ограничения."""
    row = await db.scalar(
        select(ChatQuotaGrant)
        .where(ChatQuotaGrant.company_id == company_id)
        .order_by(ChatQuotaGrant.seq.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return row.limit_after if row is not None else None


async def used_slots(db: AsyncSession, company_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(ChatBinding)
            .join(HouseManagement, HouseManagement.id == ChatBinding.management_id)
            .where(HouseManagement.tenant_id == company_id, ChatBinding.status == "active")
        )
        or 0
    )


async def quota_state(db: AsyncSession, company_id: UUID) -> QuotaState:
    return QuotaState(
        limit=await current_limit(db, company_id), used=await used_slots(db, company_id)
    )


async def lock_company(db: AsyncSession, company_id: UUID) -> ManagementCompany:
    company = await db.get(
        ManagementCompany, company_id, with_for_update=True, populate_existing=True
    )
    if company is None:
        raise ResourceNotFound("Организация не найдена")
    return company


async def activation_slot_error(db: AsyncSession, management_id: UUID) -> tuple[str, str] | None:
    """Окончательная проверка перед активацией привязки: код и текст ошибки или `None`.

    Держит блокировку строки УК до конца транзакции активации: параллельная
    активация той же УК ждёт и пересчитывает слоты после фиксации первой.
    """
    company_id = await company_of_management(db, management_id)
    if company_id is None:
        return "management_not_active", "Управление домом не найдено"
    company = await lock_company(db, company_id)
    if company.status != "active":
        return "tenant_suspended", "Организация приостановлена: новые чаты не подключаются."
    state = await quota_state(db, company_id)
    if state.exhausted:
        return QUOTA_EXCEEDED, state.exceeded_detail()
    return None


def grant_view(row: ChatQuotaGrant) -> ChatQuotaGrantView:
    return ChatQuotaGrantView(
        kind=cast(GrantKind, row.kind),
        limit_after=row.limit_after,
        delta=row.delta,
        reason=row.reason,
        created_at=row.created_at,
    )


def request_view(
    row: ChatQuotaRequest, *, company_name: str | None = None, quota: ChatQuotaView | None = None
) -> ChatQuotaRequestView:
    return ChatQuotaRequestView(
        id=row.id,
        company_id=row.company_id,
        company_name=company_name,
        requested_delta=row.requested_delta,
        reason=row.reason,
        status=cast(QuotaRequestStatus, row.status),
        granted_delta=row.granted_delta,
        decision_reason=row.decision_reason,
        created_at=row.created_at,
        decided_at=row.decided_at,
        quota=quota,
    )


class ChatQuotaService:
    """Выдача и изменение квоты, запросы на расширение."""

    @staticmethod
    def add_grant(
        db: AsyncSession,
        *,
        company_id: UUID,
        kind: GrantKind,
        previous: int | None,
        limit_after: int | None,
        reason: str,
        actor_id: UUID | None,
        application_id: UUID | None = None,
        request_id: UUID | None = None,
    ) -> ChatQuotaGrant:
        row = ChatQuotaGrant(
            company_id=company_id,
            kind=kind,
            limit_after=limit_after,
            delta=(
                limit_after - previous
                if limit_after is not None and previous is not None
                else (limit_after if kind == "initial" else None)
            ),
            reason=reason,
            actor_id=actor_id,
            application_id=application_id,
            request_id=request_id,
        )
        db.add(row)
        return row

    async def overview(
        self, db: AsyncSession, company_id: UUID, *, history: int = 50
    ) -> CompanyQuotaView:
        state = await quota_state(db, company_id)
        grants = await db.scalars(
            select(ChatQuotaGrant)
            .where(ChatQuotaGrant.company_id == company_id)
            .order_by(ChatQuotaGrant.seq.desc())
            .limit(history)
        )
        requests = await db.scalars(
            select(ChatQuotaRequest)
            .where(ChatQuotaRequest.company_id == company_id)
            .order_by(ChatQuotaRequest.created_at.desc())
            .limit(history)
        )
        return CompanyQuotaView(
            quota=state.view(),
            grants=[grant_view(g) for g in grants],
            requests=[request_view(r) for r in requests],
        )

    async def set_limit(
        self,
        db: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        limit: int | None,
        reason: str,
    ) -> CompanyQuotaView:
        """Суперадмин задаёт квоту. Снижение не отключает уже подключённые чаты."""
        await authority_lock(db, exclusive=True)
        await lock_company(db, company_id)
        previous = await current_limit(db, company_id)
        if limit is not None and (previous is None or limit < previous):
            await showcase.guard(db, actor_id, company_id=company_id)
        self.add_grant(
            db,
            company_id=company_id,
            kind="adjustment",
            previous=previous,
            limit_after=limit,
            reason=reason,
            actor_id=actor_id,
        )
        await db.flush()
        return await self.overview(db, company_id)

    async def request_expansion(
        self,
        db: AsyncSession,
        *,
        actor_id: UUID,
        company_id: UUID,
        delta: int,
        reason: str,
        key: str,
    ) -> ChatQuotaRequestView:
        """Администратор УК просит +N. Доступ проверяет вызывающий (`require_company`)."""
        repo = ReliabilityRepository(db)
        action = f"chat-quota.request:{company_id}"
        fingerprint = stable_hash({"delta": delta, "reason": reason})
        previous = await repo.idempotency_record(actor_id=actor_id, action=action, key=key)
        if previous:
            if previous.request_hash != fingerprint:
                raise IdempotencyConflict("Ключ уже использован для другого запроса")
            row = await db.get(ChatQuotaRequest, UUID(previous.response_body["id"]))
            assert row is not None
            return request_view(row)
        company = await lock_company(db, company_id)
        if company.status != "active":
            raise QuotaConflict("Организация приостановлена")
        if await current_limit(db, company_id) is None:
            raise QuotaConflict("Квота не ограничена: расширение не требуется.")
        pending = await db.scalar(
            select(ChatQuotaRequest.id).where(
                ChatQuotaRequest.company_id == company_id, ChatQuotaRequest.status == "pending"
            )
        )
        if pending:
            raise QuotaConflict("Запрос на расширение уже на рассмотрении платформы.")
        row = ChatQuotaRequest(
            company_id=company_id, requested_by=actor_id, requested_delta=delta, reason=reason
        )
        db.add(row)
        await db.flush()
        repo.add_idempotency(
            actor_id=actor_id,
            action=action,
            key=key,
            request_hash=fingerprint,
            response_status=201,
            response_body={"id": str(row.id)},
        )
        return request_view(row)

    async def cancel_request(
        self, db: AsyncSession, *, company_id: UUID, request_id: UUID
    ) -> ChatQuotaRequestView:
        row = await db.scalar(
            select(ChatQuotaRequest)
            .where(ChatQuotaRequest.id == request_id, ChatQuotaRequest.company_id == company_id)
            .with_for_update()
        )
        if row is None:
            raise ResourceNotFound("Запрос не найден")
        if row.status not in {"pending", "cancelled"}:
            raise QuotaConflict("Решение по запросу уже принято")
        row.status = "cancelled"
        return request_view(row)

    async def decide(
        self,
        db: AsyncSession,
        *,
        actor_id: UUID,
        request_id: UUID,
        granted: int,
        reason: str,
    ) -> ChatQuotaRequestView:
        """Одобрить полностью, частично (меньше запрошенного) или отклонить (0)."""
        await authority_lock(db, exclusive=True)
        row = await db.get(
            ChatQuotaRequest, request_id, with_for_update=True, populate_existing=True
        )
        if row is None:
            raise ResourceNotFound("Запрос не найден")
        if row.status != "pending":
            raise QuotaConflict("Решение по запросу уже принято. Обновите список.")
        if granted > row.requested_delta:
            raise QuotaConflict("Нельзя выдать больше, чем запрошено")
        await lock_company(db, row.company_id)
        status: Literal["approved", "partially_approved", "rejected"] = (
            "rejected"
            if granted == 0
            else "approved"
            if granted == row.requested_delta
            else "partially_approved"
        )
        row.status = status
        row.granted_delta = granted
        row.decided_by = actor_id
        row.decided_at = datetime.now(UTC)
        row.decision_reason = reason
        if granted:
            previous = await current_limit(db, row.company_id)
            self.add_grant(
                db,
                company_id=row.company_id,
                kind="expansion",
                previous=previous,
                limit_after=None if previous is None else previous + granted,
                reason=reason,
                actor_id=actor_id,
                request_id=row.id,
            )
        await db.flush()
        company = await db.get(ManagementCompany, row.company_id)
        return request_view(
            row,
            company_name=company.name if company else None,
            quota=(await quota_state(db, row.company_id)).view(),
        )

    async def platform_requests(
        self, db: AsyncSession, *, only_pending: bool, offset: int = 0
    ) -> list[ChatQuotaRequestView]:
        query = select(ChatQuotaRequest, ManagementCompany.name).join(
            ManagementCompany, ManagementCompany.id == ChatQuotaRequest.company_id
        )
        if only_pending:
            query = query.where(ChatQuotaRequest.status == "pending")
        rows = (
            await db.execute(
                query.order_by(ChatQuotaRequest.created_at.desc()).offset(offset).limit(100)
            )
        ).all()
        return [
            request_view(
                row, company_name=name, quota=(await quota_state(db, row.company_id)).view()
            )
            for row, name in rows
        ]
