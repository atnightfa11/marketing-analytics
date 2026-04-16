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
from ..dependencies import get_site_plan
from ..models import RawReport, get_session
from ..schemas import BreakdownResponse, BreakdownRow

router = APIRouter(tags=["metrics"])
BreakdownDimension = Literal["pages", "sources", "devices", "countries", "conversions"]
BreakdownMetric = Literal["uniques", "sessions", "pageviews", "conversions"]
settings = get_settings()

BREAKDOWN_METRIC_ORDER: dict[BreakdownDimension, tuple[BreakdownMetric, ...]] = {
    "pages": ("uniques", "sessions", "pageviews"),
    "sources": ("uniques", "sessions", "pageviews", "conversions"),
    "devices": ("uniques", "sessions", "pageviews", "conversions"),
    "countries": ("uniques", "sessions", "pageviews", "conversions"),
    "conversions": ("uniques", "sessions", "conversions"),
}
BREAKDOWN_PRIMARY_METRIC: dict[BreakdownDimension, BreakdownMetric] = {
    "pages": "pageviews",
    "sources": "sessions",
    "devices": "pageviews",
    "countries": "pageviews",
    "conversions": "conversions",
}
BREAKDOWN_REPORT_KINDS: dict[BreakdownDimension, tuple[str, ...]] = {
    "pages": ("pageviews",),
    "sources": ("sessions", "pageviews", "conversions"),
    "devices": ("sessions", "pageviews", "conversions"),
    "countries": ("sessions", "pageviews", "conversions"),
    "conversions": ("conversions",),
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


def _resolve_label(dimension: BreakdownDimension, payload: dict) -> str:
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
    return _normalize_country_code(payload.get("_country_code"))


@router.get("/breakdown", response_model=BreakdownResponse)
async def breakdown(
    site_id: str,
    dimension: BreakdownDimension,
    limit: int = Query(default=10, ge=1, le=50),
    start: str | None = None,
    end: str | None = None,
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
):
    # Pro ingest currently does not retain raw per-dimension event context.
    if plan == "pro":
        return BreakdownResponse(
            site_id=site_id,
            dimension=dimension,
            total=0.0,
            primary_metric=BREAKDOWN_PRIMARY_METRIC[dimension],
            metric_keys=list(BREAKDOWN_METRIC_ORDER[dimension]),
            totals={metric: 0.0 for metric in BREAKDOWN_METRIC_ORDER[dimension]},
            rows=[],
        )

    start_day, end_day = _resolve_window(start, end)
    report_kinds = BREAKDOWN_REPORT_KINDS[dimension]
    metric_keys = BREAKDOWN_METRIC_ORDER[dimension]
    primary_metric = BREAKDOWN_PRIMARY_METRIC[dimension]
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
                source_by_session[marker] = _resolve_label(dimension, payload)

    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        session_marker = _session_marker(report.server_received_at, payload)
        visitor_marker = _visitor_marker(report.day, payload)

        if dimension == "pages":
            label = _resolve_label(dimension, payload)
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
                label = source_by_session.get(session_marker, _resolve_label(dimension, payload))
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

        label = _resolve_label(dimension, payload)
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

    ordered = sorted(
        buckets.items(),
        key=lambda item: (-item[1].get(primary_metric, 0.0), item[0]),
    )[:limit]
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
