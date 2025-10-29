"""initial schema

Revision ID: 2025_10_20_initial
Revises:
Create Date: 2024-10-20 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2025_10_20_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create ldp_reports table using raw SQL to handle partitioning properly
    op.execute(
        """
        CREATE TABLE ldp_reports (
            id INTEGER GENERATED ALWAYS AS IDENTITY,
            site_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            day DATE NOT NULL,
            payload JSONB NOT NULL,
            epsilon_used DOUBLE PRECISION NOT NULL,
            sampling_rate DOUBLE PRECISION NOT NULL,
            server_received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, day)
        ) PARTITION BY RANGE (day)
        """
    )
    op.create_index("ix_ldp_reports_site_kind_day", "ldp_reports", ["site_id", "kind", "day"])

    op.create_table(
        "dp_windows",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("variance", sa.Float, nullable=False),
        sa.Column("ci80_low", sa.Float, nullable=False),
        sa.Column("ci80_high", sa.Float, nullable=False),
        sa.Column("ci95_low", sa.Float, nullable=False),
        sa.Column("ci95_high", sa.Float, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("site_id", "window_start", "metric", name="uq_window"),
    )
    op.create_index("ix_dp_windows_site_metric", "dp_windows", ["site_id", "metric"])

    op.create_table(
        "daily_uniques",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("variance", sa.Float, nullable=False),
        sa.UniqueConstraint("site_id", "day", name="uq_daily_uniques"),
    )

    op.create_table(
        "model_store",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("engine", sa.Text, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("mape_cv", sa.Float, nullable=False),
    )
    op.create_index("ix_model_store_site_metric", "model_store", ["site_id", "engine"])

    op.create_table(
        "forecasts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("yhat", sa.Float, nullable=False),
        sa.Column("yhat_lower", sa.Float, nullable=False),
        sa.Column("yhat_upper", sa.Float, nullable=False),
        sa.Column("mape", sa.Float, nullable=False),
        sa.Column("has_anomaly", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("z_score", sa.Float, nullable=False, server_default=sa.text("0")),
        sa.Column("model_id", sa.Integer, sa.ForeignKey("model_store.id")),
    )
    op.create_index("ix_forecasts_site_metric_day", "forecasts", ["site_id", "metric", "day"])

    op.create_table(
        "upload_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("iat", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("allowed_origin", sa.Text, nullable=False),
        sa.Column("sampling_rate", sa.Float, nullable=False),
        sa.Column("epsilon_budget", sa.Float, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_upload_tokens_site", "upload_tokens", ["site_id"])

    op.create_table(
        "token_nonce",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("jti", sa.Text, nullable=False, unique=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    op.create_table(
        "site_epsilon_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("site_id", sa.Text, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("epsilon_total", sa.Float, nullable=False),
        sa.UniqueConstraint("site_id", "day", name="uq_site_epsilon"),
    )

    op.create_table(
        "site_config",
        sa.Column("site_id", sa.Text, primary_key=True),
        sa.Column("max_events_per_minute", sa.Integer, nullable=False, server_default="60"),
        sa.Column("experimental_metrics", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_table("site_config")
    op.drop_table("site_epsilon_log")
    op.drop_table("token_nonce")
    op.drop_table("upload_tokens")
    op.drop_index("ix_forecasts_site_metric_day", table_name="forecasts")
    op.drop_table("forecasts")
    op.drop_index("ix_model_store_site_metric", table_name="model_store")
    op.drop_table("model_store")
    op.drop_table("daily_uniques")
    op.drop_index("ix_dp_windows_site_metric", table_name="dp_windows")
    op.drop_table("dp_windows")
    op.drop_index("ix_ldp_reports_site_kind_day", table_name="ldp_reports")
    op.execute("DROP TABLE IF EXISTS ldp_reports CASCADE")
