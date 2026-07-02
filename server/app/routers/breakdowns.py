from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import breakdown_logic
from ..config import get_settings
from ..dashboard_auth import require_dashboard_auth
from ..dependencies import get_site_plan, require_site_access
from ..entitlements import enforce_aggregate_retention
from ..hostnames import hostname_from_payload, normalize_hostname
from ..models import BreakdownRollup, DashboardSite, RawReport, ReducerWatermark, get_session
from ..scheduler.nightly_reduce import REDUCER_VERSION
from ..schemas import BreakdownResponse, BreakdownRow

router = APIRouter(tags=["metrics"])
BreakdownDimension = Literal["pages", "sources", "devices", "countries", "conversions", "hour_of_day", "day_of_week", "hostnames"]
BreakdownMetric = Literal["uniques", "sessions", "pageviews", "conversions", "revenue"]
TimePartingDayType = Literal["all", "weekday", "weekend"]
settings = get_settings()

HOUR_OF_DAY_LABELS = [
    "12 AM",
    "1 AM",
    "2 AM",
    "3 AM",
    "4 AM",
    "5 AM",
    "6 AM",
    "7 AM",
    "8 AM",
    "9 AM",
    "10 AM",
    "11 AM",
    "12 PM",
    "1 PM",
    "2 PM",
    "3 PM",
    "4 PM",
    "5 PM",
    "6 PM",
    "7 PM",
    "8 PM",
    "9 PM",
    "10 PM",
    "11 PM",
]
HOUR_OF_DAY_ORDER = {label: index for index, label in enumerate(HOUR_OF_DAY_LABELS)}
DAY_OF_WEEK_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_OF_WEEK_ORDER = {label: index for index, label in enumerate(DAY_OF_WEEK_LABELS)}

BREAKDOWN_METRIC_ORDER: dict[BreakdownDimension, tuple[BreakdownMetric, ...]] = {
    "pages": ("uniques", "sessions", "pageviews"),
    "sources": ("uniques", "sessions", "pageviews", "conversions"),
    "devices": ("uniques", "sessions", "pageviews", "conversions"),
    "countries": ("uniques", "sessions", "pageviews", "conversions"),
    "conversions": ("uniques", "sessions", "conversions"),
    "hour_of_day": ("uniques", "sessions", "pageviews", "conversions"),
    "day_of_week": ("uniques", "sessions", "pageviews", "conversions"),
    "hostnames": ("uniques", "sessions", "pageviews", "conversions", "revenue"),
}
BREAKDOWN_PRIMARY_METRIC: dict[BreakdownDimension, BreakdownMetric] = {
    "pages": "pageviews",
    "sources": "sessions",
    "devices": "pageviews",
    "countries": "pageviews",
    "conversions": "conversions",
    "hour_of_day": "sessions",
    "day_of_week": "sessions",
    "hostnames": "sessions",
}
BREAKDOWN_REPORT_KINDS: dict[BreakdownDimension, tuple[str, ...]] = {
    "pages": ("pageviews",),
    "sources": ("sessions", "pageviews", "conversions"),
    "devices": ("sessions", "pageviews", "conversions"),
    "countries": ("sessions", "pageviews", "conversions"),
    "conversions": ("conversions",),
    "hour_of_day": ("sessions", "pageviews", "conversions"),
    "day_of_week": ("sessions", "pageviews", "conversions"),
    "hostnames": ("sessions", "pageviews", "conversions", "revenue"),
}
TIME_PARTING_DIMENSIONS: set[BreakdownDimension] = {"hour_of_day", "day_of_week"}
TIME_PARTING_MIN_DAYS = 7
TIME_PARTING_MIN_SESSIONS = 10.0
BREAKDOWN_MIN_PRIMARY_THRESHOLD: dict[BreakdownDimension, float] = {
    "pages": 2.0,
    "sources": 2.0,
    "devices": 2.0,
    "countries": 1.0,
    "conversions": 2.0,
    "hour_of_day": TIME_PARTING_MIN_SESSIONS,
    "day_of_week": TIME_PARTING_MIN_SESSIONS,
    "hostnames": 1.0,
}

COMMON_SOURCE_HOST_MAP = {
    "google.com": "Google",
    "duckduckgo.com": "DuckDuckGo",
    "reddit.com": "Reddit",
    "x.com": "X",
    "t.co": "X",
    "linkedin.com": "LinkedIn",
}


def _parse_iso_date(value: str, field_name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be an ISO date (YYYY-MM-DD)",
        ) from exc


