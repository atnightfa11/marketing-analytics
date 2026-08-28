"""add segment rollups

Revision ID: 2026_08_27_segment_rollups
Revises: 2026_07_02_conversion_type_goals
Create Date: 2026-08-27
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_08_27_segment_rollups"
down_revision = "2026_07_02_conversion_type_goals"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "segment_rollups"):
        op.create_table(
            "segment_rollups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("plan", sa.String(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("grain", sa.String(), nullable=False),
            sa.Column("hostname", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("channel", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("source", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("source_medium", sa.String(length=160), nullable=False, server_default=""),
            sa.Column("country", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("device", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("page", sa.String(length=220), nullable=False, server_default=""),
            sa.Column("conversion_type", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("metric", sa.String(), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
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
                name="uq_segment_rollup",
            ),
        )

    if not _has_index(inspector, "segment_rollups", "ix_segment_rollups_lookup"):
        op.create_index(
            "ix_segment_rollups_lookup",
            "segment_rollups",
            ["site_id", "plan", "metric", "grain", "day"],
        )
    if not _has_index(inspector, "segment_rollups", "ix_segment_rollups_day"):
        op.create_index("ix_segment_rollups_day", "segment_rollups", ["site_id", "plan", "day"])
    if not _has_index(inspector, "segment_rollups", "ix_segment_rollups_channel_country_day"):
        op.create_index(
            "ix_segment_rollups_channel_country_day",
            "segment_rollups",
            ["site_id", "plan", "channel", "country", "day"],
        )
    if not _has_index(inspector, "segment_rollups", "ix_segment_rollups_source_medium_day"):
        op.create_index(
            "ix_segment_rollups_source_medium_day",
            "segment_rollups",
            ["site_id", "plan", "source_medium", "day"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "segment_rollups"):
        for index_name in (
            "ix_segment_rollups_source_medium_day",
            "ix_segment_rollups_channel_country_day",
            "ix_segment_rollups_day",
            "ix_segment_rollups_lookup",
        ):
            if _has_index(inspector, "segment_rollups", index_name):
                op.drop_index(index_name, table_name="segment_rollups")
        op.drop_table("segment_rollups")
