from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import get_settings
from .hostnames import hostname_from_payload
from .schemas import BreakdownResponse, BreakdownRow

BreakdownDimension = Literal[
    "pages",
    "sources",
    "devices",
    "countries",
    "conversions",
    "hour_of_day",
    "day_of_week",
    "hostnames",
]
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
BREAKDOWN_DIMENSIONS: tuple[BreakdownDimension, ...] = tuple(BREAKDOWN_METRIC_ORDER.keys())
TIME_PARTING_DIMENSIONS: set[BreakdownDimension] = {"hour_of_day", "day_of_week"}
TIME_PARTING_STORAGE_DAY_TYPES: tuple[TimePartingDayType, ...] = ("weekday", "weekend")
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


def session_bucket_start(timestamp: dt.datetime) -> dt.datetime:
    bucket_minutes = max(1, settings.SESSION_WINDOW_MINUTES)
    minute = timestamp.minute - (timestamp.minute % bucket_minutes)
    return timestamp.replace(minute=minute, second=0, microsecond=0)


def session_marker(server_received_at: dt.datetime, payload: dict) -> tuple[dt.datetime, str] | None:
    session_hmac = payload.get("_session_hmac")
    if not isinstance(session_hmac, str) or not session_hmac:
        return None
    return session_bucket_start(server_received_at), session_hmac


def visitor_marker(day: dt.date, payload: dict) -> tuple[dt.date, str] | None:
    visitor_hmac = payload.get("_visitor_day_hmac")
    if not isinstance(visitor_hmac, str) or not visitor_hmac:
        return None
    return day, visitor_hmac


def blank_metric_map(metric_keys: tuple[BreakdownMetric, ...]) -> dict[str, float]:
    return {metric: 0.0 for metric in metric_keys}


def increment_metric(
    buckets: defaultdict[str, dict[str, float]],
    totals: dict[str, float],
    label: str,
    metric: BreakdownMetric,
) -> None:
    buckets[label][metric] += 1.0
    totals[metric] += 1.0


