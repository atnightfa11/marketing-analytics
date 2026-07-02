from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dependencies import get_site_plan, require_site_access
from ..dashboard_auth import require_dashboard_auth
from ..entitlements import forecast_metric_allowed, display_plan_name
from ..forecast_freshness import forecast_is_fresh
from ..models import Forecast, get_session
from ..schemas import ForecastResponse, ForecastPoint

router = APIRouter(tags=["forecast"])


@router.get("/forecast/{metric}", response_model=ForecastResponse, status_code=status.HTTP_200_OK)
async def forecast(
    metric: str,
    site_id: str,
    request: Request,
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
):
    plan = await get_site_plan(site_id, session)
    if not forecast_metric_allowed(plan, metric):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{display_plan_name(plan)} does not include {metric} forecasts. Upgrade to Standard for all forecast metrics.",
        )
    stmt = (
        select(Forecast)
        .where(Forecast.site_id == site_id, Forecast.metric == metric, Forecast.plan == plan)
        .order_by(Forecast.day.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    if len(rows) < 1:
        return Response(status_code=status.HTTP_204_NO_CONTENT)  # type: ignore

    latest = rows[-1]
    if not forecast_is_fresh(latest):
        return Response(status_code=status.HTTP_204_NO_CONTENT)  # type: ignore

    request.app.state.prometheus_gauges["forecast_mape_gauge"].labels(site_id=site_id, metric=metric).set(latest.mape)
    if latest.has_anomaly:
        request.app.state.prometheus_counters["anomaly_flagged_total"].labels(
            site_id=site_id, metric=metric
        ).inc()

    return ForecastResponse(
        site_id=site_id,
        metric=metric,
        forecast=[_forecast_point_from_row(row) for row in rows],
        mape=latest.mape,
        has_anomaly=latest.has_anomaly,
        z_score=latest.z_score,
        trained_at=latest.trained_at,
    )


def _forecast_point_from_row(row: Forecast) -> ForecastPoint:
    yhat = max(0.0, float(row.yhat))
    yhat_lower = max(0.0, float(row.yhat_lower))
    yhat_upper = max(0.0, float(row.yhat_upper))
    if yhat_lower > yhat:
        yhat_lower = yhat
    if yhat_upper < yhat:
        yhat_upper = yhat
    return ForecastPoint(day=row.day, yhat=yhat, yhat_lower=yhat_lower, yhat_upper=yhat_upper)
