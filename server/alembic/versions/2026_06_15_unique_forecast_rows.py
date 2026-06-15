"""make forecast rows unique by site plan metric day

Revision ID: 2026_06_15_unique_forecast_rows
Revises: 2026_06_07_breakdown_rollups
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_06_15_unique_forecast_rows"
down_revision = "2026_06_07_breakdown_rollups"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "uq_forecast_site_plan_metric_day"


def _has_constraint(inspector, table_name: str, constraint_name: str) -> bool:
    return constraint_name in {constraint["name"] for constraint in inspector.get_unique_constraints(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            delete from forecasts old
            using forecasts newer
            where old.site_id = newer.site_id
              and old.plan = newer.plan
              and old.metric = newer.metric
              and old.day = newer.day
              and old.id < newer.id
            """
        )
    else:
        op.execute(
            """
            delete from forecasts
            where id not in (
              select max(id)
              from forecasts
              group by site_id, plan, metric, day
            )
            """
        )

    if not _has_constraint(inspector, "forecasts", CONSTRAINT_NAME):
        with op.batch_alter_table("forecasts") as batch_op:
            batch_op.create_unique_constraint(
                CONSTRAINT_NAME,
                ["site_id", "plan", "metric", "day"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_constraint(inspector, "forecasts", CONSTRAINT_NAME):
        with op.batch_alter_table("forecasts") as batch_op:
            batch_op.drop_constraint(CONSTRAINT_NAME, type_="unique")
