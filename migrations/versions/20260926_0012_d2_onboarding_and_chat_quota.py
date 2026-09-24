"""company onboarding without manual links, chat quota, credential resets (D2)

Аддитивная миграция среза D2.

* `company_onboarding_requests`: сколько чатов УК хочет подключить, адреса
  домов, должность контакта, хэш ссылки статуса и поколение ссылки
  «Создать аккаунт администратора». Частичный уникальный индекс «одна
  открытая заявка на ИНН» заменён обычным индексом: каждая отправка — своя
  заявка со своей ссылкой статуса (совпадение ИНН видит платформа).
* `company_application_messages`: вопросы платформы и ответы заявителя.
* `employee_invitations.source`: приглашение, открытая регистрация или
  страница статуса заявки.
* `management_companies`: открытая регистрация сотрудников (флаг, хэш кода).
* `chat_quota_requests`, `chat_quota_grants` (CHAT-QUOTA-2026-09-26); каждой
  существующей УК — запись `migration` «без ограничения», чтобы ничего не
  сломать.
* `employee_credential_resets`: одноразовые ссылки сброса пароля/MFA.

Revision ID: 20260926_0012
Revises: 20260925_0011
Create Date: 2026-09-26 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260926_0012"
down_revision: str | None = "20260925_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MIGRATION_REASON = "Квота до среза D2: без ограничения. Суперадмин может задать её позже."


def upgrade() -> None:
    # --- заявка УК
    op.add_column("company_onboarding_requests", sa.Column("requested_chat_count", sa.Integer()))
    op.add_column(
        "company_onboarding_requests",
        sa.Column("house_addresses", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("company_onboarding_requests", sa.Column("contact_position", sa.String(200)))
    op.add_column("company_onboarding_requests", sa.Column("status_token_hash", sa.String(64)))
    op.add_column(
        "company_onboarding_requests",
        sa.Column("admin_invite_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_unique_constraint(
        "uq_company_onboarding_requests_status_token_hash",
        "company_onboarding_requests",
        ["status_token_hash"],
    )
    op.create_check_constraint(
        "requested_chat_count",
        "company_onboarding_requests",
        sa.text("requested_chat_count IS NULL OR requested_chat_count BETWEEN 1 AND 1000"),
    )
    op.drop_index("uq_company_application_open_inn", table_name="company_onboarding_requests")
    op.create_index("ix_company_onboarding_requests_inn", "company_onboarding_requests", ["inn"])

    op.create_table(
        "company_application_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("author", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "author IN ('platform','applicant')",
            name=op.f("ck_company_application_messages_author"),
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["company_onboarding_requests.id"],
            name="fk_company_application_messages_application_id_company__276a",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_company_application_messages_actor_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_company_application_messages"),
    )
    op.create_index(
        "ix_company_application_messages_application_id",
        "company_application_messages",
        ["application_id"],
    )

    # --- приглашения
    op.add_column(
        "employee_invitations",
        sa.Column("source", sa.String(30), server_default="invitation", nullable=False),
    )
    op.create_check_constraint(
        "source",
        "employee_invitations",
        sa.text("source IN ('invitation','open_registration','application_status')"),
    )

    # --- открытая регистрация сотрудников
    op.add_column(
        "management_companies",
        sa.Column(
            "open_registration_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.add_column("management_companies", sa.Column("open_registration_code_hash", sa.String(64)))
    op.add_column(
        "management_companies",
        sa.Column("open_registration_changed_at", sa.DateTime(timezone=True)),
    )
    op.add_column("management_companies", sa.Column("open_registration_changed_by", sa.Uuid()))
    op.create_unique_constraint(
        "uq_management_companies_open_registration_code_hash",
        "management_companies",
        ["open_registration_code_hash"],
    )
    op.create_foreign_key(
        "fk_management_companies_open_registration_changed_by_users",
        "management_companies",
        "users",
        ["open_registration_changed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- квота чатов
    op.create_table(
        "chat_quota_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("requested_delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("granted_delta", sa.Integer()),
        sa.Column("decided_by", sa.Uuid()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_reason", sa.String(2000)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','partially_approved','rejected','cancelled')",
            name=op.f("ck_chat_quota_requests_status"),
        ),
        sa.CheckConstraint(
            "requested_delta BETWEEN 1 AND 1000",
            name=op.f("ck_chat_quota_requests_requested_delta"),
        ),
        sa.CheckConstraint(
            "granted_delta IS NULL OR (granted_delta >= 0 AND granted_delta <= requested_delta)",
            name=op.f("ck_chat_quota_requests_granted_delta"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["management_companies.id"],
            name="fk_chat_quota_requests_company_id_management_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["users.id"], name="fk_chat_quota_requests_requested_by_users"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name="fk_chat_quota_requests_decided_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_quota_requests"),
    )
    op.create_index("ix_chat_quota_requests_company_id", "chat_quota_requests", ["company_id"])
    op.create_index(
        "uq_chat_quota_request_pending",
        "chat_quota_requests",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "chat_quota_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("limit_after", sa.Integer()),
        sa.Column("delta", sa.Integer()),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("application_id", sa.Uuid()),
        sa.Column("request_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('initial','expansion','adjustment','migration')",
            name=op.f("ck_chat_quota_grants_kind"),
        ),
        sa.CheckConstraint(
            "limit_after IS NULL OR limit_after >= 0", name=op.f("ck_chat_quota_grants_limit_after")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["management_companies.id"],
            name="fk_chat_quota_grants_company_id_management_companies",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_chat_quota_grants_actor_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["application_id"],
            ["company_onboarding_requests.id"],
            name="fk_chat_quota_grants_application_id_company_onboarding_requests",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["chat_quota_requests.id"],
            name="fk_chat_quota_grants_request_id_chat_quota_requests",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_quota_grants"),
        sa.UniqueConstraint("seq", name="uq_chat_quota_grants_seq"),
    )
    op.create_index("ix_chat_quota_grants_company_id", "chat_quota_grants", ["company_id"])
    # Прежние УК: явная запись «без ограничения» — квота вводится без отключений.
    op.execute(
        sa.text(
            "INSERT INTO chat_quota_grants (id, company_id, kind, limit_after, delta, reason) "
            "SELECT gen_random_uuid(), id, 'migration', NULL, NULL, :reason "
            "FROM management_companies ORDER BY created_at, id"
        ).bindparams(reason=_MIGRATION_REASON)
    )

    # --- сброс пароля/MFA
    op.create_table(
        "employee_credential_resets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('password','password_mfa')", name=op.f("ck_employee_credential_resets_kind")
        ),
        sa.CheckConstraint(
            "status IN ('pending','used','revoked')",
            name=op.f("ck_employee_credential_resets_status"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["management_companies.id"],
            name="fk_employee_credential_resets_company_id_management_companies",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_employee_credential_resets_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_employee_credential_resets_created_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_employee_credential_resets"),
        sa.UniqueConstraint("token_hash", name="uq_employee_credential_resets_token_hash"),
    )
    op.create_index(
        "ix_employee_credential_resets_company_id", "employee_credential_resets", ["company_id"]
    )
    op.create_index(
        "ix_employee_credential_resets_user_id", "employee_credential_resets", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("employee_credential_resets")
    op.drop_table("chat_quota_grants")
    op.drop_table("chat_quota_requests")

    op.drop_constraint(
        "fk_management_companies_open_registration_changed_by_users",
        "management_companies",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_management_companies_open_registration_code_hash", "management_companies"
    )
    for column in (
        "open_registration_changed_by",
        "open_registration_changed_at",
        "open_registration_code_hash",
        "open_registration_enabled",
    ):
        op.drop_column("management_companies", column)

    op.drop_constraint("ck_employee_invitations_source", "employee_invitations")
    op.drop_column("employee_invitations", "source")

    op.drop_table("company_application_messages")
    op.drop_index("ix_company_onboarding_requests_inn", table_name="company_onboarding_requests")
    # Прежняя уникальность вернётся, только если открытых дублей ИНН нет; иначе
    # откат остановится, а не удалит чужие заявки.
    op.create_index(
        "uq_company_application_open_inn",
        "company_onboarding_requests",
        ["inn"],
        unique=True,
        postgresql_where=sa.text("status IN ('submitted','under_review','needs_info')"),
    )
    op.drop_constraint(
        "ck_company_onboarding_requests_requested_chat_count", "company_onboarding_requests"
    )
    op.drop_constraint(
        "uq_company_onboarding_requests_status_token_hash", "company_onboarding_requests"
    )
    for column in (
        "admin_invite_generation",
        "status_token_hash",
        "contact_position",
        "house_addresses",
        "requested_chat_count",
    ):
        op.drop_column("company_onboarding_requests", column)
