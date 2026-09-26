"""Administrative requests are proposals, never access grants."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from domsignal.db.base import Base
from domsignal.db.models.access import Timestamps

REVIEW_STATUSES = "'submitted','under_review','needs_info','approved','rejected','cancelled'"


class ReviewFields(Timestamps):
    status: Mapped[str] = mapped_column(String(30), default="submitted")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(String(2000))


class CompanyOnboardingRequest(ReviewFields, Base):
    """Заявка УК. D2: каждая отправка — своя заявка со своей ссылкой статуса.

    Повтор ИНН больше не сливается с прежней заявкой: иначе ответ «уже подано»
    или общая ссылка статуса раскрывали бы чужую заявку. Совпадение ИНН видит
    только платформа (`inn_conflict`), одобрение второй УК с тем же ИНН
    по-прежнему невозможно.
    """

    __tablename__ = "company_onboarding_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({REVIEW_STATUSES})", name="status"),
        CheckConstraint(
            "requested_chat_count IS NULL OR requested_chat_count BETWEEN 1 AND 1000",
            name="requested_chat_count",
        ),
        Index("ix_company_onboarding_requests_inn", "inn"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    legal_name: Mapped[str] = mapped_column(String(300))
    short_name: Mapped[str] = mapped_column(String(200))
    inn: Mapped[str] = mapped_column(String(12))
    contact_name: Mapped[str] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(String(2000))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("management_companies.id"), unique=True
    )
    #: Сколько домовых чатов УК хочет подключить (D2). У заявок до D2 — пусто.
    requested_chat_count: Mapped[int | None] = mapped_column(Integer)
    #: Необязательный список адресов домов, строки как ввёл заявитель.
    house_addresses: Mapped[list[str] | None] = mapped_column(JSONB)
    contact_position: Mapped[str | None] = mapped_column(String(200))
    #: Хэш секретной ссылки на страницу статуса; сама ссылка показывается один раз.
    status_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    #: Поколение ссылки «Создать аккаунт администратора» со страницы статуса:
    #: истёкшее или отозванное приглашение заменяется следующим поколением.
    admin_invite_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: Хэш одноразового кода `ca_…` для ссылки на бота «Получать уведомления в MAX».
    notify_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    #: Кому бот пишет о смене статуса заявки (тот, кто открыл бота по коду).
    notify_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class CompanyApplicationMessage(Base):
    """Вопрос платформы или ответ заявителя по заявке УК (без вложений)."""

    __tablename__ = "company_application_messages"
    __table_args__ = (CheckConstraint("author IN ('platform','applicant')", name="author"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("company_onboarding_requests.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


#: Как появилось приглашение: администратор УК, открытая регистрация (D2) или
#: страница статуса заявки (первый администратор, D2).
INVITATION_SOURCES = "'invitation','open_registration','application_status'"


class EmployeeInvitation(Timestamps, Base):
    __tablename__ = "employee_invitations"
    __table_args__ = (
        CheckConstraint("organization_role IN ('operator','company_admin')", name="role"),
        CheckConstraint(
            "status IN ('pending','claimed','accepted','expired','revoked')", name="status"
        ),
        CheckConstraint(f"source IN ({INVITATION_SOURCES})", name="source"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("management_companies.id"), index=True)
    source: Mapped[str] = mapped_column(
        String(30), default="invitation", server_default="invitation"
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    organization_role: Mapped[str] = mapped_column(String(30))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HouseManagementRequest(ReviewFields, Base):
    __tablename__ = "house_management_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({REVIEW_STATUSES})", name="status"),
        # D5: адрес из заявки УК переносится в заявку на дом один раз.
        Index(
            "uq_house_requests_application_address",
            "source_application_id",
            "normalized_address",
            unique=True,
            postgresql_where=text("source_application_id IS NOT NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("management_companies.id"), index=True)
    requested_address: Mapped[str] = mapped_column(String(500))
    normalized_address: Mapped[str] = mapped_column(String(500), index=True)
    requested_valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    basis_text: Mapped[str] = mapped_column(String(2000))
    candidate_house_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("houses.id"))
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    management_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("house_managements.id"), unique=True
    )
    # D5: заявка создана из адресов одобренной заявки УК (дома пачкой).
    source_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("company_onboarding_requests.id")
    )


class EmployeeCredentialReset(Base):
    """Одноразовая ссылка сброса пароля/MFA, выданная администратором УК (D2).

    В базе — только хэш ссылки. Выдача сразу отзывает сессии сотрудника и
    закрывает вход прежним паролем; ссылка задаёт новый пароль (и, для
    `password_mfa`, заново подключает аутентификатор).
    """

    __tablename__ = "employee_credential_resets"
    __table_args__ = (
        CheckConstraint("kind IN ('password','password_mfa')", name="kind"),
        CheckConstraint("status IN ('pending','used','revoked')", name="status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("management_companies.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
