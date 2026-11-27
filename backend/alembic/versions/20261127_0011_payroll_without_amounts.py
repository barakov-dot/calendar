"""payroll payments no longer need an amount

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-27 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CODES = (
    "ndfl_payment",
    "ndfl_end_payment",
    "ndfl_december",
    "insurance_payment",
    "injury_contrib",
    "ausn_injury",
)


def _set(value: str) -> None:
    codes = ", ".join(f"'{code}'" for code in CODES)
    op.execute(f"UPDATE tasks SET needs_amount = {value} WHERE rule_code IN ({codes})")


def upgrade() -> None:
    # и прошедшие задачи: генерация их уже не пересматривает
    _set("false")


def downgrade() -> None:
    _set("true")
