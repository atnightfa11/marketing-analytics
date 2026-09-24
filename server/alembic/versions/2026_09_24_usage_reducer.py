"""Durable usage accounting and bounded reducer diagnostics.

Revision ID: 2026_09_24_usage_reducer
Revises: 2026_09_17_anomaly_details
"""
from alembic import op
import sqlalchemy as sa

revision = "2026_09_24_usage_reducer"
down_revision = "2026_09_17_anomaly_details"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("site_plan", sa.Column("stripe_current_period_start", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_raw_reports_site_day_id", "raw_reports", ["site_id", "day", "id"])
    op.create_table("ingest_receipts",
        sa.Column("event_hash", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingest_receipts_expires", "ingest_receipts", ["expires_at"])
    op.create_table("account_usage",
        sa.Column("account_key", sa.String(320), primary_key=True),
        sa.Column("site_id", sa.String(), primary_key=True),
        sa.Column("period_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("period_basis", sa.String(32), primary_key=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_pageviews", sa.BigInteger(), nullable=False),
        sa.Column("first_recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table("reducer_runs",
        sa.Column("site_id", sa.String(), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("process_peak_rss_bytes", sa.BigInteger(), nullable=False),
        sa.Column("raw_report_count", sa.Integer(), nullable=False),
        sa.Column("segment_rollup_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(1000), nullable=True),
    )


def downgrade():
    op.drop_table("reducer_runs")
    op.drop_table("account_usage")
    op.drop_table("ingest_receipts")
    op.drop_index("ix_raw_reports_site_day_id", table_name="raw_reports")
    op.drop_column("site_plan", "stripe_current_period_start")
