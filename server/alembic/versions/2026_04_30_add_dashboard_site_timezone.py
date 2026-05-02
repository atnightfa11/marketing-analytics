"""add dashboard site timezone

Revision ID: 2026_04_30_site_tz
Revises: 2026_04_23_add_dashboard_signup_tables
Create Date: 2026-04-30
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_04_30_site_tz"
down_revision = "2026_04_23_add_dashboard_signup_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "dashboard_sites",
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
    )


def downgrade() -> None:
    op.drop_column("dashboard_sites", "timezone")
