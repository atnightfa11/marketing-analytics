"""add breakdown rollups and reducer watermarks

Revision ID: 2026_06_07_breakdown_rollups
Revises: 2026_05_29_upload_token_exp_index
Create Date: 2026-06-07
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_07_breakdown_rollups"
down_revision = "2026_05_29_upload_token_exp_index"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in set(inspector.get_table_names())


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "breakdown_rollups"):
        op.create_table(
            "breakdown_rollups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("plan", sa.String(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("dimension", sa.String(), nullable=False),
            sa.Column("hostname", sa.String(), nullable=False, server_default=""),
            sa.Column("day_type", sa.String(), nullable=False, server_default="all"),
            sa.Column("label", sa.String(), nullable=False),
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
                "dimension",
                "hostname",
                "day_type",
                "label",
                "metric",
                name="uq_breakdown_rollup",
            ),
        )
    if not _has_index(inspector, "breakdown_rollups", "ix_breakdown_rollups_lookup"):
        op.create_index(
            "ix_breakdown_rollups_lookup",
            "breakdown_rollups",
            ["site_id", "plan", "dimension", "day"],
        )
    if not _has_index(inspector, "breakdown_rollups", "ix_breakdown_rollups_hostname"):
        op.create_index(
            "ix_breakdown_rollups_hostname",
            "breakdown_rollups",
            ["site_id", "plan", "hostname", "day"],
        )

    if not _has_table(inspector, "reducer_watermarks"):
        op.create_table(
            "reducer_watermarks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("plan", sa.String(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("reducer_version", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("raw_report_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("dp_window_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("breakdown_rollup_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reduced_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("raw_purged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("site_id", "plan", "day", "reducer_version", name="uq_reducer_watermark"),
        )
    if not _has_index(inspector, "reducer_watermarks", "ix_reducer_watermarks_status"):
        op.create_index(
            "ix_reducer_watermarks_status",
            "reducer_watermarks",
            ["status", "day"],
        )
    if not _has_index(inspector, "reducer_watermarks", "ix_reducer_watermarks_site_day"):
        op.create_index(
            "ix_reducer_watermarks_site_day",
            "reducer_watermarks",
            ["site_id", "day"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "reducer_watermarks"):
        if _has_index(inspector, "reducer_watermarks", "ix_reducer_watermarks_site_day"):
            op.drop_index("ix_reducer_watermarks_site_day", table_name="reducer_watermarks")
        if _has_index(inspector, "reducer_watermarks", "ix_reducer_watermarks_status"):
            op.drop_index("ix_reducer_watermarks_status", table_name="reducer_watermarks")
        op.drop_table("reducer_watermarks")

    if _has_table(inspector, "breakdown_rollups"):
        if _has_index(inspector, "breakdown_rollups", "ix_breakdown_rollups_hostname"):
            op.drop_index("ix_breakdown_rollups_hostname", table_name="breakdown_rollups")
        if _has_index(inspector, "breakdown_rollups", "ix_breakdown_rollups_lookup"):
            op.drop_index("ix_breakdown_rollups_lookup", table_name="breakdown_rollups")
        op.drop_table("breakdown_rollups")
