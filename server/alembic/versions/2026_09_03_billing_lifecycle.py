"""add billing lifecycle state

Revision ID: 2026_09_03_billing_lifecycle
Revises: 2026_08_28_attribution_campaign_rollups
Create Date: 2026-09-03
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_09_03_billing_lifecycle"
down_revision = "2026_08_28_attribution_campaign_rollups"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "site_plan"):
        columns = {
            "stripe_subscription_status": sa.Column("stripe_subscription_status", sa.String(length=64), nullable=True),
            "stripe_current_period_end": sa.Column("stripe_current_period_end", sa.DateTime(timezone=True), nullable=True),
            "stripe_cancel_at_period_end": sa.Column(
                "stripe_cancel_at_period_end",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            "billing_past_due_at": sa.Column("billing_past_due_at", sa.DateTime(timezone=True), nullable=True),
            "billing_grace_ends_at": sa.Column("billing_grace_ends_at", sa.DateTime(timezone=True), nullable=True),
            "extra_site_subscription_item_id": sa.Column("extra_site_subscription_item_id", sa.String(), nullable=True),
            "extra_site_quantity": sa.Column(
                "extra_site_quantity",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        }
        for column_name, column in columns.items():
            if not _has_column(inspector, "site_plan", column_name):
                op.add_column("site_plan", column)

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "stripe_events"):
        op.create_table(
            "stripe_events",
            sa.Column("event_id", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.PrimaryKeyConstraint("event_id"),
        )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "stripe_events") and not _has_index(
        inspector,
        "stripe_events",
        "ix_stripe_events_type_processed",
    ):
        op.create_index(
            "ix_stripe_events_type_processed",
            "stripe_events",
            ["event_type", "processed_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "stripe_events"):
        if _has_index(inspector, "stripe_events", "ix_stripe_events_type_processed"):
            op.drop_index("ix_stripe_events_type_processed", table_name="stripe_events")
        op.drop_table("stripe_events")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "site_plan"):
        for column_name in (
            "extra_site_quantity",
            "extra_site_subscription_item_id",
            "billing_grace_ends_at",
            "billing_past_due_at",
            "stripe_cancel_at_period_end",
            "stripe_current_period_end",
            "stripe_subscription_status",
        ):
            if _has_column(inspector, "site_plan", column_name):
                op.drop_column("site_plan", column_name)
