"""house council and residents' proposals (D4)

Аддитивная миграция среза D4.

* `house_council_members`: житель дома в совете дома — отмечает и снимает
  администратор УК; одна активная запись на жителя и дом.
* `house_proposals`: «Предложить вопрос» — тема жителя; статус и опрос, в
  который её превратили.
* `broadcasts`: новый источник `council` — объявления и опросы совета дома тем
  же механизмом D3; у него, как у УК, есть `tenant_id` (УК дома).

Откат отказывается, если совет, предложения или сообщения совета уже есть.

Revision ID: 20260928_0014
Revises: 20260927_0013
Create Date: 2026-09-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260928_0014"
down_revision: str | None = "20260927_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, table: str, condition: str) -> None:
    # D3 создала ограничения с двойным префиксом (`ck_broadcasts_ck_broadcasts_origin`):
    # убираем любое из двух имён и создаём по соглашению об именах.
    for existing in (f"ck_{table}_ck_{table}_{name}", f"ck_{table}_{name}"):
        op.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {existing}"))
    op.create_check_constraint(name, table, sa.text(condition))


def upgrade() -> None:
    op.create_table(
        "house_council_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("houses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active','revoked')", name="status"),
    )
    op.create_index(
        "ix_house_council_members_house_id", "house_council_members", ["house_id"]
    )
    op.create_index(
        "uq_house_council_member_active",
        "house_council_members",
        ["house_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "house_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "house_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("houses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column(
            "broadcast_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("broadcasts.id", ondelete="SET NULL"),
        ),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('new','converted')", name="status"),
        sa.CheckConstraint("char_length(text) BETWEEN 3 AND 1000", name="text_length"),
    )
    op.create_index("ix_house_proposals_author_id", "house_proposals", ["author_id"])
    op.create_index(
        "ix_house_proposals_house_created", "house_proposals", ["house_id", "created_at"]
    )
    _check("origin", "broadcasts", "origin IN ('company','platform','council')")
    _check(
        "origin_tenant", "broadcasts", "(origin IN ('company','council')) = (tenant_id IS NOT NULL)"
    )


def downgrade() -> None:
    retained = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM house_council_members) "
                "OR EXISTS (SELECT 1 FROM house_proposals) "
                "OR EXISTS (SELECT 1 FROM broadcasts WHERE origin = 'council')"
            )
        )
        .scalar()
    )
    if retained:
        raise RuntimeError(
            "House council, proposals or council messages are retained; "
            "restore a pre-D4 backup before downgrade"
        )
    _check("origin_tenant", "broadcasts", "(origin = 'company') = (tenant_id IS NOT NULL)")
    _check("origin", "broadcasts", "origin IN ('company','platform')")
    op.drop_table("house_proposals")
    op.drop_table("house_council_members")
