from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Forecast


async def latest_forecasts_by_metric(
    session: AsyncSession,
    site_id: str,
    plan: str,
    metrics: Iterable[str] | None = None,
) -> dict[str, Forecast]:
    """Return the most recent forecast row (max ``day``) per metric for a site/plan.

    Freshness is intentionally not applied here: callers gate on
    ``forecast_is_fresh`` (and any metric-specific thresholds such as MAPE)
    themselves, since each consumer treats stale rows differently. Centralising
    the query keeps the "latest row per metric" selection consistent across the
    metrics, site-health, and forecast surfaces.
    """
    stmt = select(Forecast).where(Forecast.site_id == site_id, Forecast.plan == plan)
    if metrics is not None:
        metric_list = list(metrics)
        if not metric_list:
            return {}
        stmt = stmt.where(Forecast.metric.in_(metric_list))
    stmt = stmt.order_by(Forecast.metric, Forecast.day.asc())

    latest: dict[str, Forecast] = {}
    for row in (await session.execute(stmt)).scalars().all():
        # day-ascending order means the last write per metric is the max day.
        latest[row.metric] = row
    return latest
