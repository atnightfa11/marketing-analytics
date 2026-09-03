from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import require_dashboard_auth
from ..dependencies import require_site_access
from ..entitlements import effective_plan_for_record
from ..forecast_freshness import forecast_is_fresh
from ..forecast_status import latest_forecasts_by_metric
from ..models import DpWindow, RawReport, ReducerWatermark, SiteApiKey, SitePlan, get_session
from ..schemas import SiteHealthCheck, SiteHealthResponse

router = APIRouter(prefix="/site-health", tags=["site-health"])

FORECAST_HEALTH_METRICS = ("pageviews", "sessions", "uniques")


@router.get("", response_model=SiteHealthResponse, dependencies=[Depends(require_dashboard_auth)])
async def get_site_health(
    site_id: str,
    lookback_minutes: int = Query(default=60, ge=5, le=24 * 60),
    _: None = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
) -> SiteHealthResponse:
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=lookback_minutes)

    plan_record = await session.get(SitePlan, site_id)
    plan = effective_plan_for_record(plan_record)

    active_site_keys = int(
        (
            await session.execute(
                select(func.count(SiteApiKey.id)).where(
                    SiteApiKey.site_id == site_id,
                    SiteApiKey.is_active.is_(True),
                )
            )
        ).scalar_one()
        or 0
    )

    counts_rows = (
        await session.execute(
            select(RawReport.kind, func.count(RawReport.id))
            .where(
                RawReport.site_id == site_id,
                RawReport.server_received_at >= cutoff,
            )
            .group_by(RawReport.kind)
        )
    ).all()
    counts_by_kind = {kind: int(count) for kind, count in counts_rows}
    recent_reports = int(sum(counts_by_kind.values()))
    last_report_at = (
        await session.execute(
            select(func.max(RawReport.server_received_at)).where(RawReport.site_id == site_id)
        )
    ).scalar_one_or_none()

    recent_payloads = (
        await session.execute(
            select(RawReport.payload)
            .where(
                RawReport.site_id == site_id,
                RawReport.server_received_at >= cutoff,
            )
            .order_by(desc(RawReport.server_received_at))
            .limit(200)
        )
    ).scalars().all()
    detected_hostnames = sorted(
        {
            str(payload.get("_hostname") or payload.get("hostname")).strip()
            for payload in recent_payloads
            if isinstance(payload, dict) and str(payload.get("_hostname") or payload.get("hostname") or "").strip()
        }
    )[:10]

    latest_watermark = (
        await session.execute(
            select(ReducerWatermark)
            .where(ReducerWatermark.site_id == site_id, ReducerWatermark.plan == plan)
            .order_by(desc(ReducerWatermark.day), desc(ReducerWatermark.reduced_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    latest_window = (
        await session.execute(
            select(DpWindow)
            .where(DpWindow.site_id == site_id, DpWindow.plan == plan)
            .order_by(desc(DpWindow.window_start), desc(DpWindow.published_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    latest_forecasts = await latest_forecasts_by_metric(
        session, site_id, plan, FORECAST_HEALTH_METRICS
    )
    forecast_metrics_ready = sorted(
        metric
        for metric, forecast in latest_forecasts.items()
        if metric in FORECAST_HEALTH_METRICS and forecast.mape <= 0.5 and forecast_is_fresh(forecast, now)
    )
    forecast_metrics_building = sorted(set(FORECAST_HEALTH_METRICS) - set(forecast_metrics_ready))

    checks = [
        _check_api_key(active_site_keys),
        _check_tracking(last_report_at, recent_reports, lookback_minutes),
        _check_reducer(latest_watermark, plan),
        _check_windows(latest_window, plan),
        _check_forecast(forecast_metrics_ready, forecast_metrics_building),
    ]
    overall_status = _overall_status(checks)

    return SiteHealthResponse(
        site_id=site_id,
        plan=plan,
        overall_status=overall_status,
        lookback_minutes=lookback_minutes,
        recent_reports=recent_reports,
        counts_by_kind=counts_by_kind,
        last_report_at=last_report_at,
        active_site_keys=active_site_keys,
        detected_hostnames=detected_hostnames,
        latest_reducer_status=latest_watermark.status if latest_watermark else None,
        latest_reducer_day=latest_watermark.day if latest_watermark else None,
        latest_reduced_at=latest_watermark.reduced_at if latest_watermark else None,
        latest_standard_window_start=latest_window.window_start if latest_window else None,
        latest_standard_published_at=latest_window.published_at if latest_window else None,
        forecast_metrics_ready=forecast_metrics_ready,
        forecast_metrics_building=forecast_metrics_building,
        checks=checks,
    )


def _check_api_key(active_site_keys: int) -> SiteHealthCheck:
    if active_site_keys > 0:
        return SiteHealthCheck(
            key="api_key",
            label="Site key",
            status="ok",
            detail=f"{active_site_keys} active site key{'s' if active_site_keys != 1 else ''}.",
        )
    return SiteHealthCheck(
        key="api_key",
        label="Site key",
        status="warning",
        detail="No active site key is configured.",
        action="Create or reactivate a site key before installing the script.",
    )


def _check_tracking(
    last_report_at: dt.datetime | None,
    recent_reports: int,
    lookback_minutes: int,
) -> SiteHealthCheck:
    if recent_reports > 0:
        return SiteHealthCheck(
            key="tracking",
            label="Tracking",
            status="ok",
            detail=f"{recent_reports} reports received in the last {lookback_minutes} minutes.",
        )
    if last_report_at:
        return SiteHealthCheck(
            key="tracking",
            label="Tracking",
            status="warning",
            detail=f"No reports in the last {lookback_minutes} minutes. Last report was {last_report_at.isoformat()}.",
            action="Check whether the site currently has traffic and verify the installed script.",
        )
    return SiteHealthCheck(
        key="tracking",
        label="Tracking",
        status="warning",
        detail="No reports have been received for this site yet.",
        action="Install the script and load the site once to verify tracking.",
    )


def _check_reducer(watermark: ReducerWatermark | None, plan: str) -> SiteHealthCheck:
    if not watermark:
        return SiteHealthCheck(
            key="reducer",
            label="Reducer",
            status="warning",
            detail=f"No {plan} reducer watermark has been recorded yet.",
            action="Run the reducer after data starts arriving.",
        )
    if watermark.status == "success":
        return SiteHealthCheck(
            key="reducer",
            label="Reducer",
            status="ok",
            detail=f"Latest reduced day is {watermark.day.isoformat()} with {watermark.dp_window_count} KPI windows.",
        )
    return SiteHealthCheck(
        key="reducer",
        label="Reducer",
        status="error",
        detail=watermark.error or f"Latest reducer status is {watermark.status}.",
        action="Review reducer logs before purging raw reports.",
    )


def _check_windows(window: DpWindow | None, plan: str) -> SiteHealthCheck:
    if window:
        return SiteHealthCheck(
            key="windows",
            label="Aggregate windows",
            status="ok",
            detail=f"Latest {plan} aggregate window starts {window.window_start.isoformat()}.",
        )
    return SiteHealthCheck(
        key="windows",
        label="Aggregate windows",
        status="warning",
        detail=f"No {plan} aggregate windows have been published.",
        action="Confirm reducer completion after reports are received.",
    )


def _check_forecast(ready: list[str], building: list[str]) -> SiteHealthCheck:
    if not building:
        return SiteHealthCheck(
            key="forecast",
            label="Forecast",
            status="ok",
            detail=f"Forecasts are ready for {', '.join(ready)}.",
        )
    if ready:
        return SiteHealthCheck(
            key="forecast",
            label="Forecast",
            status="warning",
            detail=f"Ready: {', '.join(ready)}. Building: {', '.join(building)}.",
            action="Forecast quality improves after more complete days are reduced.",
        )
    return SiteHealthCheck(
        key="forecast",
        label="Forecast",
        status="warning",
        detail="Forecasts are still building for the core traffic metrics.",
        action="Add more complete daily history or wait for reducer runs to accumulate data.",
    )


def _overall_status(checks: list[SiteHealthCheck]) -> str:
    if any(check.status == "error" for check in checks):
        return "error"
    if any(check.status == "warning" for check in checks):
        return "warning"
    return "ok"
