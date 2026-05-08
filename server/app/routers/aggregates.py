from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import require_dashboard_auth
from ..dependencies import get_site_plan, require_site_access
from ..hostnames import hostname_from_payload, normalize_hostname
from ..ldp.rr_decoder import confidence_interval, standard_error
from ..models import DpWindow, RawReport, get_session
from ..schemas import AggregateResponse, WindowAggregate

router = APIRouter(tags=["metrics"])
settings = get_settings()


def _raw_report_value(report: RawReport) -> float:
    payload = report.payload if isinstance(report.payload, dict) else {}
    if report.kind == "revenue":
        try:
            return max(0.0, float(payload.get("value", 0.0)))
        except (TypeError, ValueError):
            return 0.0
    if payload.get("historical_import"):
        try:
            return max(0.0, float(payload.get("value", 0.0)))
        except (TypeError, ValueError):
            return 0.0
    return 1.0


def _window_minutes(metric: str) -> int:
    if metric == "uniques":
        return 3
    return 15


def _bucket_start(timestamp: dt.datetime, metric: str) -> dt.datetime:
    bucket_seconds = max(1, _window_minutes(metric)) * 60
    ts = int(timestamp.replace(second=0, microsecond=0).timestamp())
    floored = ts - (ts % bucket_seconds)
    return dt.datetime.fromtimestamp(floored, tz=dt.timezone.utc)


def _payload_matches_hostname(payload: dict, hostname_filter: str) -> bool:
    payload_hostname = hostname_from_payload(payload)
    return payload_hostname == hostname_filter


async def _aggregate_free_hostname(
    *,
    session: AsyncSession,
    site_id: str,
    metric: str,
    hostname_filter: str,
    window: str,
) -> list[WindowAggregate]:
    stmt = (
        select(RawReport)
        .where(RawReport.site_id == site_id, RawReport.kind == metric)
        .order_by(RawReport.server_received_at, RawReport.id)
    )
    reports = (await session.execute(stmt)).scalars().all()

    buckets: dict[dt.datetime, list[RawReport]] = defaultdict(list)
    seen_session_markers: set[tuple[dt.datetime, str]] = set()
    seen_unique_markers: set[tuple[dt.date, str]] = set()
    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if not _payload_matches_hostname(payload, hostname_filter):
            continue

        # Keep hostname-scoped free aggregates aligned with reducer semantics:
        # - sessions are deduped per session bucket + session_hmac
        # - uniques are deduped per day + visitor_day_hmac
        if metric == "sessions":
            session_hmac = payload.get("_session_hmac")
            if isinstance(session_hmac, str) and session_hmac:
                session_bucket = _bucket_start(report.server_received_at, "sessions")
                marker = (session_bucket, session_hmac)
                if marker in seen_session_markers:
                    continue
                seen_session_markers.add(marker)
        elif metric == "uniques":
            visitor_day_hmac = payload.get("_visitor_day_hmac")
            if isinstance(visitor_day_hmac, str) and visitor_day_hmac:
                marker = (report.day, visitor_day_hmac)
                if marker in seen_unique_markers:
                    continue
                seen_unique_markers.add(marker)

        # Free reducer windows are minute-started, with metric-specific window_end.
        start = report.server_received_at.replace(second=0, microsecond=0)
        buckets[start].append(report)

    windows: list[WindowAggregate] = []
    for window_start in sorted(buckets.keys()):
        items = buckets[window_start]
        historical_bucket = any(
            isinstance(item.payload, dict) and bool(item.payload.get("historical_import")) for item in items
        )
        if not historical_bucket and len(items) < settings.MIN_REPORTS_PER_WINDOW:
            continue
        value = sum(_raw_report_value(item) for item in items)
        if value <= 0:
            continue
        variance = max(1.0, value)
        se = standard_error(variance)
        ci80_low, ci80_high = confidence_interval(value, se, 1.2816)
        ci95_low, ci95_high = confidence_interval(value, se, 1.9599)
        window_end = window_start + dt.timedelta(minutes=_window_minutes(metric))
        windows.append(
            WindowAggregate(
                window_start=window_start,
                window_end=window_end,
                value=value,
                variance=variance,
                ci80={"low": max(0.0, ci80_low), "high": max(0.0, ci80_high)},
                ci95={"low": max(0.0, ci95_low), "high": max(0.0, ci95_high)},
            )
        )

    if window == "live":
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)
        windows = [entry for entry in windows if entry.window_start >= cutoff]
    return windows


@router.get("/aggregate", response_model=AggregateResponse)
async def aggregate(
    site_id: str,
    metric: str,
    window: str = Query(default="standard", pattern="^(live|standard)$"),
    hostname: str | None = None,
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
):
    if hostname is not None:
        hostname_filter = normalize_hostname(hostname)
        if not hostname_filter:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hostname must be a valid host value",
            )
        if plan != "free":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hostname filter is currently available for free plan sites",
            )
        windows = await _aggregate_free_hostname(
            session=session,
            site_id=site_id,
            metric=metric,
            hostname_filter=hostname_filter,
            window=window,
        )
        return AggregateResponse(site_id=site_id, metric=metric, windows=windows)

    stmt = select(DpWindow).where(DpWindow.site_id == site_id, DpWindow.metric == metric, DpWindow.plan == plan)
    if window == "live":
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)
        stmt = stmt.where(DpWindow.window_start >= cutoff)
    rows = (await session.execute(stmt.order_by(DpWindow.window_start))).scalars().all()
    windows = [
        WindowAggregate(
            window_start=row.window_start,
            window_end=row.window_end,
            value=row.value,
            variance=row.variance,
            ci80={"low": row.ci80_low, "high": row.ci80_high},
            ci95={"low": row.ci95_low, "high": row.ci95_high},
        )
        for row in rows
    ]
    return AggregateResponse(site_id=site_id, metric=metric, windows=windows)