def raw_report_value(report) -> float:
    payload = report.payload if isinstance(report.payload, dict) else {}
    try:
        return max(0.0, float(payload.get("value", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def normalize_page_path(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip()
    if not value:
        return "Unknown"

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


def normalize_source_bucket(raw_value: object) -> str:
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


def normalize_host(raw_value: str) -> str:
    value = raw_value.strip().lower()
    if not value:
        return ""
    if "://" in value:
        value = value.split("://", 1)[1]
    host = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_source_label(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().lower()
    if not value:
        return "Unknown"
    if value in {"direct", "(direct)"}:
        return "Direct"
    if value in {"external", "unknown"}:
        return "Referral"

    host = normalize_host(value)
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


def normalize_device_bucket(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().lower()
    mapping = {
        "mobile": "Mobile",
        "desktop": "Desktop",
        "tablet": "Tablet",
    }
    return mapping.get(value, "Unknown")


def normalize_country_code(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().upper()
    if len(value) != 2 or not value.isalpha() or value == "XX":
        return "Unknown"
    return value


def normalize_conversion_event(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip()
    if not value:
        return "Unknown"
    normalized = " ".join(value.replace("_", " ").replace("-", " ").split())
    return normalized.title()[:120] if normalized else "Unknown"


def normalize_hostname_label(payload: dict) -> str:
    host = hostname_from_payload(payload)
    return host if host else "Unknown"


def hour_of_day_label(timestamp: dt.datetime) -> str:
    return HOUR_OF_DAY_LABELS[timestamp.hour]


def day_of_week_label(timestamp: dt.datetime) -> str:
    return DAY_OF_WEEK_LABELS[timestamp.weekday()]


def resolve_label(dimension: BreakdownDimension, payload: dict, server_received_at: dt.datetime) -> str:
    if dimension == "pages":
        return normalize_page_path(payload.get("url"))
    if dimension == "sources":
        source_label = normalize_source_label(payload.get("referrer_source"))
        if source_label != "Unknown":
            return source_label
        return normalize_source_bucket(payload.get("referrer_bucket"))
    if dimension == "devices":
        return normalize_device_bucket(payload.get("_device_bucket"))
    if dimension == "conversions":
        return normalize_conversion_event(payload.get("conversion_type"))
    if dimension == "hostnames":
        return normalize_hostname_label(payload)
    if dimension == "hour_of_day":
        return hour_of_day_label(server_received_at)
    if dimension == "day_of_week":
        return day_of_week_label(server_received_at)
    return normalize_country_code(payload.get("_country_code"))


def ordered_buckets(
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


def window_days(start_day: dt.date, end_day: dt.date) -> int:
    return (end_day - start_day).days + 1


def matches_time_parting_day_type(timestamp: dt.datetime, day_type: TimePartingDayType) -> bool:
    if day_type == "all":
        return True
    is_weekend = timestamp.weekday() >= 5
    return is_weekend if day_type == "weekend" else not is_weekend


def as_utc(timestamp: dt.datetime) -> dt.datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp.astimezone(dt.timezone.utc)


def time_parting_timestamp(timestamp: dt.datetime, payload: dict, site_timezone: str) -> dt.datetime:
    timezone_name = payload.get("_timezone_hint")
    if not isinstance(timezone_name, str) or not timezone_name:
        timezone_name = site_timezone or "UTC"
    try:
        return as_utc(timestamp).astimezone(ZoneInfo(timezone_name))
    except (ZoneInfoNotFoundError, ValueError):
        return as_utc(timestamp)


def payload_matches_hostname(payload: dict, hostname_filter: str | None) -> bool:
    if not hostname_filter:
        return True
    payload_hostname = hostname_from_payload(payload)
    if not payload_hostname:
        return False
    return payload_hostname == hostname_filter


def empty_breakdown_response(
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


def aggregate_reports_for_breakdown(
    *,
    reports: list,
    dimension: BreakdownDimension,
    site_timezone: str,
    hostname_filter: str | None = None,
    day_type: TimePartingDayType = "all",
) -> dict[str, dict[str, float]]:
    metric_keys = BREAKDOWN_METRIC_ORDER[dimension]
    buckets: defaultdict[str, dict[str, float]] = defaultdict(lambda: blank_metric_map(metric_keys))
    totals = blank_metric_map(metric_keys)
    seen_sessions_by_label: defaultdict[str, set[tuple[dt.datetime, str]]] = defaultdict(set)
    seen_visitors_by_label: defaultdict[str, set[tuple[dt.date, str]]] = defaultdict(set)
    source_by_session: dict[tuple[dt.datetime, str] | None, str] = {}

    if dimension == "sources":
        for report in reports:
            if report.kind != "sessions":
                continue
            payload = report.payload if isinstance(report.payload, dict) else {}
            if payload.get("historical_import"):
                continue
            if not payload_matches_hostname(payload, hostname_filter):
                continue
            marker = session_marker(report.server_received_at, payload)
            if marker and marker not in source_by_session:
                source_by_session[marker] = resolve_label(dimension, payload, report.server_received_at)

    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        if not payload_matches_hostname(payload, hostname_filter):
            continue
        label_timestamp = report.server_received_at
        if dimension in TIME_PARTING_DIMENSIONS:
            label_timestamp = time_parting_timestamp(report.server_received_at, payload, site_timezone)
        if dimension in TIME_PARTING_DIMENSIONS and not matches_time_parting_day_type(label_timestamp, day_type):
            continue
        report_session_marker = session_marker(report.server_received_at, payload)
        report_visitor_marker = visitor_marker(report.day, payload)

        if dimension == "pages":
            label = resolve_label(dimension, payload, report.server_received_at)
            increment_metric(buckets, totals, label, "pageviews")
            if report_session_marker and report_session_marker not in seen_sessions_by_label[label]:
                seen_sessions_by_label[label].add(report_session_marker)
                increment_metric(buckets, totals, label, "sessions")
            if report_visitor_marker and report_visitor_marker not in seen_visitors_by_label[label]:
                seen_visitors_by_label[label].add(report_visitor_marker)
                increment_metric(buckets, totals, label, "uniques")
            continue

        if dimension == "sources":
            if report.kind == "sessions":
                label = source_by_session.get(
                    report_session_marker,
                    resolve_label(dimension, payload, report.server_received_at),
                )
                if report_session_marker:
                    if report_session_marker not in seen_sessions_by_label[label]:
                        seen_sessions_by_label[label].add(report_session_marker)
                        increment_metric(buckets, totals, label, "sessions")
                else:
                    increment_metric(buckets, totals, label, "sessions")
                if report_visitor_marker and report_visitor_marker not in seen_visitors_by_label[label]:
                    seen_visitors_by_label[label].add(report_visitor_marker)
                    increment_metric(buckets, totals, label, "uniques")
                continue

            label = source_by_session.get(report_session_marker, "Unknown")
            if report.kind == "pageviews":
                increment_metric(buckets, totals, label, "pageviews")
            elif report.kind == "conversions":
                increment_metric(buckets, totals, label, "conversions")
            if report_visitor_marker and report_visitor_marker not in seen_visitors_by_label[label]:
                seen_visitors_by_label[label].add(report_visitor_marker)
                increment_metric(buckets, totals, label, "uniques")
            continue

        label = resolve_label(dimension, payload, label_timestamp)
        if report.kind == "pageviews":
            increment_metric(buckets, totals, label, "pageviews")
        elif report.kind == "sessions":
            if report_session_marker:
                if report_session_marker not in seen_sessions_by_label[label]:
                    seen_sessions_by_label[label].add(report_session_marker)
                    increment_metric(buckets, totals, label, "sessions")
            else:
                increment_metric(buckets, totals, label, "sessions")
        elif report.kind == "conversions":
            increment_metric(buckets, totals, label, "conversions")
            if dimension == "conversions":
                if report_session_marker:
                    if report_session_marker not in seen_sessions_by_label[label]:
                        seen_sessions_by_label[label].add(report_session_marker)
                        increment_metric(buckets, totals, label, "sessions")
                else:
                    increment_metric(buckets, totals, label, "sessions")
        elif report.kind == "revenue" and dimension == "hostnames":
            value = raw_report_value(report)
            if value > 0:
                buckets[label]["revenue"] += value
                totals["revenue"] += value
        if report_visitor_marker and report_visitor_marker not in seen_visitors_by_label[label]:
            seen_visitors_by_label[label].add(report_visitor_marker)
            increment_metric(buckets, totals, label, "uniques")

    return dict(buckets)


def build_breakdown_response_from_buckets(
    *,
    site_id: str,
    dimension: BreakdownDimension,
    buckets: dict[str, dict[str, float]],
    limit: int,
) -> BreakdownResponse:
    metric_keys = BREAKDOWN_METRIC_ORDER[dimension]
    primary_metric = BREAKDOWN_PRIMARY_METRIC[dimension]
    min_primary_threshold = BREAKDOWN_MIN_PRIMARY_THRESHOLD[dimension]
    gated_buckets = {
        label: metrics
        for label, metrics in buckets.items()
        if metrics.get(primary_metric, 0.0) >= min_primary_threshold
    }
    if dimension in TIME_PARTING_DIMENSIONS:
        gated_buckets = {
            label: metrics
            for label, metrics in gated_buckets.items()
            if metrics.get("sessions", 0.0) >= TIME_PARTING_MIN_SESSIONS
        }
    if min_primary_threshold > 0:
        if not gated_buckets:
            return empty_breakdown_response(
                site_id=site_id,
                dimension=dimension,
                primary_metric=primary_metric,
                metric_keys=metric_keys,
            )
        buckets = gated_buckets

    totals = blank_metric_map(metric_keys)
    for metrics in buckets.values():
        for metric in metric_keys:
            totals[metric] += metrics.get(metric, 0.0)

    ordered = ordered_buckets(dimension, buckets, primary_metric, limit)
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
