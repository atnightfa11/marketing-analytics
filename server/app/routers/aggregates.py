from __future__ import annotations

import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import require_dashboard_auth
from ..dependencies import get_site_plan, require_site_access
from ..entitlements import enforce_aggregate_retention
from ..hostnames import hostname_from_payload, normalize_hostname
from ..ldp.rr_decoder import confidence_interval, standard_error
from ..models import BreakdownRollup, DpWindow, RawReport, ReducerWatermark, SegmentRollup, get_session
from ..scheduler.nightly_reduce import REDUCER_VERSION
from ..schemas import AggregateResponse, WindowAggregate
from ..segment_rollups import (
    SEGMENT_DIMENSIONS,
    SEGMENT_METRICS,
    aggregate_reports_for_segments,
    resolve_segment_grain,
    segment_key_from_filters,
)

router = APIRouter(tags=["metrics"])
settings = get_settings()

DEFAULT_AGGREGATE_DAYS = 90
MAX_AGGREGATE_DAYS = 730


def _day_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)


def _resolve_date_window(start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    if start and end:
        start_day, end_day = (start, end) if start <= end else (end, start)
    elif start:
        start_day = end_day = start
    elif end:
        start_day = end_day = end
    else:
        end_day = dt.datetime.now(dt.timezone.utc).date()
        start_day = end_day - dt.timedelta(days=DEFAULT_AGGREGATE_DAYS - 1)

    days = (end_day - start_day).days + 1
    if days > MAX_AGGREGATE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"aggregate range cannot exceed {MAX_AGGREGATE_DAYS} days",
        )
    return start_day, end_day


def _enumerate_days(start_day: dt.date, end_day: dt.date) -> list[dt.date]:
    return [start_day + dt.timedelta(days=offset) for offset in range((end_day - start_day).days + 1)]


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


def _window_from_rollup(day: dt.date, metric: str, value: float) -> WindowAggregate:
    value = max(0.0, value)
    variance = max(1.0, value)
    se = standard_error(variance)
    ci80_low, ci80_high = confidence_interval(value, se, 1.2816)
    ci95_low, ci95_high = confidence_interval(value, se, 1.9599)
    window_start = _day_start(day)
    return WindowAggregate(
        window_start=window_start,
        window_end=window_start + dt.timedelta(days=1),
        value=value,
        variance=variance,
        ci80={"low": max(0.0, ci80_low), "high": max(0.0, ci80_high)},
        ci95={"low": max(0.0, ci95_low), "high": max(0.0, ci95_high)},
    )


def _parse_segment_filter_params(filter_params: list[str] | None) -> tuple[tuple[str, str], tuple[str, ...], str]:
    parsed: list[tuple[str, str]] = []
    for filter_param in filter_params or []:
        if ":" not in filter_param:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="segment filters must use dimension:value format",
            )
        dimension, value = filter_param.split(":", 1)
        parsed.append((dimension, value))
    try:
        return resolve_segment_grain(parsed)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def _aggregate_segment_rollups(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    metric: str,
    reduced_days: set[dt.date],
    normalized_filters: tuple[tuple[str, str], ...],
    grain: str,
) -> list[WindowAggregate]:
    if not reduced_days:
        return []
    key = segment_key_from_filters(normalized_filters, grain)
    stmt = select(SegmentRollup).where(
        SegmentRollup.site_id == site_id,
        SegmentRollup.plan == plan,
        SegmentRollup.metric == metric,
        SegmentRollup.grain == grain,
        SegmentRollup.day.in_(reduced_days),
    )
    for dimension in SEGMENT_DIMENSIONS:
        stmt = stmt.where(getattr(SegmentRollup, dimension) == getattr(key, dimension))
    rows = (await session.execute(stmt.order_by(SegmentRollup.day))).scalars().all()
    return [_window_from_rollup(row.day, metric, row.value) for row in rows]


