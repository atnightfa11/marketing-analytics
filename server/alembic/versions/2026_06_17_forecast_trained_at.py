"""add trained_at freshness column to forecasts

Revision ID: 2026_06_17_forecast_trained_at
Revises: 2026_06_17_site_ip_blocks
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_17_forecast_trained_at"
down_revision = "2026_06_17_site_ip_blocks"
branch_labels = None
depends_on = None


COLUMN_NAME = "trained_at"


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_column(inspector, "forecasts", COLUMN_NAME):
        with op.batch_alter_table("forecasts") as batch_op:
            batch_op.add_column(sa.Column(COLUMN_NAME, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_column(inspector, "forecasts", COLUMN_NAME):
        with op.batch_alter_table("forecasts") as batch_op:
            batch_op.drop_column(COLUMN_NAME)
