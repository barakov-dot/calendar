"""user name override and broadcasts

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TYPES = (
    "'digest', 'reminder', 'overdue', 'client_marked_paid', 'fill_amount', "
    "'attachment', 'signature'"
)
KEY = ["user_id", "task_id", "type", "scheduled_for"]


def _allow_types(types: str) -> None:
    name = op.f("ck_notifications_log_type")
    op.drop_constraint(name, "notifications_log", type_="check")
    op.create_check_constraint(name, "notifications_log", f"type IN ({types})")


def _unique(columns: list[str]) -> None:
    op.drop_constraint("uq_notifications_log_key", "notifications_log", type_="unique")
    op.create_unique_constraint(
        "uq_notifications_log_key",
        "notifications_log",
        columns,
        postgresql_nulls_not_distinct=True,
    )


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("name_overridden", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String(length=16)), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_broadcasts_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broadcasts")),
    )
    op.add_column("notifications_log", sa.Column("broadcast_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_notifications_log_broadcast_id_broadcasts"),
        "notifications_log",
        "broadcasts",
        ["broadcast_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_notifications_log_broadcast_id"), "notifications_log", ["broadcast_id"]
    )
    _unique([*KEY, "broadcast_id"])
    _allow_types(f"{TYPES}, 'broadcast'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications_log WHERE type = 'broadcast'")
    _allow_types(TYPES)
    _unique(KEY)
    op.drop_index(op.f("ix_notifications_log_broadcast_id"), "notifications_log")
    op.drop_constraint(
        op.f("fk_notifications_log_broadcast_id_broadcasts"),
        "notifications_log",
        type_="foreignkey",
    )
    op.drop_column("notifications_log", "broadcast_id")
    op.drop_table("broadcasts")
    op.drop_column("users", "name_overridden")
