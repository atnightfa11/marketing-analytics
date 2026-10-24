"""Prospective site-local reporting with an explicit legacy UTC cutover."""
from alembic import op
import datetime as dt
from zoneinfo import ZoneInfo
import sqlalchemy as sa

revision = "2026_10_24_reporting_timezone"
down_revision = "2026_10_21_account_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("dashboard_sites", sa.Column("previous_reporting_timezone", sa.String(64), nullable=True))
    op.add_column("dashboard_sites", sa.Column("reporting_timezone_effective_at", sa.DateTime(timezone=True), nullable=True))
    # Allow at least 24h for the API/worker rollout before switching day labels.
    # Never rewrite retained raw rows or already-purged aggregate history here.
    earliest = dt.datetime.combine(dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=2), dt.time.min, dt.timezone.utc)
    sites = sa.table("dashboard_sites", sa.column("site_id", sa.String()), sa.column("timezone", sa.String()),
                     sa.column("previous_reporting_timezone", sa.String()),
                     sa.column("reporting_timezone_effective_at", sa.DateTime(timezone=True)))
    connection = op.get_bind()
    for site_id, timezone in connection.execute(sa.select(sites.c.site_id, sites.c.timezone).where(sites.c.timezone != "UTC")).all():
        local = earliest.astimezone(ZoneInfo(timezone))
        cutoff = dt.datetime.combine(local.date(), dt.time.min, ZoneInfo(timezone))
        if cutoff < local:
            cutoff += dt.timedelta(days=1)
        connection.execute(sites.update().where(sites.c.site_id == site_id).values(
            previous_reporting_timezone="UTC", reporting_timezone_effective_at=cutoff.astimezone(dt.timezone.utc),
        ))


def downgrade():
    op.drop_column("dashboard_sites", "reporting_timezone_effective_at")
    op.drop_column("dashboard_sites", "previous_reporting_timezone")
