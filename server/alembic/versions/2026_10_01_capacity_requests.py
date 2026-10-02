"""Owner-requested capacity changes; no automatic overage billing."""
from alembic import op
import sqlalchemy as sa

revision = "2026_10_01_capacity_requests"
down_revision = "2026_09_24_usage_reducer"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("site_plan", sa.Column("extra_pageview_quantity", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "capacity_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("account_key", sa.String(320), nullable=False),
        sa.Column("site_id", sa.String(), nullable=False),
        sa.Column("subscription_id", sa.String(), nullable=False),
        sa.Column("additional_millions", sa.Integer(), nullable=False),
        sa.Column("monthly_price_usd", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_capacity_requests_pending", "capacity_requests", ["account_key"], unique=True,
                    postgresql_where=sa.text("status = 'pending'"), sqlite_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_table("capacity_requests")
    op.drop_column("site_plan", "extra_pageview_quantity")
