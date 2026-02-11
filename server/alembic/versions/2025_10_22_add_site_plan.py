"""add site plan table

Revision ID: 2025_10_22_add_site_plan
Revises: 2025_10_21_add_upload_token_jti
Create Date: 2025-10-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2025_10_22_add_site_plan"
down_revision = "2025_10_21_add_upload_token_jti"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_plan",
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("site_id"),
    )
    op.create_index("ix_site_plan_plan", "site_plan", ["plan"])
    op.create_index("ix_site_plan_stripe_customer_id", "site_plan", ["stripe_customer_id"])
    op.create_index("ix_site_plan_stripe_subscription_id", "site_plan", ["stripe_subscription_id"])


def downgrade():
    op.drop_index("ix_site_plan_stripe_subscription_id", table_name="site_plan")
    op.drop_index("ix_site_plan_stripe_customer_id", table_name="site_plan")
    op.drop_index("ix_site_plan_plan", table_name="site_plan")
    op.drop_table("site_plan")
