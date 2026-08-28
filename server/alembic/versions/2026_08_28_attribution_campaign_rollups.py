"""add campaign attribution rollup columns

Revision ID: 2026_08_28_attribution_campaign_rollups
Revises: 2026_08_27_segment_rollups
Create Date: 2026-08-28
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_08_28_attribution_campaign_rollups"
down_revision = "2026_08_27_segment_rollups"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _has_constraint(inspector, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "segment_rollups"):
        return

    for column_name in ("campaign", "content", "term"):
        if not _has_column(inspector, "segment_rollups", column_name):
            op.add_column(
                "segment_rollups",
                sa.Column(column_name, sa.String(length=160), nullable=False, server_default=""),
            )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_constraint(inspector, "segment_rollups", "uq_segment_rollup"):
        op.drop_constraint("uq_segment_rollup", "segment_rollups", type_="unique")

    op.create_unique_constraint(
        "uq_segment_rollup",
        "segment_rollups",
        [
            "site_id",
            "plan",
            "day",
            "grain",
            "hostname",
            "channel",
            "source",
            "source_medium",
            "campaign",
            "content",
            "term",
            "country",
            "device",
            "page",
            "conversion_type",
            "metric",
        ],
    )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "segment_rollups", "ix_segment_rollups_campaign_day"):
        op.create_index(
            "ix_segment_rollups_campaign_day",
            "segment_rollups",
            ["site_id", "plan", "campaign", "day"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "segment_rollups"):
        return

    if _has_index(inspector, "segment_rollups", "ix_segment_rollups_campaign_day"):
        op.drop_index("ix_segment_rollups_campaign_day", table_name="segment_rollups")
    if _has_constraint(inspector, "segment_rollups", "uq_segment_rollup"):
        op.drop_constraint("uq_segment_rollup", "segment_rollups", type_="unique")

    op.create_unique_constraint(
        "uq_segment_rollup",
        "segment_rollups",
        [
            "site_id",
            "plan",
            "day",
            "grain",
            "hostname",
            "channel",
            "source",
            "source_medium",
            "country",
            "device",
            "page",
            "conversion_type",
            "metric",
        ],
    )

    for column_name in ("term", "content", "campaign"):
        if _has_column(inspector, "segment_rollups", column_name):
            op.drop_column("segment_rollups", column_name)
