"""Company administration. Caller owns each application transaction.

No platform method reads Report, WorkAttempt or resident observation content.
Authority changes use one exclusive advisory lock, before any domain row locks.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from domsignal.contracts.onboarding import (
    AdminBootstrap,
    ApplicationView,
    AssignmentChange,
    AssignmentView,
    AuditView,
    ChatSummary,
    CompanyApplicationCreate,
    CompanyApproved,
    CompanyContext,
    CompanyHouseView,
    CompanyOverview,
    CompanyView,
    HouseApproval,
    HouseRequestCreate,
    HouseRequestView,
    InvitationView,
    MembershipView,
    OpenAccessChange,
    OpenAccessView,
    PlatformBindingView,
    PlatformHealth,
    PlatformHouseView,
    PlatformOpenHouseView,
    Role,
    StaffDetail,
)
from domsignal.db.models import (
    ChatBinding,
    CompanyOnboardingRequest,
    ConnectionRequest,
    EmployeeCredential,
    EmployeeInvitation,
    House,
    HouseAssignment,
    HouseManagement,
    HouseManagementRequest,
    InboxReceipt,
    Job,
    ManagementCompany,
    MAXChat,
    NotificationDelivery,
    OrganizationMembership,
    Ticket,
    TicketEvent,
    User,
)
from domsignal.db.repositories.reliability import ReliabilityRepository, authority_lock, stable_hash
from domsignal.services.employee_auth import EmployeeAuthService
from domsignal.services.errors import (
    AccessDenied,
    AuthenticationRequired,
    IdempotencyConflict,
    ResourceNotFound,
    ServiceError,
)
from domsignal.services.management import ManagementService
from domsignal.services.resident_access import ResidentAccessService
from domsignal.settings import Settings

OPEN = {"submitted", "under_review", "needs_info"}
TRANSITIONS = {
    "submitted": {"under_review", "needs_info", "approved", "rejected", "cancelled"},
    "under_review": {"needs_info", "approved", "rejected", "cancelled"},
    "needs_info": {"under_review", "approved", "rejected", "cancelled"},
}


class AdministrationConflict(ServiceError):
    status = 409
    code = "administration_conflict"
    title = "Состояние изменилось"


def audit(
    db: AsyncSession, event: str, actor: UUID | None, obj: UUID, reason: str | None = None
) -> None:
    db.add(
        InboxReceipt(
            event_id=f"administration:{uuid4()}",
            event_type=f"administration.{event}",
            payload={
                "actor_id": str(actor) if actor else None,
                "object_id": str(obj),
                "reason": reason,
            },
        )
    )


def transition(
    db: AsyncSession,
    row: CompanyOnboardingRequest | HouseManagementRequest,
    target: str,
    actor: UUID,
    reason: str,
) -> None:
    if target not in TRANSITIONS.get(row.status, set()):
        raise AdministrationConflict("Решение уже принято. Обновите список.")
    row.status = target
    row.reviewed_at = datetime.now(UTC)
    row.reviewed_by_user_id = actor
    row.decision_reason = reason
    kind = "company_application" if isinstance(row, CompanyOnboardingRequest) else "house_request"
    audit(db, f"{kind}.{target}", actor, row.id, reason)


def current_management() -> tuple[ColumnElement[bool], ...]:
    now = datetime.now(UTC)
    return (
        HouseManagement.status == "active",
        HouseManagement.valid_from <= now,
        or_(HouseManagement.valid_to.is_(None), HouseManagement.valid_to > now),
    )


async def require_company(
    db: AsyncSession, actor: UUID, company: UUID, *, admin: bool = True
) -> OrganizationMembership:
    membership = await db.scalar(
        select(OrganizationMembership)
        .join(ManagementCompany, ManagementCompany.id == OrganizationMembership.tenant_id)
        .where(
            OrganizationMembership.user_id == actor,
            OrganizationMembership.tenant_id == company,
            OrganizationMembership.status == "active",
            ManagementCompany.status == "active",
        )
        .execution_options(populate_existing=True)
    )
    if membership is None:
        raise ResourceNotFound("Ресурс не найден")
    if admin and membership.role != "company_admin":
        raise AccessDenied("Требуется администратор УК")
    return membership


async def require_platform(db: AsyncSession, actor: UUID) -> User:
    user = await db.get(User, actor, populate_existing=True)
    if user is None or user.platform_role != "superadmin":
        raise AccessDenied("Нет доступа к платформенному кабинету")
    return user


async def valid_invitation(
    db: AsyncSession, invitation_id: UUID, actor: UUID | None = None
) -> EmployeeInvitation:
    row = await db.get(
        EmployeeInvitation, invitation_id, with_for_update=True, populate_existing=True
    )
    if (
        row is None
        or row.status not in {"pending", "claimed"}
        or row.expires_at <= datetime.now(UTC)
    ):
        raise AuthenticationRequired("Приглашение недействительно. Запросите новую ссылку.")
    company = await db.get(ManagementCompany, row.company_id, populate_existing=True)
    if company is None or company.status != "active":
        raise AuthenticationRequired("Приглашение недействительно. Запросите новую ссылку.")
    if row.invited_by_user_id:
        try:
            await require_company(db, row.invited_by_user_id, row.company_id)
        except (AccessDenied, ResourceNotFound) as exc:
            raise AuthenticationRequired("Приглашение недействительно") from exc
    if row.claimed_by_user_id and row.claimed_by_user_id != actor:
        raise AuthenticationRequired("Приглашение уже закреплено за другим сотрудником")
    return row


async def accept_invitation(db: AsyncSession, invitation_id: UUID, actor: UUID) -> None:
    row = await valid_invitation(db, invitation_id, actor)
    if row.status != "claimed" or row.claimed_by_user_id != actor:
        raise AuthenticationRequired("Сначала подтвердите приглашение")
    credential = await db.scalar(
        select(EmployeeCredential).where(EmployeeCredential.user_id == actor)
    )
    if (
        credential is None
        or not credential.mfa_enabled
        or credential.revoked_at
        or credential.password_change_required
    ):
        raise AuthenticationRequired("Завершите настройку MFA")
    member = await db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == actor,
            OrganizationMembership.tenant_id == row.company_id,
        )
    )
    if member is None:
        db.add(
            OrganizationMembership(
                user_id=actor, tenant_id=row.company_id, role=row.organization_role, status="active"
            )
        )
    elif member.status != "active":
        member.role, member.status = row.organization_role, "active"
    elif member.role != row.organization_role:
        # An invitation never silently downgrades an existing administrator.
        raise AdministrationConflict("Сотрудник уже имеет другую роль в УК")
    row.status, row.accepted_at = "accepted", datetime.now(UTC)
    audit(db, "invitation.accepted", actor, row.id)
    audit(db, "membership.created", actor, row.company_id)


class AdministrationService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.auth = EmployeeAuthService(settings)

    async def history(
        self, db: AsyncSession, obj: UUID | None = None, *, offset: int = 0
    ) -> list[AuditView]:
        query = select(InboxReceipt).where(InboxReceipt.event_type.like("administration.%"))
        if obj:
            query = query.where(InboxReceipt.payload["object_id"].astext == str(obj))
        rows = await db.scalars(
            query.order_by(InboxReceipt.accepted_at.desc()).offset(offset).limit(100)
        )
        return [
            AuditView(
                event=r.event_type,
                occurred_at=r.accepted_at,
                actor_id=r.payload.get("actor_id"),
                object_id=r.payload.get("object_id"),
                reason=r.payload.get("reason"),
            )
            for r in rows
        ]

    async def submit_company(self, db: AsyncSession, payload: CompanyApplicationCreate) -> None:
        await authority_lock(db, exclusive=True)
        existing = await db.scalar(
            select(CompanyOnboardingRequest.id).where(
                CompanyOnboardingRequest.inn == payload.inn,
                CompanyOnboardingRequest.status.in_(OPEN),
            )
        )
        company = await db.scalar(
            select(ManagementCompany.id).where(ManagementCompany.inn == payload.inn)
        )
        if existing or company:
            return  # Same public response; no existence/status oracle and no duplicate.
        row = CompanyOnboardingRequest(**payload.model_dump(), submitted_at=datetime.now(UTC))
        db.add(row)
        await db.flush()
        audit(db, "company_application.submitted", None, row.id)

    async def application(self, db: AsyncSession, obj: UUID) -> ApplicationView:
        row = await db.get(CompanyOnboardingRequest, obj)
        if row is None:
            raise ResourceNotFound("Заявка не найдена")
        view = ApplicationView.model_validate(row, from_attributes=True)
        view.history = await self.history(db, obj)
        return view

    async def issue_invitation(
        self, db: AsyncSession, company: UUID, role: str, actor: UUID | None
    ) -> InvitationView:
        if role not in {"operator", "company_admin"}:
            raise AccessDenied("Недопустимая роль")
        raw = secrets.token_urlsafe(32)
        row = EmployeeInvitation(
            company_id=company,
            invited_by_user_id=actor,
            organization_role=role,
            token_hash=self.auth.digest(raw, "invitation"),
            expires_at=datetime.now(UTC)
            + timedelta(seconds=self.settings.employee_invitation_seconds),
        )
        db.add(row)
        await db.flush()
        audit(db, "invitation.created", actor, row.id)
        view = self.invitation_view(row)
        view.invitation_url = f"{self.settings.public_base_url.rstrip('/')}/admin/invite/{raw}"
        return view

    @staticmethod
    def invitation_view(row: EmployeeInvitation) -> InvitationView:
        view = InvitationView.model_validate(row, from_attributes=True)
        if view.status in {"pending", "claimed"} and view.expires_at <= datetime.now(UTC):
            view.status = "expired"
        return view

    async def decide_company(
        self, db: AsyncSession, obj: UUID, actor: UUID, target: str, reason: str
    ) -> ApplicationView | CompanyApproved:
        await authority_lock(db, exclusive=True)
        await require_platform(db, actor)
        row = await db.get(CompanyOnboardingRequest, obj, with_for_update=True)
        if row is None:
            raise ResourceNotFound("Заявка не найдена")
        transition(db, row, target, actor, reason)
        invitation = None
        if target == "approved":
            if await db.scalar(
                select(ManagementCompany.id).where(ManagementCompany.inn == row.inn)
            ):
                raise AdministrationConflict("Организация с этим ИНН уже создана")
            company = ManagementCompany(
                name=row.short_name,
                legal_name=row.legal_name,
                inn=row.inn,
                contact_name=row.contact_name,
                contact_email=row.contact_email,
                contact_phone=row.contact_phone,
            )
            db.add(company)
            await db.flush()
            row.company_id = company.id
            invitation = await self.issue_invitation(db, company.id, "company_admin", None)
            audit(db, "company.created", actor, company.id)
        await db.flush()
        application = await self.application(db, obj)
        return (
            CompanyApproved(application=application, invitation=invitation)
            if invitation
            else application
        )

    async def bootstrap(self, db: AsyncSession, actor: UUID) -> AdminBootstrap:
        user = await db.get(User, actor)
        if user is None:
            raise AuthenticationRequired("Войдите в кабинет")
        rows = (
            await db.execute(
                select(ManagementCompany, OrganizationMembership)
                .join(
                    OrganizationMembership, OrganizationMembership.tenant_id == ManagementCompany.id
                )
                .where(
                    OrganizationMembership.user_id == actor,
                    OrganizationMembership.status == "active",
                    ManagementCompany.status == "active",
                )
                .order_by(ManagementCompany.name)
            )
        ).all()
        return AdminBootstrap(
            user_id=actor,
            display_name=user.display_name,
            companies=[
                CompanyContext(
                    company_id=c.id,
                    name=c.name,
                    surfaces=(
                        [
                            "overview",
                            "tickets",
                            "signals",
                            "houses",
                            "staff",
                            "chat_connections",
                            "organization",
                        ]
                        if m.role == "company_admin"
                        else ["tickets", "signals", "assigned_houses"]
                    ),
                )
                for c, m in rows
            ],
        )

    async def invite(
        self, db: AsyncSession, actor: UUID, company: UUID, role: str, key: str
    ) -> InvitationView:
        await authority_lock(db, exclusive=True)
        await require_company(db, actor, company)
        repo = ReliabilityRepository(db)
        action = f"employee.invite:{company}"
        fingerprint = stable_hash({"role": role})
        previous = await repo.idempotency_record(actor_id=actor, action=action, key=key)
        if previous:
            if previous.request_hash != fingerprint:
                raise IdempotencyConflict("Ключ уже использован для другого приглашения")
            row = await db.get(EmployeeInvitation, UUID(previous.response_body["id"]))
            assert row is not None
            return self.invitation_view(row)
        view = await self.issue_invitation(db, company, role, actor)
        repo.add_idempotency(
            actor_id=actor,
            action=action,
            key=key,
            request_hash=fingerprint,
            response_status=201,
            response_body={"id": str(view.id)},
        )
        return view

    async def token_invitation(
        self, db: AsyncSession, token: str, actor: UUID | None = None
    ) -> EmployeeInvitation:
        obj = await db.scalar(
            select(EmployeeInvitation.id).where(
                EmployeeInvitation.token_hash == self.auth.digest(token, "invitation")
            )
        )
        if obj is None:
            raise AuthenticationRequired("Приглашение недействительно")
        return await valid_invitation(db, obj, actor)

    async def claim(self, db: AsyncSession, token: str, actor: UUID) -> EmployeeInvitation:
        row = await self.token_invitation(db, token, actor)
        if row.status == "pending":
            row.status, row.claimed_by_user_id, row.claimed_at = "claimed", actor, datetime.now(UTC)
            audit(db, "invitation.claimed", actor, row.id)
        return row

    async def revoke_invitation(
        self, db: AsyncSession, actor: UUID, company: UUID, obj: UUID
    ) -> InvitationView:
        await authority_lock(db, exclusive=True)
        await require_company(db, actor, company)
        row = await db.scalar(
            select(EmployeeInvitation)
            .where(EmployeeInvitation.id == obj, EmployeeInvitation.company_id == company)
            .with_for_update()
        )
        if row is None:
            raise ResourceNotFound("Приглашение не найдено")
        if row.status not in {"pending", "claimed", "revoked"}:
            raise AdministrationConflict("Приглашение уже завершено")
        if row.status != "revoked":
            row.status, row.revoked_at = "revoked", datetime.now(UTC)
            audit(db, "invitation.revoked", actor, obj)
        return self.invitation_view(row)

    async def staff(self, db: AsyncSession, actor: UUID, company: UUID) -> list[MembershipView]:
        await require_company(db, actor, company)
        rows = (
            await db.execute(
                select(User, OrganizationMembership)
                .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                .where(OrganizationMembership.tenant_id == company)
                .order_by(User.display_name)
            )
        ).all()
        return [
            MembershipView(
                user_id=u.id, display_name=u.display_name, role=cast(Role, m.role), status=m.status
            )
            for u, m in rows
        ]

    async def staff_detail(
        self, db: AsyncSession, actor: UUID, company: UUID, user: UUID
    ) -> StaffDetail:
        people = await self.staff(db, actor, company)
        member = next((p for p in people if p.user_id == user), None)
        if member is None:
            raise ResourceNotFound("Сотрудник не найден")
        assignments = await db.scalars(
            select(HouseAssignment)
            .join(HouseManagement)
            .where(
                HouseAssignment.user_id == user,
                HouseAssignment.status == "active",
                HouseManagement.tenant_id == company,
            )
        )
        return StaffDetail(
            **member.model_dump(),
            assignments=[
                AssignmentView.model_validate(a, from_attributes=True) for a in assignments
            ],
        )

    async def assign(
        self, db: AsyncSession, actor: UUID, company: UUID, user: UUID, change: AssignmentChange
    ) -> StaffDetail:
        await authority_lock(db, exclusive=True)
        await require_company(db, actor, company)
        await require_company(db, user, company, admin=False)
        management = await db.scalar(
            select(HouseManagement).where(
                HouseManagement.id == change.management_id,
                HouseManagement.tenant_id == company,
                *current_management(),
            )
        )
        if management is None:
            raise ResourceNotFound("Управление домом не найдено")
        row = await db.scalar(
            select(HouseAssignment).where(
                HouseAssignment.user_id == user, HouseAssignment.management_id == management.id
            )
        )
        if row and change.role is None:
            row.status = "revoked"
        elif row and change.role:
            row.role, row.status = change.role, "active"
        elif change.role:
            db.add(HouseAssignment(user_id=user, management_id=management.id, role=change.role))
        audit(db, "assignment.changed", actor, management.id)
        await db.flush()
        return await self.staff_detail(db, actor, company, user)

    async def revoke_member(self, db: AsyncSession, actor: UUID, company: UUID, user: UUID) -> None:
        await authority_lock(db, exclusive=True)
        await require_company(db, actor, company)
        member = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user, OrganizationMembership.tenant_id == company
            )
        )
        if member is None:
            raise ResourceNotFound("Сотрудник не найден")
        if member.status == "revoked":
            return
        count = await db.scalar(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.tenant_id == company,
                OrganizationMembership.status == "active",
                OrganizationMembership.role == "company_admin",
            )
        )
        if member.role == "company_admin" and (count or 0) <= 1:
            raise AdministrationConflict("Нельзя отозвать последнего администратора УК")
        member.status = "revoked"
        issued = await db.scalars(
            select(EmployeeInvitation).where(
                EmployeeInvitation.company_id == company,
                EmployeeInvitation.invited_by_user_id == user,
                EmployeeInvitation.status.in_(["pending", "claimed"]),
            )
        )
        for invitation in issued:
            invitation.status, invitation.revoked_at = "revoked", datetime.now(UTC)
            audit(db, "invitation.revoked", actor, invitation.id)
        managements = select(HouseManagement.id).where(HouseManagement.tenant_id == company)
        assignments = await db.scalars(
            select(HouseAssignment).where(
                HouseAssignment.user_id == user, HouseAssignment.management_id.in_(managements)
            )
        )
        for assignment in assignments:
            assignment.status = "revoked"
        tickets = await db.scalars(
            select(Ticket)
            .where(
                Ticket.management_id.in_(managements),
                Ticket.assignee_id == user,
                Ticket.status.not_in(["closed", "cancelled"]),
            )
            .order_by(Ticket.id)
            .with_for_update()
        )
        for ticket in tickets:
            ticket.assignee_id = ticket.accepted_by = ticket.accepted_at = None
            ticket.version += 1
            ticket.updated_at = datetime.now(UTC)
            ticket.routing_reason = "employee_revoked"
            db.add(
                TicketEvent(
                    ticket_id=ticket.id,
                    actor_id=actor,
                    kind="assigned",
                    version=ticket.version,
                    from_status=ticket.status,
                    to_status=ticket.status,
                    reason="employee_revoked",
                    assignee_id=None,
                    visibility="internal",
                )
            )
        # Identity sessions intentionally survive; A-15 removes this company on every request.
        # Other company memberships, resident sessions and historical work are preserved.
        audit(db, "membership.revoked", actor, user)

    async def submit_house(
        self, db: AsyncSession, actor: UUID, company: UUID, payload: HouseRequestCreate, key: str
    ) -> HouseRequestView:
        await authority_lock(db, exclusive=True)
        await require_company(db, actor, company)
        repo = ReliabilityRepository(db)
        action, fingerprint = (
            f"house.request:{company}",
            stable_hash(payload.model_dump(mode="json")),
        )
        old = await repo.idempotency_record(actor_id=actor, action=action, key=key)
        if old:
            if old.request_hash != fingerprint:
                raise IdempotencyConflict("Ключ уже использован")
            return await self.house_request(db, UUID(old.response_body["id"]))
        normalized = " ".join(payload.requested_address.casefold().split())
        candidate = await db.scalar(select(House.id).where(func.lower(House.address) == normalized))
        row = HouseManagementRequest(
            **payload.model_dump(),
            normalized_address=normalized,
            company_id=company,
            submitted_by_user_id=actor,
            candidate_house_id=candidate,
        )
        db.add(row)
        await db.flush()
        audit(db, "house_request.submitted", actor, row.id)
        repo.add_idempotency(
            actor_id=actor,
            action=action,
            key=key,
            request_hash=fingerprint,
            response_status=201,
            response_body={"id": str(row.id)},
        )
        return await self.house_request(db, row.id)

    async def house_request(self, db: AsyncSession, obj: UUID) -> HouseRequestView:
        row = await db.get(HouseManagementRequest, obj)
        if row is None:
            raise ResourceNotFound("Заявка не найдена")
        view = HouseRequestView.model_validate(row, from_attributes=True)
        view.history = await self.history(db, obj)
        return view

    async def decide_house(
        self,
        db: AsyncSession,
        obj: UUID,
        actor: UUID,
        target: str,
        reason: str,
        approval: HouseApproval | None = None,
    ) -> HouseRequestView:
        await authority_lock(db, exclusive=True)
        await require_platform(db, actor)
        row = await db.get(HouseManagementRequest, obj, with_for_update=True)
        if row is None:
            raise ResourceNotFound("Заявка не найдена")
        company = await db.get(ManagementCompany, row.company_id)
        if company is None or company.status != "active":
            raise AdministrationConflict("Организация приостановлена")
        transition(db, row, target, actor, reason)
        if target == "approved":
            assert approval is not None
            if (
                approval.valid_from < datetime.now(UTC) - timedelta(days=1)
                and not approval.confirm_backdate
            ):
                raise AdministrationConflict(
                    "Для прошлой даты нужно явное подтверждение и основание"
                )
            if approval.resolution == "new":
                if await db.scalar(select(House.id).where(House.address == row.requested_address)):
                    raise AdministrationConflict(
                        "Такой адрес уже существует. Выберите существующий дом."
                    )
                house = House(name=row.requested_address[:200], address=row.requested_address)
                db.add(house)
                await db.flush()
                house_id = house.id
            else:
                assert approval.house_id is not None
                house_id = approval.house_id
            try:
                management = await ManagementService().create(
                    db,
                    house_id=house_id,
                    tenant_id=row.company_id,
                    valid_from=approval.valid_from,
                    created_by=actor,
                    basis_type="approved_request",
                    basis_reference=str(row.id),
                )
            except ValueError as exc:
                raise AdministrationConflict(
                    "Период пересекается с действующим управлением"
                ) from exc
            management.ticket_intake_enabled = True
            row.management_id = management.id
            audit(db, "management.approved", actor, management.id, reason)
        await db.flush()
        return await self.house_request(db, obj)

    async def houses(self, db: AsyncSession, actor: UUID, company: UUID) -> list[CompanyHouseView]:
        member = await require_company(db, actor, company, admin=False)
        query = (
            select(House, HouseManagement)
            .join(HouseManagement)
            .where(HouseManagement.tenant_id == company, *current_management())
        )
        if member.role != "company_admin":
            query = query.join(
                HouseAssignment, HouseAssignment.management_id == HouseManagement.id
            ).where(HouseAssignment.user_id == actor, HouseAssignment.status == "active")
        rows = (await db.execute(query.order_by(House.address))).all()
        result = []
        for house, management in rows:
            assignments = list(
                await db.scalars(
                    select(HouseAssignment)
                    .join(
                        OrganizationMembership,
                        OrganizationMembership.user_id == HouseAssignment.user_id,
                    )
                    .where(
                        HouseAssignment.management_id == management.id,
                        HouseAssignment.status == "active",
                        OrganizationMembership.tenant_id == company,
                        OrganizationMembership.status == "active",
                    )
                )
            )
            responsible = sum(a.role == "responsible" for a in assignments)
            bindings = (
                await db.execute(
                    select(ChatBinding, MAXChat.title)
                    .join(MAXChat, MAXChat.max_chat_id == ChatBinding.max_chat_id)
                    .where(ChatBinding.management_id == management.id)
                )
            ).all()
            requests = list(
                await db.scalars(
                    select(ConnectionRequest)
                    .where(ConnectionRequest.management_id == management.id)
                    .order_by(ConnectionRequest.created_at.desc())
                    .limit(100)
                )
            )
            from domsignal.contracts.chat_connections import ConnectionView

            result.append(
                CompanyHouseView(
                    house_id=house.id,
                    management_id=management.id,
                    address=house.address,
                    name=house.name,
                    valid_from=management.valid_from,
                    valid_to=management.valid_to,
                    operator_count=sum(a.role == "operator" for a in assignments),
                    responsible_count=responsible,
                    open_ticket_count=await db.scalar(
                        select(func.count())
                        .select_from(Ticket)
                        .where(
                            Ticket.management_id == management.id,
                            Ticket.status.not_in(["closed", "cancelled"]),
                        )
                    )
                    or 0,
                    bindings=[
                        ChatSummary(
                            id=b.id,
                            title=title,
                            max_chat_id=b.max_chat_id,
                            status=b.status,
                            scope_type=b.scope_type,
                            scope_value=b.scope_value,
                            suspension_reason=b.suspension_reason,
                            passive_capture_enabled=b.passive_capture_enabled,
                        )
                        for b, title in bindings
                    ],
                    connection_requests=[
                        ConnectionView.model_validate(r, from_attributes=True) for r in requests
                    ]
                    if member.role == "company_admin"
                    else [],
                    warning="Для дома назначено несколько ответственных. "
                    "Новые заявки будут поступать в общую очередь дома."
                    if responsible > 1
                    else None,
                    open_resident_access=house.open_resident_access,
                    open_access_changed_at=house.open_access_changed_at,
                )
            )
        return result

    async def set_open_access(
        self,
        db: AsyncSession,
        actor: UUID,
        company: UUID,
        house_id: UUID,
        payload: OpenAccessChange,
    ) -> OpenAccessView:
        """Открытый доступ к дому переключает администратор УК этого дома.

        Чужая УК и чужой дом — 404; сотрудник без роли администратора — 403.
        Выключение сразу завершает членства по открытому доступу; заявки и
        история остаются у УК.
        """
        await require_company(db, actor, company)
        await authority_lock(db)
        house = await db.scalar(
            select(House)
            .join(HouseManagement, HouseManagement.house_id == House.id)
            .where(
                House.id == house_id,
                HouseManagement.tenant_id == company,
                *current_management(),
            )
            .with_for_update(of=House)
            .execution_options(populate_existing=True)
        )
        if house is None:
            raise ResourceNotFound("Дом не найден")
        changed = house.open_resident_access != payload.enabled
        ended = await ResidentAccessService.set_open_access(
            db, house=house, enabled=payload.enabled, actor_id=actor
        )
        if changed:
            audit(
                db,
                "house.open_access_enabled" if payload.enabled else "house.open_access_disabled",
                actor,
                house.id,
            )
        return OpenAccessView(
            house_id=house.id,
            open_resident_access=house.open_resident_access,
            open_access_changed_at=house.open_access_changed_at,
            ended_memberships=ended,
        )

    async def platform_open_houses(self, db: AsyncSession) -> list[PlatformOpenHouseView]:
        """Все дома с открытым доступом — для суперадмина."""
        rows = (
            await db.execute(
                select(House, ManagementCompany)
                .join(HouseManagement, HouseManagement.house_id == House.id)
                .join(ManagementCompany, ManagementCompany.id == HouseManagement.tenant_id)
                .where(House.open_resident_access.is_(True), *current_management())
                .order_by(House.address)
                .limit(500)
            )
        ).all()
        return [
            PlatformOpenHouseView(
                house_id=house.id,
                address=house.address,
                name=house.name,
                company_id=company.id,
                company_name=company.name,
                open_access_changed_at=house.open_access_changed_at,
            )
            for house, company in rows
        ]

    async def platform_close_open_access(
        self, db: AsyncSession, actor: UUID, house_id: UUID, reason: str
    ) -> OpenAccessView:
        """Суперадмин закрывает открытый доступ к дому; причина — в аудит."""
        await require_platform(db, actor)
        await authority_lock(db)
        house = await db.get(House, house_id, with_for_update=True, populate_existing=True)
        if house is None:
            raise ResourceNotFound("Дом не найден")
        changed = house.open_resident_access
        ended = await ResidentAccessService.set_open_access(
            db, house=house, enabled=False, actor_id=actor
        )
        if changed:
            audit(db, "house.open_access_closed_by_platform", actor, house.id, reason)
        return OpenAccessView(
            house_id=house.id,
            open_resident_access=house.open_resident_access,
            open_access_changed_at=house.open_access_changed_at,
            ended_memberships=ended,
        )

    async def company(self, db: AsyncSession, obj: UUID) -> CompanyView:
        row = await db.get(ManagementCompany, obj)
        if row is None:
            raise ResourceNotFound("Организация не найдена")
        view = CompanyView.model_validate(row, from_attributes=True)
        view.house_count = (
            await db.scalar(
                select(func.count())
                .select_from(HouseManagement)
                .where(HouseManagement.tenant_id == obj, *current_management())
            )
            or 0
        )
        view.employee_count = (
            await db.scalar(
                select(func.count())
                .select_from(OrganizationMembership)
                .where(
                    OrganizationMembership.tenant_id == obj,
                    OrganizationMembership.status == "active",
                )
            )
            or 0
        )
        view.binding_problems = (
            await db.scalar(
                select(func.count())
                .select_from(ChatBinding)
                .join(HouseManagement)
                .where(
                    HouseManagement.tenant_id == obj,
                    ChatBinding.status.in_(["suspended", "revoked"]),
                )
            )
            or 0
        )
        return view

    async def overview(self, db: AsyncSession, actor: UUID, company: UUID) -> CompanyOverview:
        await require_company(db, actor, company)
        info = await self.company(db, company)
        managements = select(HouseManagement.id).where(
            HouseManagement.tenant_id == company, *current_management()
        )
        query = (
            select(func.count())
            .select_from(Ticket)
            .where(
                Ticket.management_id.in_(managements), Ticket.status.not_in(["closed", "cancelled"])
            )
        )
        return CompanyOverview(
            open_tickets=await db.scalar(query) or 0,
            unassigned_tickets=await db.scalar(query.where(Ticket.assignee_id.is_(None))) or 0,
            verification_pending=await db.scalar(
                query.where(Ticket.status == "verification_pending")
            )
            or 0,
            house_count=info.house_count,
            active_employees=info.employee_count,
            binding_problems=info.binding_problems,
        )

    async def company_status(
        self, db: AsyncSession, actor: UUID, obj: UUID, status: str, reason: str
    ) -> CompanyView:
        await authority_lock(db, exclusive=True)
        await require_platform(db, actor)
        row = await db.get(ManagementCompany, obj, with_for_update=True)
        if row is None:
            raise ResourceNotFound("Организация не найдена")
        if row.status == "archived":
            raise AdministrationConflict("Организация архивирована")
        row.status = status
        audit(db, f"company.{status}", actor, obj, reason)
        await db.flush()
        return await self.company(db, obj)

    async def reissue_first_admin(
        self, db: AsyncSession, actor: UUID, company: UUID, key: str, reason: str
    ) -> InvitationView:
        await authority_lock(db, exclusive=True)
        await require_platform(db, actor)
        row = await db.get(ManagementCompany, company)
        approved = await db.scalar(
            select(CompanyOnboardingRequest.id).where(
                CompanyOnboardingRequest.company_id == company,
                CompanyOnboardingRequest.status == "approved",
            )
        )
        active = await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.tenant_id == company,
                OrganizationMembership.role == "company_admin",
                OrganizationMembership.status == "active",
            )
        )
        if row is None or not approved:
            raise ResourceNotFound("Одобренная организация не найдена")
        if active or row.status != "active":
            raise AdministrationConflict("Первый администратор уже активен или УК приостановлена")
        repo = ReliabilityRepository(db)
        action = f"first-admin.reissue:{company}"
        previous = await repo.idempotency_record(actor_id=actor, action=action, key=key)
        if previous:
            if previous.request_hash != stable_hash({"reason": reason}):
                raise IdempotencyConflict("Ключ уже использован")
            invitation = await db.get(EmployeeInvitation, UUID(previous.response_body["id"]))
            assert invitation is not None
            return self.invitation_view(invitation)
        old = await db.scalars(
            select(EmployeeInvitation).where(
                EmployeeInvitation.company_id == company,
                EmployeeInvitation.invited_by_user_id.is_(None),
                EmployeeInvitation.status.in_(["pending", "claimed"]),
            )
        )
        for invitation in old:
            invitation.status, invitation.revoked_at = "revoked", datetime.now(UTC)
            audit(db, "invitation.revoked", actor, invitation.id, reason)
        result = await self.issue_invitation(db, company, "company_admin", None)
        repo.add_idempotency(
            actor_id=actor,
            action=action,
            key=key,
            request_hash=stable_hash({"reason": reason}),
            response_status=201,
            response_body={"id": str(result.id)},
        )
        audit(db, "first_admin.reissued", actor, company, reason)
        return result

    async def platform_houses(self, db: AsyncSession, offset: int = 0) -> list[PlatformHouseView]:
        return [
            PlatformHouseView.model_validate(h, from_attributes=True)
            for h in await db.scalars(
                select(House).order_by(House.address).offset(offset).limit(100)
            )
        ]

    async def disputes(self, db: AsyncSession, offset: int = 0) -> list[PlatformBindingView]:
        rows = (
            await db.execute(
                select(ChatBinding, MAXChat.title, HouseManagement.tenant_id)
                .join(MAXChat, MAXChat.max_chat_id == ChatBinding.max_chat_id)
                .join(HouseManagement)
                .where(ChatBinding.status.in_(["suspended", "revoked"]))
                .order_by(ChatBinding.updated_at.desc())
                .offset(offset)
                .limit(100)
            )
        ).all()
        return [
            PlatformBindingView(
                id=b.id,
                title=title,
                max_chat_id=b.max_chat_id,
                status=b.status,
                scope_type=b.scope_type,
                scope_value=b.scope_value,
                suspension_reason=b.suspension_reason,
                house_id=b.house_id,
                management_id=b.management_id,
                company_id=tenant,
            )
            for b, title, tenant in rows
        ]

    async def health(self, db: AsyncSession) -> PlatformHealth:
        return PlatformHealth(
            database="ready",
            pending_jobs=await db.scalar(
                select(func.count()).select_from(Job).where(Job.status == "pending")
            )
            or 0,
            failed_jobs=await db.scalar(
                select(func.count()).select_from(Job).where(Job.status == "failed")
            )
            or 0,
            pending_deliveries=await db.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(NotificationDelivery.status == "pending")
            )
            or 0,
        )
