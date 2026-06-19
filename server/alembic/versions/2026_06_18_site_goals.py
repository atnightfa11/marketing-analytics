"""add persisted site goals

Revision ID: 2026_06_18_site_goals
Revises: 2026_06_17_site_alert_settings
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_18_site_goals"
down_revision = "2026_06_17_site_alert_settings"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "site_goals"):
        op.create_table(
            "site_goals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("metric", sa.String(length=64), nullable=False),
            sa.Column("target", sa.Float(), nullable=False),
            sa.Column("period_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("repeat", sa.String(length=32), nullable=False, server_default="monthly"),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("site_id", "metric", name="uq_site_goals_site_metric"),
        )
        op.create_index("ix_site_goals_site", "site_goals", ["site_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "site_goals"):
        op.drop_index("ix_site_goals_site", table_name="site_goals")
        op.drop_table("site_goals")