async def _aggregate_raw_segments(
    *,
    session: AsyncSession,
    site_id: str,
    metric: str,
    raw_days: set[dt.date],
    normalized_filters: tuple[tuple[str, str], ...],
    grain: str,
) -> list[WindowAggregate]:
    if not raw_days:
        return []
    reports = (
        await session.execute(
            select(RawReport)
            .where(
                RawReport.site_id == site_id,
                RawReport.day.in_(raw_days),
            )
            .order_by(RawReport.server_received_at, RawReport.id)
        )
    ).scalars().all()
    reports_by_day: dict[dt.date, list[RawReport]] = defaultdict(list)
    for report in reports:
        reports_by_day[report.day].append(report)

    key = segment_key_from_filters(normalized_filters, grain)
    max_gap_seconds = max(1, settings.SESSION_WINDOW_MINUTES) * 60
    windows: list[WindowAggregate] = []
    for day in sorted(raw_days):
        buckets = aggregate_reports_for_segments(reports_by_day.get(day, []), max_gap_seconds=max_gap_seconds)
        value = buckets.get(key, {}).get(metric, 0.0)
        if value <= 0:
            continue
        windows.append(_window_from_rollup(day, metric, value))
    return windows


async def _aggregate_free_hostname(
    *,
    session: AsyncSession,
    site_id: str,
    metric: str,
    hostname_filter: str,
    window: str,
    raw_days: set[dt.date],
) -> list[WindowAggregate]:
    if not raw_days:
        return []
    stmt = (
        select(RawReport)
        .where(
            RawReport.site_id == site_id,
            RawReport.kind == metric,
            RawReport.day.in_(raw_days),
        )
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

        # Historical/reporting aggregates use day buckets to match reducer output;
        # the live endpoint remains raw-backed and minute-bucketed.
        start = _bucket_start(report.server_received_at, metric) if window == "live" else _day_start(report.day)
        buckets[start].append(report)

    windows: list[WindowAggregate] = []
    for window_start in sorted(buckets.keys()):
        items = buckets[window_start]
        value = sum(_raw_report_value(item) for item in items)
        if value <= 0:
            continue
        variance = max(1.0, value)
        se = standard_error(variance)
        ci80_low, ci80_high = confidence_interval(value, se, 1.2816)
        ci95_low, ci95_high = confidence_interval(value, se, 1.9599)
        window_end = (
            window_start + dt.timedelta(minutes=_window_minutes(metric))
            if window == "live"
            else window_start + dt.timedelta(days=1)
        )
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


@router.get("/aggregate/segments", response_model=AggregateResponse)
async def segment_aggregate(
    site_id: str,
    metric: str,
    window: str = Query(default="standard", pattern="^(live|standard)$"),
    start: dt.date | None = None,
    end: dt.date | None = None,
    filters: list[str] | None = Query(default=None, alias="filter"),
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
):
    start_day, end_day = _resolve_date_window(start, end)
    enforce_aggregate_retention(plan, start_day, end_day)
    if metric not in SEGMENT_METRICS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metric is not segment-rollup backed")
    if plan == "pro":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="segment filters are not available for Pro sites yet")

    normalized_filters, _dimensions, grain = _parse_segment_filter_params(filters)
    all_days = set(_enumerate_days(start_day, end_day))
    if window == "live":
        reduced_days: set[dt.date] = set()
        raw_days = {dt.datetime.now(dt.timezone.utc).date()}
    else:
        reduced_days = await _successful_reduced_days(
            session=session,
            site_id=site_id,
            plan=plan,
            start_day=start_day,
            end_day=end_day,
        )
        raw_days = all_days - reduced_days

    windows = await _aggregate_segment_rollups(
        session=session,
        site_id=site_id,
        plan=plan,
        metric=metric,
        reduced_days=reduced_days,
        normalized_filters=normalized_filters,
        grain=grain,
    )
    windows.extend(
        await _aggregate_raw_segments(
            session=session,
            site_id=site_id,
            metric=metric,
            raw_days=raw_days,
            normalized_filters=normalized_filters,
            grain=grain,
        )
    )
    windows.sort(key=lambda entry: entry.window_start)
    return AggregateResponse(site_id=site_id, metric=metric, windows=windows)


