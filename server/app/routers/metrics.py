from __future__ import annotations

import datetime as dt
import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import require_dashboard_auth
from ..dependencies import get_site_plan, require_site_access
from ..ldp.rr_decoder import confidence_interval, standard_error
from ..models import DpWindow, get_session
from ..schemas import MetricsResponse, MetricStatistic

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    site_id: str,
    start: str | None = None,
    end: str | None = None,
    metrics: list[str] | None = Query(default=None),
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(DpWindow).where(DpWindow.site_id == site_id, DpWindow.plan == plan)
    if start:
        stmt = stmt.where(DpWindow.window_start >= start)
    if end:
        stmt = stmt.where(DpWindow.window_end <= end)
    if metrics:
        stmt = stmt.where(DpWindow.metric.in_(metrics))
    rows = (await session.execute(stmt.order_by(DpWindow.window_start))).scalars().all()

    aggregated: dict[str, dict[str, float | dt.datetime | None]] = {}
    for row in rows:
        bucket = aggregated.setdefault(
            row.metric,
            {"value": 0.0, "variance": 0.0, "published_at": None},
        )
        bucket["value"] = float(bucket["value"] or 0.0) + row.value
        bucket["variance"] = float(bucket["variance"] or 0.0) + max(0.0, row.variance)
        if row.published_at and (
            bucket["published_at"] is None or row.published_at > bucket["published_at"]  # type: ignore[operator]
        ):
            bucket["published_at"] = row.published_at

    metric_map: dict[str, MetricStatistic] = {}
    for metric, values in aggregated.items():
        value = float(values["value"] or 0.0)
        variance = float(values["variance"] or 0.0)
        se = standard_error(variance)
        snr = value / se if se > 0 else 0.0
        if snr < 1.5 or value <= 0:
            continue
        metric_map[metric] = MetricStatistic(
            metric=metric,
            value=value,
            variance=variance,
            standard_error=se,
            snr=snr,
            published_at=values["published_at"],
            ci80=_ci(value, se, 1.2816),
            ci95=_ci(value, se, 1.9599),
            has_anomaly=False,
        )

    if "sessions" in metric_map and "pageviews" in metric_map:
        sessions_metric = metric_map["sessions"]
        pageviews_metric = metric_map["pageviews"]
        if sessions_metric.value > pageviews_metric.value:
            sessions_metric.value = pageviews_metric.value

    if "conversions" in metric_map and "pageviews" in metric_map and metric_map["pageviews"].value > 0:
        conversions = metric_map["conversions"].value
        pageviews = metric_map["pageviews"].value
        conversion_rate = conversions / pageviews
        metric_map["conversion_rate"] = MetricStatistic(
            metric="conversion_rate",
            value=conversion_rate,
            variance=0.0,
            standard_error=0.0,
            # Derived metric; no direct RR/DP variance term, so keep finite for JSON safety.
            snr=0.0,
            ci80=_ci(conversion_rate, 0.0, 1.2816),
            ci95=_ci(conversion_rate, 0.0, 1.9599),
            has_anomaly=False,
        )

    return MetricsResponse(site_id=site_id, metrics=list(metric_map.values()))


def _ci(value: float, se: float, z: float):
    low, high = confidence_interval(value, se, z)
    return {"low": max(0.0, low), "high": max(0.0, high)}
