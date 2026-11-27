"""tax authority demands

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-27 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = (
    "'digest', 'reminder', 'overdue', 'client_marked_paid', 'fill_amount', "
    "'attachment', 'signature', 'broadcast'"
)


def _allow_types(types: str) -> None:
    name = op.f("ck_notifications_log_type")
    op.drop_constraint(name, "notifications_log", type_="check")
    op.create_check_constraint(name, "notifications_log", f"type IN ({types})")


def _text(name: str, length: int) -> sa.Column:
    return sa.Column(name, sa.String(length=length), server_default="", nullable=False)


def _flag(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean(), server_default="false", nullable=False)


def upgrade() -> None:
    op.create_table(
        "demands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        _text("knd", 7),
        _text("number", 64),
        sa.Column("doc_date", sa.Date(), nullable=False),
        sa.Column("sent_date", sa.Date(), nullable=False),
        sa.Column("receipt_date", sa.Date(), nullable=False),
        _flag("receipt_set"),
        sa.Column("response_workdays", sa.Integer(), nullable=True),
        sa.Column("response_date", sa.Date(), nullable=False),
        _flag("response_set"),
        sa.Column("amount_kopecks", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        _text("filename", 255),
        _text("content_type", 64),
        sa.Column("data", sa.LargeBinary(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount_kopecks >= 0", name=op.f("ck_demands_amount")),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], name=op.f("fk_demands_company_id_companies")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_demands_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demands")),
    )
    op.create_index(op.f("ix_demands_company_id"), "demands", ["company_id"])
    op.add_column("tasks", sa.Column("demand_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("demand_step", sa.String(length=16), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_demand_id_demands"),
        "tasks",
        "demands",
        ["demand_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_tasks_demand_step", "tasks", ["demand_id", "demand_step"])
    _allow_types(f"{TYPES}, 'demand'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications_log WHERE type = 'demand'")
    _allow_types(TYPES)
    # задачи требований удаляются вместе с ними
    op.execute("DELETE FROM tasks WHERE demand_id IS NOT NULL")
    op.drop_constraint("uq_tasks_demand_step", "tasks", type_="unique")
    op.drop_constraint(op.f("fk_tasks_demand_id_demands"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "demand_step")
    op.drop_column("tasks", "demand_id")
    op.drop_index(op.f("ix_demands_company_id"), table_name="demands")
    op.drop_table("demands")
