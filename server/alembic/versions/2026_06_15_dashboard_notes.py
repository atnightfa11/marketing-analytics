"""add dashboard notes

Revision ID: 2026_06_15_dashboard_notes
Revises: 2026_06_15_unique_forecast_rows
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_15_dashboard_notes"
down_revision = "2026_06_15_unique_forecast_rows"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, "dashboard_notes"):
        op.create_table(
            "dashboard_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("body", sa.String(length=1200), nullable=False),
            sa.Column("metric", sa.String(length=64), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "dashboard_notes", "ix_dashboard_notes_site_day"):
        op.create_index("ix_dashboard_notes_site_day", "dashboard_notes", ["site_id", "day"], unique=False)
    if not _has_index(inspector, "dashboard_notes", "ix_dashboard_notes_created"):
        op.create_index("ix_dashboard_notes_created", "dashboard_notes", ["created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, "dashboard_notes"):
        if _has_index(inspector, "dashboard_notes", "ix_dashboard_notes_created"):
            op.drop_index("ix_dashboard_notes_created", table_name="dashboard_notes")
        if _has_index(inspector, "dashboard_notes", "ix_dashboard_notes_site_day"):
            op.drop_index("ix_dashboard_notes_site_day", table_name="dashboard_notes")
        op.drop_table("dashboard_notes")
