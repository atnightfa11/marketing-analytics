"""add site anomaly alert settings

Revision ID: 2026_06_17_site_alert_settings
Revises: 2026_06_17_forecast_trained_at
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_17_site_alert_settings"
down_revision = "2026_06_17_forecast_trained_at"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "site_alert_settings"):
        op.create_table(
            "site_alert_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("anomaly_alerts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("slack_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("slack_webhook_url", sa.String(length=2048), nullable=True),
            sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("email_recipients", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column("updated_by", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("site_id", name="uq_site_alert_settings_site"),
        )
        op.create_index("ix_site_alert_settings_site", "site_alert_settings", ["site_id"])

    if not _has_table(inspector, "site_alert_deliveries"):
        op.create_table(
            "site_alert_deliveries",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("metric", sa.String(length=64), nullable=False),
            sa.Column("channel", sa.String(length=32), nullable=False),
            sa.Column("anomaly_key", sa.String(length=128), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("site_id", "metric", "channel", "anomaly_key", name="uq_site_alert_delivery"),
        )
        op.create_index("ix_site_alert_deliveries_site_sent", "site_alert_deliveries", ["site_id", "sent_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "site_alert_deliveries"):
        op.drop_index("ix_site_alert_deliveries_site_sent", table_name="site_alert_deliveries")
        op.drop_table("site_alert_deliveries")

    if _has_table(inspector, "site_alert_settings"):
        op.drop_index("ix_site_alert_settings_site", table_name="site_alert_settings")
        op.drop_table("site_alert_settings")
