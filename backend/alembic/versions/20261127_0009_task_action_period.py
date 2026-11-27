"""task action title and period label

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-27 08:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("action_title", "period_label")


def upgrade() -> None:
    # заполняются ближайшей генерацией задач (при запуске worker)
    for name in COLUMNS:
        op.add_column(
            "tasks", sa.Column(name, sa.String(length=200), server_default="", nullable=False)
        )


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("tasks", name)
