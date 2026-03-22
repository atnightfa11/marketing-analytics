"""add site api keys for sdk bootstrap

Revision ID: 2026_03_18_add_site_api_keys
Revises: 2026_02_13_tier_rollout_raw_reports
Create Date: 2026-03-18 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_03_18_add_site_api_keys"
down_revision = "2026_02_13_tier_rollout_raw_reports"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "site_api_keys" in inspector.get_table_names():
        return

    op.create_table(
        "site_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("allowed_origin_pattern", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_site_api_keys_site_active", "site_api_keys", ["site_id", "is_active"])
    op.create_index("ix_site_api_keys_key_id", "site_api_keys", ["key_id"], unique=True)
    op.create_index("ix_site_api_keys_key_prefix", "site_api_keys", ["key_prefix"])


def downgrade():
    op.drop_index("ix_site_api_keys_key_prefix", table_name="site_api_keys")
    op.drop_index("ix_site_api_keys_key_id", table_name="site_api_keys")
    op.drop_index("ix_site_api_keys_site_active", table_name="site_api_keys")
    op.drop_table("site_api_keys")