async def _successful_reduced_days(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    start_day: dt.date,
    end_day: dt.date,
) -> set[dt.date]:
    rows = (
        await session.execute(
            select(ReducerWatermark.day).where(
                ReducerWatermark.site_id == site_id,
                ReducerWatermark.plan == plan,
                ReducerWatermark.reducer_version == REDUCER_VERSION,
                ReducerWatermark.status == "success",
                ReducerWatermark.day >= start_day,
                ReducerWatermark.day <= end_day,
            )
        )
    ).all()
    return {row[0] for row in rows}


async def _aggregate_hostname_rollups(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    metric: str,
    hostname_filter: str,
    reduced_days: set[dt.date],
) -> list[WindowAggregate]:
    if not reduced_days:
        return []
    rollups = (
        await session.execute(
            select(BreakdownRollup).where(
                BreakdownRollup.site_id == site_id,
                BreakdownRollup.plan == plan,
                BreakdownRollup.dimension == "hostnames",
                BreakdownRollup.hostname == "",
                BreakdownRollup.day_type == "all",
                BreakdownRollup.label == hostname_filter,
                BreakdownRollup.metric == metric,
                BreakdownRollup.day.in_(reduced_days),
            )
        )
    ).scalars().all()
    windows: list[WindowAggregate] = []
    for rollup in sorted(rollups, key=lambda row: row.day):
        value = max(0.0, rollup.value)
        variance = max(1.0, value)
        se = standard_error(variance)
        ci80_low, ci80_high = confidence_interval(value, se, 1.2816)
        ci95_low, ci95_high = confidence_interval(value, se, 1.9599)
        window_start = _day_start(rollup.day)
        windows.append(
            WindowAggregate(
                window_start=window_start,
                window_end=window_start + dt.timedelta(days=1),
                value=value,
                variance=variance,
                ci80={"low": max(0.0, ci80_low), "high": max(0.0, ci80_high)},
                ci95={"low": max(0.0, ci95_low), "high": max(0.0, ci95_high)},
            )
        )
    return windows


@router.get("/aggregate", response_model=AggregateResponse)
async def aggregate(
    site_id: str,
    metric: str,
    window: str = Query(default="standard", pattern="^(live|standard)$"),
    hostname: str | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
):
    start_day, end_day = _resolve_date_window(start, end)
    enforce_aggregate_retention(plan, start_day, end_day)
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
                detail="hostname filter is currently available for Solo sites",
            )
        all_days = set(_enumerate_days(start_day, end_day))
        if window == "live":
            reduced_days: set[dt.date] = set()
            raw_days = {dt.datetime.now(dt.timezone.utc).date()}
        else:
            reduced_days = await _successful_reduced_days(
                session=session,
                site_id=site_id,
                plan=plan,
                start_day=start_day,
                end_day=end_day,
            )
            raw_days = all_days - reduced_days
        windows = await _aggregate_hostname_rollups(
            session=session,
            site_id=site_id,
            plan=plan,
            metric=metric,
            hostname_filter=hostname_filter,
            reduced_days=reduced_days,
        )
        windows.extend(await _aggregate_free_hostname(
            session=session,
            site_id=site_id,
            metric=metric,
            hostname_filter=hostname_filter,
            window=window,
            raw_days=raw_days,
        ))
        windows.sort(key=lambda entry: entry.window_start)
        return AggregateResponse(site_id=site_id, metric=metric, windows=windows)

    stmt = select(DpWindow).where(DpWindow.site_id == site_id, DpWindow.metric == metric, DpWindow.plan == plan)
    stmt = stmt.where(
        DpWindow.window_start >= _day_start(start_day),
        DpWindow.window_start < _day_start(end_day + dt.timedelta(days=1)),
    )
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
