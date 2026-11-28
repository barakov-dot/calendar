"""rosstat forms

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-28 08:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _string(name: str, length: int) -> sa.Column:
    return sa.Column(name, sa.String(length=length), server_default="", nullable=False)


def _long(name: str) -> sa.Column:
    return sa.Column(name, sa.Text(), server_default="", nullable=False)


def upgrade() -> None:
    op.create_table(
        "rosstat_forms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        _string("index", 64),
        _long("name"),
        _string("okud", 32),
        _string("periodicity", 100),
        _string("period", 200),
        _string("deadline", 200),
        sa.Column("due_date", sa.Date(), nullable=True),
        _long("comment"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_rosstat_forms_company_id_companies")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rosstat_forms")),
        sa.UniqueConstraint("company_id", "key", name="uq_rosstat_forms_key"),
    )
    op.create_index(op.f("ix_rosstat_forms_company_id"), "rosstat_forms", ["company_id"])
    op.add_column("tasks", sa.Column("rosstat_form_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_rosstat_form_id_rosstat_forms"),
        "tasks",
        "rosstat_forms",
        ["rosstat_form_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(op.f("uq_tasks_rosstat_form_id"), "tasks", ["rosstat_form_id"])
    op.add_column(
        "companies", sa.Column("rosstat_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("companies", _long("rosstat_error"))
    op.add_column("companies", _string("rosstat_okpo", 14))


def downgrade() -> None:
    for name in ("rosstat_okpo", "rosstat_error", "rosstat_checked_at"):
        op.drop_column("companies", name)
    op.execute("DELETE FROM tasks WHERE rosstat_form_id IS NOT NULL")
    op.drop_constraint(op.f("uq_tasks_rosstat_form_id"), "tasks", type_="unique")
    op.drop_constraint(op.f("fk_tasks_rosstat_form_id_rosstat_forms"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "rosstat_form_id")
    op.drop_index(op.f("ix_rosstat_forms_company_id"), table_name="rosstat_forms")
    op.drop_table("rosstat_forms")
