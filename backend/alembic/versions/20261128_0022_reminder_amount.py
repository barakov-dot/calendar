"""сумма в повторяющемся напоминании

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recurring_reminders", sa.Column("amount_kopecks", sa.BigInteger()))


def downgrade() -> None:
    op.drop_column("recurring_reminders", "amount_kopecks")
