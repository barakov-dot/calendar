"""у решения о взыскании нет срока оплаты: деньги списывают со счёта

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("demands", "response_date", existing_type=sa.Date(), nullable=True)
    # уже загруженные решения: убираем задачу оплаты (с её напоминаниями) и срок
    op.execute(
        "DELETE FROM tasks WHERE demand_step = 'response' "
        "AND demand_id IN (SELECT id FROM demands WHERE knd = '1165001')"
    )
    op.execute(
        "UPDATE demands SET response_date = NULL, response_set = false, response_workdays = NULL "
        "WHERE knd = '1165001'"
    )


def downgrade() -> None:
    op.execute("UPDATE demands SET response_date = receipt_date WHERE response_date IS NULL")
    op.alter_column("demands", "response_date", existing_type=sa.Date(), nullable=False)
