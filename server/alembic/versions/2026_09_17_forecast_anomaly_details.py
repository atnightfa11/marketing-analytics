"""add forecast anomaly details

Revision ID: 2026_09_17_anomaly_details
Revises: 2026_09_03_billing_lifecycle
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_09_17_anomaly_details"
down_revision = "2026_09_03_billing_lifecycle"
branch_labels = None
depends_on = None


def _columns(inspector) -> set[str]:
    return {column["name"] for column in inspector.get_columns("forecasts")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "forecasts" not in set(inspector.get_table_names()):
        return
    existing = _columns(inspector)
    for column in (
        sa.Column("anomaly_day", sa.Date(), nullable=True),
        sa.Column("anomaly_actual", sa.Float(), nullable=True),
        sa.Column("anomaly_expected", sa.Float(), nullable=True),
    ):
        if column.name not in existing:
            op.add_column("forecasts", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "forecasts" not in set(inspector.get_table_names()):
        return
    existing = _columns(inspector)
    for column_name in ("anomaly_expected", "anomaly_actual", "anomaly_day"):
        if column_name in existing:
            op.drop_column("forecasts", column_name)
