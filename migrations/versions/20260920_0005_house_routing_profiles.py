"""house routing profiles for the responsibility router

Revision ID: 20260920_0005
Revises: e107a3cff433
Create Date: 2026-09-20 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0005"
down_revision: str | None = "e107a3cff433"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "house_routing_profiles",
        sa.Column("house_id", sa.Uuid(), nullable=False),
        sa.Column("region_code", sa.String(length=20), nullable=True),
        sa.Column("municipality_code", sa.String(length=60), nullable=True),
        sa.Column(
            "territory_policy",
            sa.String(length=20),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "territory_policy IN ('uk', 'municipal', 'mixed', 'unknown')",
            name=op.f("ck_house_routing_profiles_territory_policy"),
        ),
        sa.ForeignKeyConstraint(
            ["house_id"],
            ["houses.id"],
            name=op.f("fk_house_routing_profiles_house_id_houses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_house_routing_profiles_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("house_id", name=op.f("pk_house_routing_profiles")),
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM house_routing_profiles)")
    ).scalar():
        raise RuntimeError(
            "House routing profiles retained; restore a pre-routing backup before downgrade"
        )
    op.drop_table("house_routing_profiles")
