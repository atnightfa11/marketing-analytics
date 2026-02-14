"""tier rollout raw reports and plan columns

Revision ID: 2026_02_13_tier_rollout_raw_reports
Revises: 2025_10_22_add_site_plan
Create Date: 2026-02-13 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_02_13_tier_rollout_raw_reports"
down_revision = "2025_10_22_add_site_plan"
branch_labels = None
depends_on = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _safe_drop_index(index_name: str, table_name: str):
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())

    if "raw_reports" not in existing_tables:
        op.create_table(
            "raw_reports",
            sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
            sa.Column("site_id", sa.Text(), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("day", sa.Date(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("epsilon_used", sa.Float(), nullable=False),
            sa.Column("sampling_rate", sa.Float(), nullable=False),
            sa.Column(
                "server_received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_raw_reports_site_kind_day", "raw_reports", ["site_id", "kind", "day"])

    if not _has_column(inspector, "dp_windows", "plan"):
        op.add_column("dp_windows", sa.Column("plan", sa.Text(), nullable=False, server_default="free"))
    if _has_index(inspector, "dp_windows", "ix_dp_windows_site_metric"):
        op.drop_index("ix_dp_windows_site_metric", table_name="dp_windows")
    op.create_index("ix_dp_windows_site_metric", "dp_windows", ["site_id", "metric", "plan"])

    # replace unique constraint
    constraints = {c["name"] for c in inspector.get_unique_constraints("dp_windows")}
    if "uq_window" in constraints:
        op.drop_constraint("uq_window", "dp_windows", type_="unique")
    op.create_unique_constraint("uq_window", "dp_windows", ["site_id", "window_start", "metric", "plan"])

    if not _has_column(inspector, "forecasts", "plan"):
        op.add_column("forecasts", sa.Column("plan", sa.Text(), nullable=False, server_default="free"))
    if _has_index(inspector, "forecasts", "ix_forecasts_site_metric_day"):
        op.drop_index("ix_forecasts_site_metric_day", table_name="forecasts")
    op.create_index("ix_forecasts_site_metric_day", "forecasts", ["site_id", "metric", "day", "plan"])

    if not _has_column(inspector, "model_store", "plan"):
        op.add_column("model_store", sa.Column("plan", sa.Text(), nullable=False, server_default="free"))
    if _has_index(inspector, "model_store", "ix_model_store_site_metric"):
        op.drop_index("ix_model_store_site_metric", table_name="model_store")
    op.create_index("ix_model_store_site_metric", "model_store", ["site_id", "engine", "metric", "plan"])

    if not _has_column(inspector, "site_epsilon_log", "plan"):
        op.add_column("site_epsilon_log", sa.Column("plan", sa.Text(), nullable=False, server_default="standard"))
    constraints = {c["name"] for c in inspector.get_unique_constraints("site_epsilon_log")}
    if "uq_site_epsilon" in constraints:
        op.drop_constraint("uq_site_epsilon", "site_epsilon_log", type_="unique")
    op.create_unique_constraint("uq_site_epsilon", "site_epsilon_log", ["site_id", "day", "plan"])


def downgrade():
    _safe_drop_index("ix_raw_reports_site_kind_day", "raw_reports")
    op.drop_table("raw_reports")

    _safe_drop_index("ix_dp_windows_site_metric", "dp_windows")
    op.create_index("ix_dp_windows_site_metric", "dp_windows", ["site_id", "metric"])
    op.drop_constraint("uq_window", "dp_windows", type_="unique")
    op.create_unique_constraint("uq_window", "dp_windows", ["site_id", "window_start", "metric"])
    op.drop_column("dp_windows", "plan")

    _safe_drop_index("ix_forecasts_site_metric_day", "forecasts")
    op.create_index("ix_forecasts_site_metric_day", "forecasts", ["site_id", "metric", "day"])
    op.drop_column("forecasts", "plan")

    _safe_drop_index("ix_model_store_site_metric", "model_store")
    op.create_index("ix_model_store_site_metric", "model_store", ["site_id", "engine"])
    op.drop_column("model_store", "plan")

    op.drop_constraint("uq_site_epsilon", "site_epsilon_log", type_="unique")
    op.create_unique_constraint("uq_site_epsilon", "site_epsilon_log", ["site_id", "day"])
    op.drop_column("site_epsilon_log", "plan")
