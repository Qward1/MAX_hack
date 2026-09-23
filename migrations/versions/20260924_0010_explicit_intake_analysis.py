"""explicit intake analysis: provenance of every /report analysis

Аддитивная миграция P7b. `explicit_intakes.analysis` — провенанс разбора
реплики `/report` для любого исхода: заявка, внешний маршрут, уточнение или
пропуск. Раньше провенанс жил только в `reports.analysis`, и у внешнего
маршрута (заявки нет) задержка, токены и стоимость модели терялись. Текста
реплики в провенансе нет. Прежние строки остаются без провенанса.

Revision ID: 20260924_0010
Revises: 20260923_0009
Create Date: 2026-09-24 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260924_0010"
down_revision: str | None = "20260923_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "explicit_intakes",
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    retained = (
        op.get_bind()
        .execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM explicit_intakes WHERE analysis IS NOT NULL)")
        )
        .scalar()
    )
    if retained:
        raise RuntimeError(
            "Explicit report analysis provenance is retained; "
            "restore a pre-P7b backup before downgrade"
        )
    op.drop_column("explicit_intakes", "analysis")
