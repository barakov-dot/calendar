"""рассылки по организациям и архив рассылок

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("broadcasts", sa.Column("archived_at", sa.DateTime(timezone=True)))
    for name, kind in (("company_ids", sa.Integer()), ("company_groups", sa.String(16))):
        op.add_column(
            "broadcasts",
            sa.Column(name, postgresql.ARRAY(kind), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    for name in ("company_groups", "company_ids", "archived_at"):
        op.drop_column("broadcasts", name)