def _resolve_window(start: str | None, end: str | None) -> tuple[dt.date, dt.date]:
    if start and end:
        start_day = _parse_iso_date(start, "start")
        end_day = _parse_iso_date(end, "end")
        return (start_day, end_day) if start_day <= end_day else (end_day, start_day)
    if start:
        start_day = _parse_iso_date(start, "start")
        return start_day, start_day
    if end:
        end_day = _parse_iso_date(end, "end")
        return end_day, end_day
    end_day = dt.date.today()
    start_day = end_day - dt.timedelta(days=29)
    return start_day, end_day


def _session_bucket_start(timestamp: dt.datetime) -> dt.datetime:
    bucket_minutes = max(1, settings.SESSION_WINDOW_MINUTES)
    minute = timestamp.minute - (timestamp.minute % bucket_minutes)
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def _session_marker(server_received_at: dt.datetime, payload: dict) -> tuple[dt.datetime, str] | None:
    session_hmac = payload.get("_session_hmac")
    if not isinstance(session_hmac, str) or not session_hmac:
        return None
    return _session_bucket_start(server_received_at), session_hmac


def _visitor_marker(day: dt.date, payload: dict) -> tuple[dt.date, str] | None:
    visitor_hmac = payload.get("_visitor_day_hmac")
    if not isinstance(visitor_hmac, str) or not visitor_hmac:
        return None
    return day, visitor_hmac


def _blank_metric_map(metric_keys: tuple[BreakdownMetric, ...]) -> dict[str, float]:
    return {metric: 0.0 for metric in metric_keys}


def _increment_metric(
    buckets: defaultdict[str, dict[str, float]],
    totals: dict[str, float],
    label: str,
    metric: BreakdownMetric,
):
    buckets[label][metric] += 1.0
    totals[metric] += 1.0


