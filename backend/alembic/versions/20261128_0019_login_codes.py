"""sign-in by a code sent by the bot

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-28 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIME = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("users", sa.Column("login", sa.String(length=32), nullable=True))
    op.create_unique_constraint(op.f("uq_users_login"), "users", ["login"])
    op.create_table(
        "login_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("login_key", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", TIME, nullable=False),
        sa.Column("consumed_at", TIME, nullable=True),
        sa.Column("created_at", TIME, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_login_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_codes")),
        sa.UniqueConstraint("request_id", name=op.f("uq_login_codes_request_id")),
    )
    op.create_index(op.f("ix_login_codes_login_key"), "login_codes", ["login_key"])
    op.create_index(op.f("ix_login_codes_created_at"), "login_codes", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_login_codes_created_at"), table_name="login_codes")
    op.drop_index(op.f("ix_login_codes_login_key"), table_name="login_codes")
    op.drop_table("login_codes")
    op.drop_constraint(op.f("uq_users_login"), "users", type_="unique")
    op.drop_column("users", "login")
