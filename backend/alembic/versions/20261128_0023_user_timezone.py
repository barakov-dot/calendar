"""часовой пояс для времени уведомлений у каждого пользователя

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_settings", sa.Column("timezone", sa.String(40)))


def downgrade() -> None:
    op.drop_column("notification_settings", "timezone")