def _raw_report_value(report: RawReport) -> float:
    payload = report.payload if isinstance(report.payload, dict) else {}
    try:
        return max(0.0, float(payload.get("value", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_page_path(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip()
    if not value:
        return "Unknown"

    path: str
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        path = parsed.path or "/"
    else:
        path = value.split("?", 1)[0].split("#", 1)[0]

    if not path:
        path = "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path[:200]


def _normalize_source_bucket(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().lower()
    mapping = {
        "direct": "Direct",
        "external": "Referral",
        "organic": "Organic",
        "referral": "Referral",
        "social": "Social",
        "email": "Email",
        "paid": "Paid",
    }
    return mapping.get(value, "Unknown")


def _normalize_host(raw_value: str) -> str:
    value = raw_value.strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = value.split("://", 1)[1]
    host = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize_source_label(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().lower()
    if not value:
        return "Unknown"
    if value in {"direct", "(direct)"}:
        return "Direct"
    if value in {"external", "unknown"}:
        return "Referral"

    host = _normalize_host(value)
    if host:
        for known_host, label in COMMON_SOURCE_HOST_MAP.items():
            if host == known_host or host.endswith(f".{known_host}"):
                return label
        if "." in host:
            return host[:120]

    normalized = " ".join(value.replace("_", " ").replace("-", " ").split())
    if normalized:
        return normalized.title()[:120]
    return "Unknown"


def _normalize_device_bucket(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().lower()
    mapping = {
        "mobile": "Mobile",
        "desktop": "Desktop",
        "tablet": "Tablet",
    }
    return mapping.get(value, "Unknown")


def _normalize_country_code(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().upper()
    if len(value) != 2 or not value.isalpha() or value == "XX":
        return "Unknown"
    return value


def _normalize_conversion_event(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip()
    if not value:
        return "Unknown"
    normalized = " ".join(value.replace("_", " ").replace("-", " ").split())
    return normalized.title()[:120] if normalized else "Unknown"


def _normalize_hostname_label(payload: dict) -> str:
    host = hostname_from_payload(payload)
    return host if host else "Unknown"


def _hour_of_day_label(timestamp: dt.datetime) -> str:
    return HOUR_OF_DAY_LABELS[timestamp.hour]


def _day_of_week_label(timestamp: dt.datetime) -> str:
    return DAY_OF_WEEK_LABELS[timestamp.weekday()]


def _resolve_label(dimension: BreakdownDimension, payload: dict, server_received_at: dt.datetime) -> str:
    if dimension == "pages":
        return _normalize_page_path(payload.get("url"))
    if dimension == "sources":
        source_label = _normalize_source_label(payload.get("referrer_source"))
        if source_label != "Unknown":
            return source_label
        return _normalize_source_bucket(payload.get("referrer_bucket"))
    if dimension == "devices":
        return _normalize_device_bucket(payload.get("_device_bucket"))
    if dimension == "conversions":
        return _normalize_conversion_event(payload.get("conversion_type"))
    if dimension == "hostnames":
        return _normalize_hostname_label(payload)
    if dimension == "hour_of_day":
        return _hour_of_day_label(server_received_at)
    if dimension == "day_of_week":
        return _day_of_week_label(server_received_at)
    return _normalize_country_code(payload.get("_country_code"))


def _ordered_buckets(
    dimension: BreakdownDimension,
    buckets: dict[str, dict[str, float]],
    primary_metric: BreakdownMetric,
    limit: int,
) -> list[tuple[str, dict[str, float]]]:
    items = list(buckets.items())
    if dimension == "hour_of_day":
        items.sort(key=lambda item: HOUR_OF_DAY_ORDER.get(item[0], 999))
        return items[:limit]
    if dimension == "day_of_week":
        items.sort(key=lambda item: DAY_OF_WEEK_ORDER.get(item[0], 999))
        return items[:limit]
    return sorted(items, key=lambda item: (-item[1].get(primary_metric, 0.0), item[0]))[:limit]


def _window_days(start_day: dt.date, end_day: dt.date) -> int:
    return (end_day - start_day).days + 1


def _enumerate_days(start_day: dt.date, end_day: dt.date) -> list[dt.date]:
    return [start_day + dt.timedelta(days=offset) for offset in range(_window_days(start_day, end_day))]


def _matches_time_parting_day_type(timestamp: dt.datetime, day_type: TimePartingDayType) -> bool:
    if day_type == "all":
        return True
    is_weekend = timestamp.weekday() >= 5
    return is_weekend if day_type == "weekend" else not is_weekend


def _as_utc(timestamp: dt.datetime) -> dt.datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp.astimezone(dt.timezone.utc)


def _time_parting_timestamp(timestamp: dt.datetime, payload: dict, site_timezone: str) -> dt.datetime:
    timezone_name = payload.get("_timezone_hint")
    if not isinstance(timezone_name, str) or not timezone_name:
        timezone_name = site_timezone or "UTC"
    try:
        return _as_utc(timestamp).astimezone(ZoneInfo(timezone_name))
    except (ZoneInfoNotFoundError, ValueError):
        return _as_utc(timestamp)


def _payload_matches_hostname(payload: dict, hostname_filter: str | None) -> bool:
    if not hostname_filter:
        return True
    payload_hostname = hostname_from_payload(payload)
    if not payload_hostname:
        return False
    return payload_hostname == hostname_filter


def _empty_breakdown_response(
    *,
    site_id: str,
    dimension: BreakdownDimension,
    primary_metric: BreakdownMetric,
    metric_keys: tuple[BreakdownMetric, ...],
) -> BreakdownResponse:
    return BreakdownResponse(
        site_id=site_id,
        dimension=dimension,
        total=0.0,
        primary_metric=primary_metric,
        metric_keys=list(metric_keys),
        totals={metric: 0.0 for metric in metric_keys},
        rows=[],
    )


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


async def _breakdown_buckets_from_rollups(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    dimension: BreakdownDimension,
    start_day: dt.date,
    end_day: dt.date,
    reduced_days: set[dt.date],
    hostname_filter: str | None,
    day_type: TimePartingDayType,
) -> dict[str, dict[str, float]]:
    if not reduced_days:
        return {}
    metric_keys = BREAKDOWN_METRIC_ORDER[dimension]
    stmt = (
        select(BreakdownRollup)
        .where(
            BreakdownRollup.site_id == site_id,
            BreakdownRollup.plan == plan,
            BreakdownRollup.dimension == dimension,
            BreakdownRollup.day >= start_day,
            BreakdownRollup.day <= end_day,
            BreakdownRollup.day.in_(reduced_days),
            BreakdownRollup.hostname == (hostname_filter or ""),
        )
        .order_by(BreakdownRollup.day, BreakdownRollup.label, BreakdownRollup.metric)
    )
    if dimension in TIME_PARTING_DIMENSIONS and day_type != "all":
        stmt = stmt.where(BreakdownRollup.day_type == day_type)
    elif dimension not in TIME_PARTING_DIMENSIONS:
        stmt = stmt.where(BreakdownRollup.day_type == "all")

    rollups = (await session.execute(stmt)).scalars().all()
    buckets: defaultdict[str, dict[str, float]] = defaultdict(lambda: _blank_metric_map(metric_keys))
    for rollup in rollups:
        if rollup.metric not in metric_keys:
            continue
        buckets[rollup.label][rollup.metric] += rollup.value
    return dict(buckets)


def _merge_buckets(
    target: defaultdict[str, dict[str, float]],
    source: dict[str, dict[str, float]],
    metric_keys: tuple[BreakdownMetric, ...],
) -> None:
    for label, metrics in source.items():
        for metric in metric_keys:
            target[label][metric] += metrics.get(metric, 0.0)


@router.get("/breakdown", response_model=BreakdownResponse)
async def breakdown(
    site_id: str,
    dimension: BreakdownDimension,
    limit: int = Query(default=10, ge=1, le=50),
    start: str | None = None,
    end: str | None = None,
    hostname: str | None = None,
    day_type: TimePartingDayType = "all",
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
):
    metric_keys = BREAKDOWN_METRIC_ORDER[dimension]
    primary_metric = BREAKDOWN_PRIMARY_METRIC[dimension]

    # Pro ingest currently does not retain raw per-dimension event context.
    if plan == "pro":
        return _empty_breakdown_response(
            site_id=site_id,
            dimension=dimension,
            primary_metric=primary_metric,
            metric_keys=metric_keys,
        )

    start_day, end_day = _resolve_window(start, end)
    enforce_aggregate_retention(plan, start_day, end_day)
    hostname_filter = normalize_hostname(hostname) if hostname is not None else None
    if hostname is not None and not hostname_filter:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="hostname must be a valid host value",
        )
    if dimension in TIME_PARTING_DIMENSIONS and _window_days(start_day, end_day) < TIME_PARTING_MIN_DAYS:
        return _empty_breakdown_response(
            site_id=site_id,
            dimension=dimension,
            primary_metric=primary_metric,
            metric_keys=metric_keys,
        )

    all_days = set(_enumerate_days(start_day, end_day))
    reduced_days = await _successful_reduced_days(
        session=session,
        site_id=site_id,
        plan=plan,
        start_day=start_day,
        end_day=end_day,
    )
    unreduced_days = all_days - reduced_days

    buckets: defaultdict[str, dict[str, float]] = defaultdict(lambda: _blank_metric_map(metric_keys))
    rollup_buckets = await _breakdown_buckets_from_rollups(
        session=session,
        site_id=site_id,
        plan=plan,
        dimension=dimension,
        start_day=start_day,
        end_day=end_day,
        reduced_days=reduced_days,
        hostname_filter=hostname_filter,
        day_type=day_type,
    )
    _merge_buckets(buckets, rollup_buckets, metric_keys)
    if not unreduced_days:
        return breakdown_logic.build_breakdown_response_from_buckets(
            site_id=site_id,
            dimension=dimension,
            buckets=dict(buckets),
            limit=limit,
        )

    site = await session.get(DashboardSite, site_id)
    site_timezone = site.timezone if site and site.timezone else "UTC"
    report_kinds = BREAKDOWN_REPORT_KINDS[dimension]
    stmt = (
        select(RawReport)
        .where(RawReport.site_id == site_id, RawReport.kind.in_(report_kinds))
        .where(RawReport.day.in_(unreduced_days))
        .order_by(RawReport.server_received_at, RawReport.id)
    )
    reports = (await session.execute(stmt)).scalars().all()

    totals = _blank_metric_map(metric_keys)
    seen_sessions_by_label: defaultdict[str, set[tuple[dt.datetime, str]]] = defaultdict(set)
    seen_visitors_by_label: defaultdict[str, set[tuple[dt.date, str]]] = defaultdict(set)
    source_by_session: dict[tuple[dt.datetime, str], str] = {}

    if dimension == "sources":
        for report in reports:
            if report.kind != "sessions":
                continue
            payload = report.payload if isinstance(report.payload, dict) else {}
            if payload.get("historical_import"):
                continue
            if not _payload_matches_hostname(payload, hostname_filter):
                continue
            marker = _session_marker(report.server_received_at, payload)
            if marker and marker not in source_by_session:
                source_by_session[marker] = _resolve_label(dimension, payload, report.server_received_at)

    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        if not _payload_matches_hostname(payload, hostname_filter):
            continue
        label_timestamp = report.server_received_at
        if dimension in TIME_PARTING_DIMENSIONS:
            label_timestamp = _time_parting_timestamp(report.server_received_at, payload, site_timezone)
        if dimension in TIME_PARTING_DIMENSIONS and not _matches_time_parting_day_type(label_timestamp, day_type):
            continue
        session_marker = _session_marker(report.server_received_at, payload)
        visitor_marker = _visitor_marker(report.day, payload)

        if dimension == "pages":
            label = _resolve_label(dimension, payload, report.server_received_at)
            _increment_metric(buckets, totals, label, "pageviews")
            if session_marker and session_marker not in seen_sessions_by_label[label]:
                seen_sessions_by_label[label].add(session_marker)
                _increment_metric(buckets, totals, label, "sessions")
            if visitor_marker and visitor_marker not in seen_visitors_by_label[label]:
                seen_visitors_by_label[label].add(visitor_marker)
                _increment_metric(buckets, totals, label, "uniques")
            continue

        if dimension == "sources":
            if report.kind == "sessions":
                label = source_by_session.get(session_marker, _resolve_label(dimension, payload, report.server_received_at))
                if session_marker:
                    if session_marker not in seen_sessions_by_label[label]:
                        seen_sessions_by_label[label].add(session_marker)
                        _increment_metric(buckets, totals, label, "sessions")
                else:
                    _increment_metric(buckets, totals, label, "sessions")
                if visitor_marker and visitor_marker not in seen_visitors_by_label[label]:
                    seen_visitors_by_label[label].add(visitor_marker)
                    _increment_metric(buckets, totals, label, "uniques")
                continue

            label = source_by_session.get(session_marker, "Unknown")
            if report.kind == "pageviews":
                _increment_metric(buckets, totals, label, "pageviews")
            elif report.kind == "conversions":
                _increment_metric(buckets, totals, label, "conversions")
            if visitor_marker and visitor_marker not in seen_visitors_by_label[label]:
                seen_visitors_by_label[label].add(visitor_marker)
                _increment_metric(buckets, totals, label, "uniques")
            continue

        label = _resolve_label(dimension, payload, label_timestamp)
        if report.kind == "pageviews":
            _increment_metric(buckets, totals, label, "pageviews")
        elif report.kind == "sessions":
            if session_marker:
                if session_marker not in seen_sessions_by_label[label]:
                    seen_sessions_by_label[label].add(session_marker)
                    _increment_metric(buckets, totals, label, "sessions")
            else:
                _increment_metric(buckets, totals, label, "sessions")
        elif report.kind == "conversions":
            _increment_metric(buckets, totals, label, "conversions")
            if dimension == "conversions":
                if session_marker:
                    if session_marker not in seen_sessions_by_label[label]:
                        seen_sessions_by_label[label].add(session_marker)
                        _increment_metric(buckets, totals, label, "sessions")
                else:
                    _increment_metric(buckets, totals, label, "sessions")
        elif report.kind == "revenue" and dimension == "hostnames":
            value = _raw_report_value(report)
            if value > 0:
                buckets[label]["revenue"] += value
                totals["revenue"] += value
        if visitor_marker and visitor_marker not in seen_visitors_by_label[label]:
            seen_visitors_by_label[label].add(visitor_marker)
            _increment_metric(buckets, totals, label, "uniques")

    min_primary_threshold = BREAKDOWN_MIN_PRIMARY_THRESHOLD[dimension]
    gated_buckets = {
        label: metrics
        for label, metrics in buckets.items()
        if metrics.get(primary_metric, 0.0) >= min_primary_threshold
    }
    if dimension in TIME_PARTING_DIMENSIONS:
        gated_buckets = {
            label: metrics for label, metrics in gated_buckets.items() if metrics.get("sessions", 0.0) >= TIME_PARTING_MIN_SESSIONS
        }
    if min_primary_threshold > 0:
        if not gated_buckets:
            return _empty_breakdown_response(
                site_id=site_id,
                dimension=dimension,
                primary_metric=primary_metric,
                metric_keys=metric_keys,
            )
        buckets = defaultdict(lambda: _blank_metric_map(metric_keys), gated_buckets)
        totals = _blank_metric_map(metric_keys)
        for metrics in buckets.values():
            for metric in metric_keys:
                totals[metric] += metrics.get(metric, 0.0)

    ordered = _ordered_buckets(dimension, dict(buckets), primary_metric, limit)
    rows = [
        BreakdownRow(
            label=label,
            value=metrics.get(primary_metric, 0.0),
            metrics={metric: metrics.get(metric, 0.0) for metric in metric_keys},
        )
        for label, metrics in ordered
    ]
    return BreakdownResponse(
        site_id=site_id,
        dimension=dimension,
        total=totals.get(primary_metric, 0.0),
        primary_metric=primary_metric,
        metric_keys=list(metric_keys),
        totals={metric: totals.get(metric, 0.0) for metric in metric_keys},
        rows=rows,
    )
