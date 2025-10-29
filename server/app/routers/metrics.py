from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
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
    session: AsyncSession = Depends(get_session),
):
    stmt = select(DpWindow).where(DpWindow.site_id == site_id)
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

    return MetricsResponse(site_id=site_id, metrics=list(metric_map.values()))


def _ci(value: float, se: float, z: float):
    low, high = confidence_interval(value, se, z)
    return {"low": max(0.0, low), "high": max(0.0, high)}
