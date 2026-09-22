"""route outcome author and the words a resident submitted through the form

Аддитивная миграция экрана карточки маршрута. Оба столбца допускают NULL,
существующие исходы не переписываются и ни одна запись не удаляется: у
исходов, созданных до этой миграции, автор и текст формы остаются пустыми.

Revision ID: 20260920_0007
Revises: 20260920_0006
Create Date: 2026-09-20 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0007"
down_revision: str | None = "20260920_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Исход маршрутизации — ответ конкретному жителю: карточку по ссылке
    # `r_…` и по `?card=` видит только её автор.
    op.add_column("route_outcomes", sa.Column("author_id", sa.Uuid(), nullable=True))
    # Слова жителя из формы. У чатового пути текст остаётся в `explicit_intakes`,
    # поэтому оба источника черновика существуют независимо.
    op.add_column("route_outcomes", sa.Column("submitted_text", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_route_outcomes_author_id_users"),
        "route_outcomes",
        "users",
        ["author_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_route_outcomes_author_id_users"), "route_outcomes", type_="foreignkey"
    )
    op.drop_column("route_outcomes", "submitted_text")
    op.drop_column("route_outcomes", "author_id")
