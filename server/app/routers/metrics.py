from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dependencies import get_site_plan
from ..ldp.rr_decoder import confidence_interval, standard_error
from ..models import DailyUnique, DpWindow, get_session
from ..schemas import MetricsResponse, MetricStatistic

router = APIRouter(tags=["metrics"])
settings = get_settings()


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    site_id: str,
    start: str | None = None,
    end: str | None = None,
    metrics: list[str] | None = Query(default=None),
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
    rows = (await session.execute(stmt)).scalars().all()

    metric_map: dict[str, MetricStatistic] = {}
    for row in rows:
        se = standard_error(row.variance)
        snr = row.value / se if se > 0 else 0
        if snr < 1.5 or row.value <= 0:
            continue
        metric_map[row.metric] = MetricStatistic(
            metric=row.metric,
            value=row.value,
            variance=row.variance,
            standard_error=se,
            snr=snr,
            published_at=row.published_at,
            ci80=_ci(row.value, se, 1.2816),
            ci95=_ci(row.value, se, 1.9599),
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
            snr=float("inf"),
            ci80=_ci(conversion_rate, 0.0, 1.2816),
            ci95=_ci(conversion_rate, 0.0, 1.9599),
            has_anomaly=False,
        )

    return MetricsResponse(site_id=site_id, metrics=list(metric_map.values()))


def _ci(value: float, se: float, z: float):
    low, high = confidence_interval(value, se, z)
    return {"low": max(0.0, low), "high": max(0.0, high)}
