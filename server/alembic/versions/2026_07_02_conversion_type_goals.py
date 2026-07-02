"""add conversion type targets to site goals

Revision ID: 2026_07_02_conversion_type_goals
Revises: 2026_06_18_site_goals
Create Date: 2026-07-02
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_07_02_conversion_type_goals"
down_revision = "2026_06_18_site_goals"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_unique_constraint(inspector, table_name: str, constraint_name: str) -> bool:
    return any(constraint["name"] == constraint_name for constraint in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "site_goals"):
        return

    if not _has_column(inspector, "site_goals", "conversion_type"):
        op.add_column("site_goals", sa.Column("conversion_type", sa.String(length=120), nullable=True))

    # The original constraint allowed only one "conversions" target per site. Replace it
    # with partial unique indexes so all-metric goals and conversion-specific goals can coexist.
    if bind.dialect.name != "sqlite" and _has_unique_constraint(inspector, "site_goals", "uq_site_goals_site_metric"):
        op.drop_constraint("uq_site_goals_site_metric", "site_goals", type_="unique")

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "site_goals", "uq_site_goals_site_metric_default"):
        op.create_index(
            "uq_site_goals_site_metric_default",
            "site_goals",
            ["site_id", "metric"],
            unique=True,
            postgresql_where=sa.text("conversion_type IS NULL"),
            sqlite_where=sa.text("conversion_type IS NULL"),
        )
    if not _has_index(inspector, "site_goals", "uq_site_goals_site_metric_conversion_type"):
        op.create_index(
            "uq_site_goals_site_metric_conversion_type",
            "site_goals",
            ["site_id", "metric", "conversion_type"],
            unique=True,
            postgresql_where=sa.text("conversion_type IS NOT NULL"),
            sqlite_where=sa.text("conversion_type IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "site_goals"):
        return

    if _has_index(inspector, "site_goals", "uq_site_goals_site_metric_conversion_type"):
        op.drop_index("uq_site_goals_site_metric_conversion_type", table_name="site_goals")
    if _has_index(inspector, "site_goals", "uq_site_goals_site_metric_default"):
        op.drop_index("uq_site_goals_site_metric_default", table_name="site_goals")

    if bind.dialect.name != "sqlite" and not _has_unique_constraint(inspector, "site_goals", "uq_site_goals_site_metric"):
        op.create_unique_constraint("uq_site_goals_site_metric", "site_goals", ["site_id", "metric"])

    inspector = sa.inspect(bind)
    if _has_column(inspector, "site_goals", "conversion_type"):
        op.drop_column("site_goals", "conversion_type")
