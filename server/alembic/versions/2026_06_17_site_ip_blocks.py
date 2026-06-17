"""add site ip block list

Revision ID: 2026_06_17_site_ip_blocks
Revises: 2026_06_16_commercial_readiness
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_17_site_ip_blocks"
down_revision = "2026_06_16_commercial_readiness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_ip_blocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("cidr", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "cidr", name="uq_site_ip_blocks_site_cidr"),
    )
    op.create_index("ix_site_ip_blocks_site", "site_ip_blocks", ["site_id"])


def downgrade() -> None:
    op.drop_index("ix_site_ip_blocks_site", table_name="site_ip_blocks")
    op.drop_table("site_ip_blocks")
