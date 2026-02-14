from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_site_plan
from ..models import Forecast, ModelStore, get_session
from ..schemas import ForecastResponse, ForecastPoint

router = APIRouter(tags=["forecast"])


@router.get("/forecast/{metric}", response_model=ForecastResponse, status_code=status.HTTP_200_OK)
async def forecast(metric: str, site_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    plan = await get_site_plan(site_id, session)
    stmt = (
        select(Forecast)
        .where(Forecast.site_id == site_id, Forecast.metric == metric, Forecast.plan == plan)
        .order_by(Forecast.day.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    if len(rows) < 1:
        return Response(status_code=status.HTTP_204_NO_CONTENT)  # type: ignore

    latest = rows[-1]
    request.app.state.prometheus_gauges["forecast_mape_gauge"].labels(site_id=site_id, metric=metric).set(latest.mape)
    if latest.has_anomaly:
        request.app.state.prometheus_counters["anomaly_flagged_total"].labels(
            site_id=site_id, metric=metric
        ).inc()

    return ForecastResponse(
        site_id=site_id,
        metric=metric,
        forecast=[
            ForecastPoint(day=row.day, yhat=row.yhat, yhat_lower=row.yhat_lower, yhat_upper=row.yhat_upper)
            for row in rows
        ],
        mape=latest.mape,
        has_anomaly=latest.has_anomaly,
        z_score=latest.z_score,
    )
