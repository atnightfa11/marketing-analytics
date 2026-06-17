"""add commercial readiness audit tables

Revision ID: 2026_06_16_commercial_readiness
Revises: 2026_06_15_dashboard_notes
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_16_commercial_readiness"
down_revision = "2026_06_15_dashboard_notes"
branch_labels = None
depends_on = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def _has_constraint(inspector, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "raw_reports") and not _has_column(inspector, "raw_reports", "import_batch_id"):
        op.add_column("raw_reports", sa.Column("import_batch_id", sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)
    if _has_table(inspector, "raw_reports") and not _has_index(inspector, "raw_reports", "ix_raw_reports_import_batch"):
        op.create_index("ix_raw_reports_import_batch", "raw_reports", ["import_batch_id"], unique=False)

    if not _has_table(inspector, "dashboard_site_access"):
        op.create_table(
            "dashboard_site_access",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(["username"], ["dashboard_users.username"]),
            sa.UniqueConstraint("site_id", "username", name="uq_dashboard_site_access_member"),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "dashboard_site_access", "ix_dashboard_site_access_site"):
        op.create_index("ix_dashboard_site_access_site", "dashboard_site_access", ["site_id"], unique=False)
    if not _has_index(inspector, "dashboard_site_access", "ix_dashboard_site_access_username"):
        op.create_index("ix_dashboard_site_access_username", "dashboard_site_access", ["username"], unique=False)

    if not _has_table(inspector, "historical_import_batches"):
        op.create_table(
            "historical_import_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("site_id", sa.String(), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False, server_default="csv"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("imported_rows", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reduced_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("start_day", sa.Date(), nullable=True),
            sa.Column("end_day", sa.Date(), nullable=True),
            sa.Column("metrics", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.String(length=64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error", sa.String(length=2000), nullable=True),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, "historical_import_batches", "ix_historical_import_batches_site_created"):
        op.create_index(
            "ix_historical_import_batches_site_created",
            "historical_import_batches",
            ["site_id", "created_at"],
            unique=False,
        )
    if not _has_index(inspector, "historical_import_batches", "ix_historical_import_batches_site_status"):
        op.create_index(
            "ix_historical_import_batches_site_status",
            "historical_import_batches",
            ["site_id", "status"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, "historical_import_batches"):
        if _has_index(inspector, "historical_import_batches", "ix_historical_import_batches_site_status"):
            op.drop_index("ix_historical_import_batches_site_status", table_name="historical_import_batches")
        if _has_index(inspector, "historical_import_batches", "ix_historical_import_batches_site_created"):
            op.drop_index("ix_historical_import_batches_site_created", table_name="historical_import_batches")
        op.drop_table("historical_import_batches")

    if _has_table(inspector, "dashboard_site_access"):
        if _has_index(inspector, "dashboard_site_access", "ix_dashboard_site_access_username"):
            op.drop_index("ix_dashboard_site_access_username", table_name="dashboard_site_access")
        if _has_index(inspector, "dashboard_site_access", "ix_dashboard_site_access_site"):
            op.drop_index("ix_dashboard_site_access_site", table_name="dashboard_site_access")
        if _has_constraint(inspector, "dashboard_site_access", "uq_dashboard_site_access_member"):
            with op.batch_alter_table("dashboard_site_access") as batch_op:
                batch_op.drop_constraint("uq_dashboard_site_access_member", type_="unique")
        op.drop_table("dashboard_site_access")

    inspector = sa.inspect(bind)
    if _has_table(inspector, "raw_reports") and _has_index(inspector, "raw_reports", "ix_raw_reports_import_batch"):
        op.drop_index("ix_raw_reports_import_batch", table_name="raw_reports")
    if _has_table(inspector, "raw_reports") and _has_column(inspector, "raw_reports", "import_batch_id"):
        op.drop_column("raw_reports", "import_batch_id")
