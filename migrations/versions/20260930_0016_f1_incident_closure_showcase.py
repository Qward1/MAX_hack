"""incident closes with its ticket, showcase guard, LLM token limiter (F1)

Аддитивная миграция среза F1.

* `incidents`: проблема закрывается вместе с заявкой
  (INCIDENT-CLOSE-WITH-TICKET-2026-09-28): время закрытия, вид закрытия
  (`residents_confirmed` — жители подтвердили; `ticket_cancelled` — заявка
  отменена с причиной), служебная причина и время смены статуса. Значения
  статуса `resolved` / `dismissed` уже есть в контракте, поле строковое.
* `incident_events`: события проблемы — закрыта, снова открыта — со временем,
  заявкой и автором.
* `users.reviewer`, `management_companies.showcase`: проверочные аккаунты
  жюри и витрина (демо-УК), защищённые от разрушающих действий
  (SHOWCASE-GUARD-2026-09-29). Признаки задаёт штатный инструмент
  `domsignal.tools.showcase`.
* `ai_token_minutes`: общий на все процессы счётчик токенов модели по минутам
  (LLM-RATE-2026-09-29, ограничитель `LLM_TOKENS_PER_MINUTE`).

Откат отказывается, если проблемы уже закрывались.

Revision ID: 20260930_0016
Revises: 20260929_0015
Create Date: 2026-09-30 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0016"
down_revision: str | None = "20260929_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("incidents", sa.Column("closure", sa.String(30)))
    op.add_column("incidents", sa.Column("closure_reason", sa.Text()))
    op.add_column("incidents", sa.Column("status_changed_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "closure",
        "incidents",
        "closure IS NULL OR closure IN ('residents_confirmed', 'ticket_cancelled')",
    )
    op.create_index(
        "ix_incident_house_resolved",
        "incidents",
        ["house_id", "resolved_at"],
        postgresql_where=sa.text("resolved_at IS NOT NULL"),
    )
    op.create_table(
        "incident_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "incident_id",
            sa.Uuid(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(30)),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), sa.ForeignKey("tickets.id", ondelete="SET NULL")),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('resolved', 'closed_cancelled', 'reopened')",
            name="kind",
        ),
    )
    op.create_index(
        "ix_incident_events_incident", "incident_events", ["incident_id", "created_at"]
    )
    op.add_column(
        "users",
        sa.Column("reviewer", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "management_companies",
        sa.Column("showcase", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "ai_token_minutes",
        sa.Column("minute", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("tokens >= 0", name="tokens"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    closed = bind.scalar(sa.text("SELECT count(*) FROM incident_events"))
    if closed:
        raise RuntimeError("incidents were already closed with tickets; restore a pre-F1 backup")
    op.drop_table("ai_token_minutes")
    op.drop_column("management_companies", "showcase")
    op.drop_column("users", "reviewer")
    op.drop_index("ix_incident_events_incident", table_name="incident_events")
    op.drop_table("incident_events")
    op.drop_index("ix_incident_house_resolved", table_name="incidents")
    op.drop_constraint(op.f("ck_incidents_closure"), "incidents", type_="check")
    op.drop_column("incidents", "status_changed_at")
    op.drop_column("incidents", "closure_reason")
    op.drop_column("incidents", "closure")
    op.drop_column("incidents", "resolved_at")
