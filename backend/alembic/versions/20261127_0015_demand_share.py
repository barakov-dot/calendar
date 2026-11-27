"""sending a demand to chosen people

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-27 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = (
    "'digest', 'reminder', 'overdue', 'client_marked_paid', 'fill_amount', "
    "'attachment', 'signature', 'broadcast', 'demand'"
)


def _allow_types(types: str) -> None:
    name = op.f("ck_notifications_log_type")
    op.drop_constraint(name, "notifications_log", type_="check")
    op.create_check_constraint(name, "notifications_log", f"type IN ({types})")


def upgrade() -> None:
    op.add_column(
        "notifications_log", sa.Column("note", sa.Text(), server_default="", nullable=False)
    )
    _allow_types(f"{TYPES}, 'demand_share'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications_log WHERE type = 'demand_share'")
    _allow_types(TYPES)
    op.drop_column("notifications_log", "note")
