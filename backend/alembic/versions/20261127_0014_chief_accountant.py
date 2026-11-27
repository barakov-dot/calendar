"""chief accountant role

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-27 17:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (таблица, имя ограничения, столбец, значения без главного бухгалтера)
CHECKS = (
    ("users", "ck_users_role", "role", "'admin', 'accountant', 'assistant', 'client'"),
    ("invites", "ck_invites_kind", "kind", "'accountant', 'assistant', 'client'"),
    (
        "tasks",
        "ck_tasks_changed_by_role",
        "status_changed_by_role",
        "'accountant', 'admin', 'client', 'system'",
    ),
)


def _set(table: str, name: str, column: str, values: str) -> None:
    op.drop_constraint(op.f(name), table, type_="check")
    op.create_check_constraint(op.f(name), table, f"{column} IN ({values})")


def upgrade() -> None:
    for table, name, column, values in CHECKS:
        _set(table, name, column, f"{values}, 'chief'")


def downgrade() -> None:
    # главные бухгалтеры становятся обычными: их компании не теряются
    op.execute("UPDATE users SET role = 'accountant' WHERE role = 'chief'")
    op.execute("DELETE FROM invites WHERE kind = 'chief'")
    op.execute(
        "UPDATE tasks SET status_changed_by_role = 'accountant' "
        "WHERE status_changed_by_role = 'chief'"
    )
    for table, name, column, values in CHECKS:
        _set(table, name, column, values)
