from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import require_dashboard_auth
from ..dependencies import get_site_plan, require_site_access
from ..models import RawReport, get_session
from ..schemas import BreakdownResponse, BreakdownRow

router = APIRouter(tags=["metrics"])
BreakdownDimension = Literal["pages", "sources", "devices", "countries", "conversions", "hour_of_day", "day_of_week"]
BreakdownMetric = Literal["uniques", "sessions", "pageviews", "conversions"]
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
}
BREAKDOWN_PRIMARY_METRIC: dict[BreakdownDimension, BreakdownMetric] = {
    "pages": "pageviews",
    "sources": "sessions",
    "devices": "pageviews",
    "countries": "pageviews",
    "conversions": "conversions",
    "hour_of_day": "sessions",
    "day_of_week": "sessions",
}
BREAKDOWN_REPORT_KINDS: dict[BreakdownDimension, tuple[str, ...]] = {
    "pages": ("pageviews",),
    "sources": ("sessions", "pageviews", "conversions"),
    "devices": ("sessions", "pageviews", "conversions"),
    "countries": ("sessions", "pageviews", "conversions"),
    "conversions": ("conversions",),
    "hour_of_day": ("sessions", "pageviews", "conversions"),
    "day_of_week": ("sessions", "pageviews", "conversions"),
}
TIME_PARTING_DIMENSIONS: set[BreakdownDimension] = {"hour_of_day", "day_of_week"}
TIME_PARTING_MIN_DAYS = 7
TIME_PARTING_MIN_SESSIONS = 10.0
BREAKDOWN_MIN_PRIMARY_THRESHOLD: dict[BreakdownDimension, float] = {
    "pages": 2.0,
    "sources": 2.0,
    "devices": 2.0,
    "countries": 3.0,
    "conversions": 2.0,
    "hour_of_day": TIME_PARTING_MIN_SESSIONS,
    "day_of_week": TIME_PARTING_MIN_SESSIONS,
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


@router.get("/breakdown", response_model=BreakdownResponse)
async def breakdown(
    site_id: str,
    dimension: BreakdownDimension,
    limit: int = Query(default=10, ge=1, le=50),
    start: str | None = None,
    end: str | None = None,
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
    if dimension in TIME_PARTING_DIMENSIONS and _window_days(start_day, end_day) < TIME_PARTING_MIN_DAYS:
        return _empty_breakdown_response(
            site_id=site_id,
            dimension=dimension,
            primary_metric=primary_metric,
            metric_keys=metric_keys,
        )

    report_kinds = BREAKDOWN_REPORT_KINDS[dimension]
    stmt = (
        select(RawReport)
        .where(RawReport.site_id == site_id, RawReport.kind.in_(report_kinds))
        .where(RawReport.day >= start_day, RawReport.day <= end_day)
        .order_by(RawReport.server_received_at, RawReport.id)
    )
    reports = (await session.execute(stmt)).scalars().all()

    buckets: defaultdict[str, dict[str, float]] = defaultdict(lambda: _blank_metric_map(metric_keys))
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
            marker = _session_marker(report.server_received_at, payload)
            if marker and marker not in source_by_session:
                source_by_session[marker] = _resolve_label(dimension, payload, report.server_received_at)

    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
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

        label = _resolve_label(dimension, payload, report.server_received_at)
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
