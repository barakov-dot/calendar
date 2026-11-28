"""несколько бухгалтеров и помощников у компании

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_staff",
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_company_staff_company_id_companies",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_company_staff_user_id_users"),
        sa.PrimaryKeyConstraint("company_id", "user_id", name="pk_company_staff"),
    )
    op.create_index("ix_company_staff_user_id", "company_staff", ["user_id"])
    op.execute(
        "INSERT INTO company_staff (company_id, user_id) "
        "SELECT id, accountant_id FROM companies WHERE accountant_id IS NOT NULL"
    )
    op.drop_column("companies", "accountant_id")


def downgrade() -> None:
    op.add_column("companies", sa.Column("accountant_id", sa.Integer(), nullable=True))
    # у компании остаётся один бухгалтер
    op.execute(
        "UPDATE companies SET accountant_id = (SELECT min(s.user_id) FROM company_staff s "
        "JOIN users u ON u.id = s.user_id "
        "WHERE s.company_id = companies.id AND u.role <> 'assistant')"
    )
    op.create_foreign_key(
        "fk_companies_accountant_id_users", "companies", "users", ["accountant_id"], ["id"]
    )
    op.create_index("ix_companies_accountant_id", "companies", ["accountant_id"])
    op.drop_index("ix_company_staff_user_id", table_name="company_staff")
    op.drop_table("company_staff")
