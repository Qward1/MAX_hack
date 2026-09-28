"""Самостоятельный путь УК и её сотрудников без ручной передачи ссылок (D2).

* Страница статуса заявки по секретной ссылке: статус, вопросы платформы и
  ответ, выданная квота и «Создать аккаунт администратора» — то же
  приглашение первого администратора A-10 (пароль + TOTP).
* Сброс пароля/MFA сотрудника администратором УК: одноразовая ссылка по
  образцу приглашения; выдача сразу отзывает сессии и закрывает вход прежним
  паролем.
* Открытая регистрация сотрудников по публичной ссылке `/join/<код>`:
  переключатель суперадмина у конкретной УК, по умолчанию выключен;
  регистрация — логин, пароль, TOTP → оператор УК на всех её домах.

Во всех таблицах — только хэши ссылок. Транзакцией владеет вызывающий.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from domsignal.contracts.onboarding import (
    ApplicationStatusView,
    CompanyDestination,
    CredentialResetIssued,
    CredentialResetPreview,
    EmployeeDestinations,
    OpenRegistrationEmployee,
    OpenRegistrationView,
    Role,
)
from domsignal.db.models import (
    ChatQuotaGrant,
    CompanyApplicationMessage,
    CompanyOnboardingRequest,
    EmployeeCredential,
    EmployeeCredentialReset,
    EmployeeInvitation,
    ManagementCompany,
    OrganizationMembership,
    RecoveryCode,
    User,
)
from domsignal.db.models.employee_auth import AuthChallenge
from domsignal.db.repositories.reliability import authority_lock
from domsignal.services import showcase
from domsignal.services.employee_auth import HASHER, EmployeeAuthService
from domsignal.services.employee_auth import audit as auth_audit
from domsignal.services.errors import AuthenticationRequired, ResourceNotFound
from domsignal.services.onboarding import (
    AdministrationConflict,
    AdministrationService,
    application_messages,
    audit,
    require_company,
    require_platform,
)
from domsignal.settings import Settings

#: Срок одноразовой ссылки сброса пароля/MFA.
RESET_SECONDS = 24 * 3600
#: Префикс кода в ссылке на бота «Получать уведомления в MAX».
NOTIFY_PREFIX = "ca_"
NOTIFY_LINKED = (
    "Буду присылать сюда изменения статуса заявки {name}. Подробности — на "
    "странице статуса заявки."
)
NOTIFY_INVALID = (
    "Ссылка для уведомлений о заявке устарела. Откройте страницу статуса заявки и "
    "нажмите «Получать уведомления в MAX» ещё раз."
)


def notify_digest(settings: Settings, code: str) -> str:
    return EmployeeAuthService(settings).digest(code, "application-notify")


LINK_INVALID = "Ссылка недействительна или устарела. Запросите новую."


class CompanySignupService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.auth = EmployeeAuthService(settings)
        self.administration = AdministrationService(settings)

    def base_url(self) -> str:
        return self.settings.public_base_url.rstrip("/")

    # --- страница статуса заявки -------------------------------------------------

    async def application_by_token(
        self, db: AsyncSession, token: str, *, lock: bool = False
    ) -> CompanyOnboardingRequest:
        query = select(CompanyOnboardingRequest).where(
            CompanyOnboardingRequest.status_token_hash
            == self.auth.digest(token, "application-status")
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await db.scalar(query)
        if row is None:
            raise ResourceNotFound("Заявка по этой ссылке не найдена. Проверьте ссылку.")
        return row

    async def admin_account(
        self, db: AsyncSession, row: CompanyOnboardingRequest
    ) -> Literal["unavailable", "create", "active"]:
        if row.status != "approved" or row.company_id is None:
            return "unavailable"
        company = await db.get(ManagementCompany, row.company_id, populate_existing=True)
        if company is None or company.status != "active":
            return "unavailable"
        admin = await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.tenant_id == row.company_id,
                OrganizationMembership.role == "company_admin",
                OrganizationMembership.status == "active",
            )
        )
        return "active" if admin else "create"

    async def status(self, db: AsyncSession, token: str) -> ApplicationStatusView:
        row = await self.application_by_token(db, token)
        grant = await db.scalar(
            select(ChatQuotaGrant).where(
                ChatQuotaGrant.application_id == row.id, ChatQuotaGrant.kind == "initial"
            )
        )
        return ApplicationStatusView(
            status=cast(
                Literal[
                    "submitted", "under_review", "needs_info", "approved", "rejected", "cancelled"
                ],
                row.status,
            ),
            short_name=row.short_name,
            submitted_at=row.submitted_at,
            requested_chat_count=row.requested_chat_count,
            house_addresses=list(row.house_addresses or []),
            messages=await application_messages(db, row.id),
            can_reply=row.status == "needs_info",
            decision_reason=row.decision_reason if row.status in {"approved", "rejected"} else None,
            granted_chat_quota=grant.limit_after if grant else None,
            quota_unlimited=grant is not None and grant.limit_after is None,
            admin_account=await self.admin_account(db, row),
            max_notifications=row.notify_user_id is not None,
        )

    async def reply(self, db: AsyncSession, token: str, text: str) -> ApplicationStatusView:
        await authority_lock(db, exclusive=True)
        row = await self.application_by_token(db, token, lock=True)
        if row.status != "needs_info":
            raise AdministrationConflict("Платформа не ждёт ответа по этой заявке.")
        db.add(CompanyApplicationMessage(application_id=row.id, author="applicant", text=text))
        # Ответ возвращает заявку на рассмотрение; решает по-прежнему платформа.
        row.status = "under_review"
        audit(db, "company_application.answered", None, row.id)
        await db.flush()
        return await self.status(db, token)

    async def notify_link(self, db: AsyncSession, token: str) -> str:
        """Ссылка на бота с новым одноразовым кодом; прежний код перестаёт работать."""
        bot = self.settings.max_bot_username
        if not bot:
            raise AdministrationConflict("Бот ДомСигнала в MAX сейчас недоступен.")
        row = await self.application_by_token(db, token, lock=True)
        code = secrets.token_urlsafe(24)
        row.notify_code_hash = notify_digest(self.settings, code)
        audit(db, "company_application.notify_link", None, row.id)
        return f"https://max.ru/{bot}?start={NOTIFY_PREFIX}{code}"

    def derived_invitation(self, token: str, row: CompanyOnboardingRequest) -> str:
        """Ссылка приглашения, воспроизводимая только владельцем ссылки статуса.

        В базе нет ни ссылки статуса, ни ссылки приглашения — только хэши. Та же
        ссылка статуса даёт то же приглашение, пока оно действует; истёкшее или
        отозванное заменяет следующее поколение.
        """
        mac = hmac.new(
            self.settings.session_secret.encode(),
            f"first-admin:{row.id}:{row.admin_invite_generation}:{token}".encode(),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    async def admin_invitation(self, db: AsyncSession, token: str) -> str:
        await authority_lock(db, exclusive=True)
        row = await self.application_by_token(db, token, lock=True)
        state = await self.admin_account(db, row)
        if state == "active":
            raise AdministrationConflict("Администратор уже создан. Войдите в кабинет.")
        if state != "create" or row.company_id is None:
            raise AdministrationConflict("Аккаунт можно создать после одобрения заявки.")
        for _ in range(2):
            raw = self.derived_invitation(token, row)
            existing = await db.scalar(
                select(EmployeeInvitation)
                .where(EmployeeInvitation.token_hash == self.auth.digest(raw, "invitation"))
                .with_for_update()
            )
            if existing is None:
                invitation = EmployeeInvitation(
                    company_id=row.company_id,
                    invited_by_user_id=None,
                    organization_role="company_admin",
                    source="application_status",
                    token_hash=self.auth.digest(raw, "invitation"),
                    expires_at=datetime.now(UTC)
                    + timedelta(seconds=self.settings.employee_invitation_seconds),
                )
                db.add(invitation)
                await db.flush()
                audit(db, "invitation.created", None, invitation.id)
                return f"{self.base_url()}/admin/invite/{raw}"
            if existing.status in {"pending", "claimed"} and existing.expires_at > datetime.now(
                UTC
            ):
                return f"{self.base_url()}/admin/invite/{raw}"
            row.admin_invite_generation += 1
        raise AdministrationConflict("Не удалось выпустить приглашение. Повторите попытку.")

    # --- сброс пароля/MFA ----------------------------------------------------------

    async def issue_reset(
        self,
        db: AsyncSession,
        *,
        actor: UUID,
        company: UUID,
        user: UUID,
        kind: Literal["password", "password_mfa"],
    ) -> CredentialResetIssued:
        await authority_lock(db, exclusive=True)
        await require_company(db, actor, company)
        if user == actor:
            raise AdministrationConflict(
                "Свой пароль и аутентификатор сбрасывает другой администратор УК."
            )
        await showcase.guard(db, actor, target_user_id=user)
        member = await db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user,
                OrganizationMembership.tenant_id == company,
                OrganizationMembership.status == "active",
            )
        )
        if member is None:
            raise ResourceNotFound("Сотрудник не найден")
        target = await db.get(User, user)
        if target is None or target.platform_role:
            raise AdministrationConflict("Учётную запись платформы сбрасывает платформа.")
        elsewhere = await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.user_id == user,
                OrganizationMembership.tenant_id != company,
                OrganizationMembership.status == "active",
            )
        )
        if elsewhere:
            raise AdministrationConflict(
                "Сотрудник работает и в другой УК. Сброс выполняет платформа."
            )
        credential = await db.scalar(
            select(EmployeeCredential).where(EmployeeCredential.user_id == user).with_for_update()
        )
        if credential is None:
            raise AdministrationConflict("У сотрудника нет учётной записи для входа.")
        now = datetime.now(UTC)
        await db.execute(
            update(EmployeeCredentialReset)
            .where(
                EmployeeCredentialReset.user_id == user,
                EmployeeCredentialReset.status == "pending",
            )
            .values(status="revoked", revoked_at=now)
        )
        # Прежний пароль больше не открывает вход, все сессии отозваны сразу.
        credential.password_change_required = True
        credential.temporary_expires_at = None
        await self.auth.revoke_sessions(db, credential)
        raw = secrets.token_urlsafe(32)
        row = EmployeeCredentialReset(
            company_id=company,
            user_id=user,
            created_by=actor,
            kind=kind,
            token_hash=self.auth.digest(raw, "credential-reset"),
            expires_at=now + timedelta(seconds=RESET_SECONDS),
        )
        db.add(row)
        await db.flush()
        audit(db, f"credential_reset.{kind}", actor, user)
        auth_audit(db, "password_reset", user)
        return CredentialResetIssued(
            kind=kind, reset_url=f"{self.base_url()}/admin/reset/{raw}", expires_at=row.expires_at
        )

    async def valid_reset(
        self, db: AsyncSession, token: str
    ) -> tuple[EmployeeCredentialReset, EmployeeCredential, ManagementCompany]:
        row = await db.scalar(
            select(EmployeeCredentialReset)
            .where(
                EmployeeCredentialReset.token_hash == self.auth.digest(token, "credential-reset")
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.status != "pending" or row.expires_at <= datetime.now(UTC):
            raise AuthenticationRequired(LINK_INVALID)
        company = await db.get(ManagementCompany, row.company_id, populate_existing=True)
        member = await db.scalar(
            select(OrganizationMembership.id).where(
                OrganizationMembership.user_id == row.user_id,
                OrganizationMembership.tenant_id == row.company_id,
                OrganizationMembership.status == "active",
            )
        )
        credential = await db.scalar(
            select(EmployeeCredential)
            .where(EmployeeCredential.user_id == row.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if company is None or company.status != "active" or member is None or credential is None:
            raise AuthenticationRequired(LINK_INVALID)
        return row, credential, company

    async def preview_reset(self, db: AsyncSession, token: str) -> CredentialResetPreview:
        row, credential, company = await self.valid_reset(db, token)
        return CredentialResetPreview(
            company_name=company.name,
            login_name=credential.login_name,
            kind=cast(Literal["password", "password_mfa"], row.kind),
            expires_at=row.expires_at,
        )

    async def complete_reset(
        self, db: AsyncSession, *, token: str, password: str, challenge: AuthChallenge
    ) -> tuple[str, str]:
        """Новый пароль по ссылке. Возвращает следующий шаг входа: MFA."""
        row, credential, _ = await self.valid_reset(db, token)
        now = datetime.now(UTC)
        credential.password_hash = await run_in_threadpool(HASHER.hash, password)
        credential.password_changed_at = now
        credential.password_change_required = False
        credential.temporary_expires_at = None
        credential.temporary_used_at = None
        credential.revoked_at = None
        if row.kind == "password_mfa":
            credential.mfa_enabled = False
            credential.encrypted_totp_secret = None
            credential.last_totp_step = None
            await db.execute(
                update(RecoveryCode)
                .where(RecoveryCode.credential_id == credential.id, RecoveryCode.used_at.is_(None))
                .values(used_at=now)
            )
        await self.auth.revoke_sessions(db, credential)
        row.status, row.used_at = "used", now
        challenge.consumed_at = now
        stage = "mfa_challenge" if credential.mfa_enabled else "mfa_enroll"
        next_token = self.auth.new_challenge(db, stage=stage, credential_id=credential.id)
        await self.auth.reset_rate(db, credential.login_name)
        audit(db, "credential_reset.used", credential.user_id, row.id)
        auth_audit(db, "password_changed", credential.user_id)
        if row.kind == "password_mfa":
            auth_audit(db, "mfa_reset", credential.user_id)
        return next_token, stage

    # --- открытая регистрация сотрудников -----------------------------------------------

    async def open_registration(
        self, db: AsyncSession, company_id: UUID, *, join_url: str | None = None
    ) -> OpenRegistrationView:
        company = await db.get(ManagementCompany, company_id, populate_existing=True)
        if company is None:
            raise ResourceNotFound("Организация не найдена")
        rows = (
            await db.execute(
                select(EmployeeInvitation, User, EmployeeCredential, OrganizationMembership)
                .join(User, User.id == EmployeeInvitation.claimed_by_user_id)
                .outerjoin(EmployeeCredential, EmployeeCredential.user_id == User.id)
                .outerjoin(
                    OrganizationMembership,
                    (OrganizationMembership.user_id == User.id)
                    & (OrganizationMembership.tenant_id == company_id),
                )
                .where(
                    EmployeeInvitation.company_id == company_id,
                    EmployeeInvitation.source == "open_registration",
                    EmployeeInvitation.status == "accepted",
                )
                .order_by(EmployeeInvitation.accepted_at.desc())
                .limit(500)
            )
        ).all()
        return OpenRegistrationView(
            enabled=company.open_registration_enabled,
            changed_at=company.open_registration_changed_at,
            join_url=join_url,
            employees=[
                OpenRegistrationEmployee(
                    user_id=user.id,
                    display_name=user.display_name,
                    login_name=credential.login_name if credential else None,
                    status=member.status if member else "revoked",
                    registered_at=invitation.accepted_at,
                )
                for invitation, user, credential, member in rows
            ],
        )

    async def set_open_registration(
        self, db: AsyncSession, *, actor: UUID, company_id: UUID, enabled: bool, reason: str
    ) -> OpenRegistrationView:
        """Включить (или выпустить новую ссылку) и закрыть регистрацию одним действием."""
        await authority_lock(db, exclusive=True)
        await require_platform(db, actor)
        company = await db.get(
            ManagementCompany, company_id, with_for_update=True, populate_existing=True
        )
        if company is None:
            raise ResourceNotFound("Организация не найдена")
        now = datetime.now(UTC)
        join_url = None
        if enabled:
            if company.status != "active":
                raise AdministrationConflict("Организация приостановлена")
            code = secrets.token_urlsafe(24)
            company.open_registration_code_hash = self.auth.digest(code, "join")
            join_url = f"{self.base_url()}/join/{code}"
        else:
            company.open_registration_code_hash = None
            # Незавершённые регистрации (без второго фактора) закрываются сразу.
            await db.execute(
                update(EmployeeInvitation)
                .where(
                    EmployeeInvitation.company_id == company_id,
                    EmployeeInvitation.source == "open_registration",
                    EmployeeInvitation.status.in_(["pending", "claimed"]),
                )
                .values(status="revoked", revoked_at=now)
            )
        company.open_registration_enabled = enabled
        company.open_registration_changed_at = now
        company.open_registration_changed_by = actor
        audit(
            db,
            "open_registration.enabled" if enabled else "open_registration.closed",
            actor,
            company_id,
            reason,
        )
        await db.flush()
        return await self.open_registration(db, company_id, join_url=join_url)

    async def company_by_code(self, db: AsyncSession, code: str) -> ManagementCompany:
        company = await db.scalar(
            select(ManagementCompany)
            .where(ManagementCompany.open_registration_code_hash == self.auth.digest(code, "join"))
            .execution_options(populate_existing=True)
        )
        if company is None or not company.open_registration_enabled or company.status != "active":
            raise AuthenticationRequired("Регистрация по этой ссылке закрыта.")
        return company

    def join_invitation(self, company_id: UUID, user_id: UUID) -> EmployeeInvitation:
        """Приглашение-носитель открытой регистрации: сразу закреплено за новым аккаунтом."""
        now = datetime.now(UTC)
        return EmployeeInvitation(
            company_id=company_id,
            invited_by_user_id=None,
            organization_role="operator",
            source="open_registration",
            # Никто не знает эту ссылку: вход завершает только MFA этого аккаунта.
            token_hash=self.auth.digest(secrets.token_urlsafe(32), "invitation"),
            expires_at=now + timedelta(seconds=self.settings.employee_invitation_seconds),
            status="claimed",
            claimed_by_user_id=user_id,
            claimed_at=now,
        )

    # --- единый вход -----------------------------------------------------------------

    async def destinations(self, db: AsyncSession, actor: UUID) -> EmployeeDestinations:
        user = await db.get(User, actor)
        if user is None:
            raise AuthenticationRequired("Войдите в кабинет")
        rows = (
            await db.execute(
                select(ManagementCompany, OrganizationMembership.role)
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
        return EmployeeDestinations(
            platform=user.platform_role == "superadmin",
            companies=[
                CompanyDestination(company_id=c.id, name=c.name, role=cast(Role, role))
                for c, role in rows
            ],
        )
