"""queue indexes and houses from a company application (D5)

Аддитивная миграция среза D5.

* `jobs`: частичный индекс выборки задачи по пулу, приоритету и времени
  (`ix_jobs_claim_pool`) — выборка не просматривает выполненные задачи;
  частичный индекс по времени завершения для периодической очистки
  (`ix_jobs_done_completed`). Прежний `ix_jobs_claim` остаётся.
* `house_management_requests.source_application_id`: заявка на дом, созданная
  из адресов одобренной заявки УК (дома пачкой, аудит Р-1). Уникальность
  «заявка УК + адрес» делает перенос адресов идемпотентным.

Откат отказывается, если заявки на дома из заявок УК уже есть.

Revision ID: 20260929_0015
Revises: 20260928_0014
Create Date: 2026-09-29 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0015"
down_revision: str | None = "20260928_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_jobs_claim_pool",
        "jobs",
        [sa.text("starts_with(kind, 'ai.')"), "priority", "created_at"],
        postgresql_where=sa.text("status IN ('pending', 'leased')"),
    )
    op.create_index(
        "ix_jobs_done_completed",
        "jobs",
        ["status", "completed_at"],
        postgresql_where=sa.text("status IN ('succeeded', 'failed')"),
    )
    op.add_column(
        "house_management_requests",
        sa.Column(
            "source_application_id",
            sa.Uuid(),
            sa.ForeignKey("company_onboarding_requests.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_house_requests_application_address",
        "house_management_requests",
        ["source_application_id", "normalized_address"],
        unique=True,
        postgresql_where=sa.text("source_application_id IS NOT NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    imported = bind.scalar(
        sa.text(
            "SELECT count(*) FROM house_management_requests WHERE source_application_id IS NOT NULL"
        )
    )
    if imported:
        raise RuntimeError(
            "house requests created from company applications exist; restore a pre-D5 backup"
        )
    op.drop_index("uq_house_requests_application_address", table_name="house_management_requests")
    op.drop_column("house_management_requests", "source_application_id")
    op.drop_index("ix_jobs_done_completed", table_name="jobs")
    op.drop_index("ix_jobs_claim_pool", table_name="jobs")
