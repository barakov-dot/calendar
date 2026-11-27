"""IP registration date

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-27 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("registration_date", sa.Date(), nullable=True))
    # у уже добавленных через DaData ИП дата есть в сохранённом ответе (миллисекунды)
    op.execute(
        """
        UPDATE companies SET registration_date =
            (to_timestamp((dadata_raw #>> '{data,state,registration_date}')::bigint / 1000)
                AT TIME ZONE 'Europe/Moscow')::date
        WHERE entity_type = 'ip'
          AND dadata_raw #>> '{data,state,registration_date}' ~ '^[0-9]+$'
        """
    )


def downgrade() -> None:
    op.drop_column("companies", "registration_date")
