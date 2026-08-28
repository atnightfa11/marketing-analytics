from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .breakdown_logic import (
    normalize_conversion_event,
    normalize_country_code,
    normalize_device_bucket,
    normalize_page_path,
    normalize_attribution_label,
    normalize_source_bucket,
    normalize_source_label,
    raw_report_value,
    session_marker,
    visitor_marker,
)
from .hostnames import hostname_from_payload, normalize_hostname

SEGMENT_DIMENSIONS = (
    "hostname",
    "channel",
    "source",
    "source_medium",
    "campaign",
    "content",
    "term",
    "country",
    "device",
    "page",
    "conversion_type",
)
SEGMENT_DIMENSION_ALIASES = {
    "goal": "conversion_type",
}
SOURCE_DIMENSIONS = {"channel", "source", "source_medium", "campaign", "content", "term"}
SEGMENT_METRICS = (
    "pageviews",
    "sessions",
    "uniques",
    "conversions",
    "revenue",
    "bounced_sessions",
    "visit_duration_seconds",
)

_BASE_SEGMENT_GRAINS: tuple[tuple[str, ...], ...] = (
    ("channel",),
    ("source",),
    ("source_medium",),
    ("campaign",),
    ("content",),
    ("term",),
    ("country",),
    ("device",),
    ("page",),
    ("conversion_type",),
    ("channel", "country"),
    ("channel", "device"),
    ("channel", "page"),
    ("channel", "conversion_type"),
    ("source", "country"),
    ("source", "device"),
    ("source", "page"),
    ("source", "conversion_type"),
    ("source_medium", "country"),
    ("source_medium", "device"),
    ("source_medium", "page"),
    ("source_medium", "conversion_type"),
    ("source_medium", "campaign"),
    ("campaign", "country"),
    ("campaign", "device"),
    ("campaign", "page"),
    ("campaign", "conversion_type"),
    ("country", "device"),
    ("country", "page"),
    ("country", "conversion_type"),
    ("device", "page"),
    ("device", "conversion_type"),
    ("channel", "country", "device"),
    ("channel", "country", "page"),
    ("channel", "device", "page"),
    ("source_medium", "country", "device"),
    ("source_medium", "country", "page"),
    ("source_medium", "device", "page"),
    ("source_medium", "campaign", "country"),
    ("source_medium", "campaign", "device"),
    ("campaign", "country", "device"),
    ("channel", "country", "device", "conversion_type"),
    ("source_medium", "country", "device", "conversion_type"),
    ("source_medium", "campaign", "country", "device"),
)
SUPPORTED_SEGMENT_GRAINS: tuple[tuple[str, ...], ...] = (
    ("hostname",),
    *_BASE_SEGMENT_GRAINS,
    *(("hostname", *grain) for grain in _BASE_SEGMENT_GRAINS),
)
SUPPORTED_SEGMENT_GRAIN_SET = {grain for grain in SUPPORTED_SEGMENT_GRAINS}

SEARCH_SOURCE_SET = {
    "google",
    "google.com",
    "bing",
    "bing.com",
    "duckduckgo",
    "duckduckgo.com",
    "yahoo",
    "yahoo.com",
    "ecosia",
    "ecosia.org",
    "search.brave.com",
    "baidu.com",
    "yandex.com",
}
AI_ASSISTANT_SOURCE_SET = {
    "chatgpt",
    "chatgpt.com",
    "chat.openai.com",
    "claude",
    "claude.ai",
    "perplexity",
    "perplexity.ai",
    "gemini",
    "gemini.google.com",
    "copilot",
    "copilot.microsoft.com",
}
SOCIAL_SOURCE_SET = {
    "reddit",
    "reddit.com",
    "x",
    "x.com",
    "t.co",
    "linkedin",
    "linkedin.com",
    "facebook",
    "facebook.com",
    "instagram",
    "instagram.com",
    "youtube",
    "youtube.com",
    "tiktok",
    "tiktok.com",
    "threads.net",
    "pinterest.com",
}
EMAIL_SOURCE_SET = {"email", "e-mail", "e_mail", "e mail", "gmail", "newsletter"}
PAID_SEARCH_SOURCE_SET = {"adwords", "bing ads", "bingads", "google ads", "googleads", "microsoft ads", "microsoftads"}
SEARCH_PAID_CLICK_IDS = {"gclid", "gbraid", "wbraid", "msclkid"}
PAID_SIGNAL_PATTERN = re.compile(r"(^|[\s/_-])(cpc|ppc|paid|retargeting|remarketing|sponsored|display|cpm)($|[\s/_-])", re.I)


@dataclass(frozen=True)
class SourceAttributes:
    channel: str
    source: str
    source_medium: str
    campaign: str = "Unknown"
    content: str = "Unknown"
    term: str = "Unknown"


@dataclass(frozen=True)
class SegmentKey:
    grain: str
    hostname: str = ""
    channel: str = ""
    source: str = ""
    source_medium: str = ""
    campaign: str = ""
    content: str = ""
    term: str = ""
    country: str = ""
    device: str = ""
    page: str = ""
    conversion_type: str = ""

    def as_model_kwargs(self) -> dict[str, str]:
        return {
            "grain": self.grain,
            "hostname": self.hostname,
            "channel": self.channel,
            "source": self.source,
            "source_medium": self.source_medium,
            "campaign": self.campaign,
            "content": self.content,
            "term": self.term,
            "country": self.country,
            "device": self.device,
            "page": self.page,
            "conversion_type": self.conversion_type,
        }


def grain_name(dimensions: Iterable[str]) -> str:
    return "+".join(dimensions)


def _normalize_source_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        return ""
    if "://" in normalized:
        try:
            normalized = normalized.split("://", 1)[1]
        except IndexError:
            pass
    host = normalized.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or normalized.replace("www.", "", 1)


def _matches_source_set(value: str, candidates: set[str]) -> bool:
    normalized = _normalize_source_key(value)
    if not normalized:
        return False
    return any(normalized == candidate or normalized.endswith(f".{candidate}") for candidate in candidates)


def _is_explicit_paid_source(value: str) -> bool:
    normalized = value.strip().lower()
    source_key = _normalize_source_key(value)
    return bool(PAID_SIGNAL_PATTERN.search(normalized)) or source_key in PAID_SEARCH_SOURCE_SET


def _channel_from_medium(medium: str, source: str) -> str | None:
    normalized = medium.strip().lower()
    if not normalized or normalized == "unknown":
        return None
    if bool(PAID_SIGNAL_PATTERN.search(normalized)):
        if _matches_source_set(source, SOCIAL_SOURCE_SET):
            return "Paid Social"
        if _matches_source_set(source, SEARCH_SOURCE_SET) or _matches_source_set(source, PAID_SEARCH_SOURCE_SET):
            return "Paid Search"
        return "Paid Other"
    if normalized in {"email", "e-mail", "newsletter"}:
        return "Email"
    if normalized in {"social", "social_media", "social-network", "social-networking"}:
        return "Organic Social"
    if normalized == "organic":
        return "Organic Search" if _matches_source_set(source, SEARCH_SOURCE_SET) else "Organic"
    if normalized in {"referral", "app", "link"}:
        return "Referral"
    return None


def classify_channel_label(raw_label: str, *, bucket: str = "", medium: str = "", paid_click_id: str = "") -> str:
    source = normalize_source_label(raw_label)
    normalized = source.lower()
    raw_normalized = raw_label.strip().lower()
    paid_click = paid_click_id.strip().lower()
    bucket_normalized = bucket.strip().lower()
    if paid_click in SEARCH_PAID_CLICK_IDS:
        return "Paid Search"
    medium_channel = _channel_from_medium(medium, source)
    if medium_channel:
        return medium_channel
    if normalized == "direct":
        return "Direct"
    has_paid_signal = _is_explicit_paid_source(raw_normalized) or _is_explicit_paid_source(normalized)
    if has_paid_signal and (_matches_source_set(normalized, SOCIAL_SOURCE_SET) or _matches_source_set(raw_normalized, SOCIAL_SOURCE_SET)):
        return "Paid Social"
    if has_paid_signal and (
        _matches_source_set(normalized, SEARCH_SOURCE_SET)
        or _normalize_source_key(raw_normalized) in PAID_SEARCH_SOURCE_SET
        or _normalize_source_key(normalized) in PAID_SEARCH_SOURCE_SET
    ):
        return "Paid Search"
    if has_paid_signal:
        return "Paid Other"
    if normalized == "organic" or bucket_normalized == "organic":
        return "Organic Search"
    if normalized == "social" or bucket_normalized == "social":
        return "Organic Social"
    if normalized == "email" or bucket_normalized == "email":
        return "Email"
    if normalized == "paid" or bucket_normalized == "paid":
        return "Paid Other"
    if _matches_source_set(normalized, AI_ASSISTANT_SOURCE_SET) or _matches_source_set(raw_normalized, AI_ASSISTANT_SOURCE_SET):
        return "AI Assistants"

    if _matches_source_set(normalized, SOCIAL_SOURCE_SET) or _matches_source_set(raw_normalized, SOCIAL_SOURCE_SET):
        return "Organic Social"
    if _matches_source_set(normalized, SEARCH_SOURCE_SET) or _matches_source_set(raw_normalized, SEARCH_SOURCE_SET):
        return "Organic Search"
    if normalized in EMAIL_SOURCE_SET or raw_normalized in EMAIL_SOURCE_SET:
        return "Email"
    return "Referral"


def build_source_medium_label(raw_label: str, *, channel: str, medium: str = "Unknown", paid_click_id: str = "") -> str:
    source = normalize_source_label(raw_label)
    if medium != "Unknown":
        return f"{source}/{medium}"
    if paid_click_id.strip().lower() in SEARCH_PAID_CLICK_IDS:
        return f"{source}/cpc"
    if channel == "Direct":
        return f"{source}/None"
    if channel == "Organic Search":
        return f"{source}/Organic"
    if channel == "Organic Social":
        return f"{source}/Organic Social"
    if channel == "AI Assistants":
        return f"{source}/AI Assistant"
    if channel == "Email":
        return f"{source}/Email"
    if channel == "Paid Search":
        return f"{source}/Paid"
    if channel == "Paid Social":
        return f"{source}/Paid Social"
    if channel == "Paid Other":
        return f"{source}/Paid"
    return f"{source}/Referral"


def source_attributes_from_payload(payload: dict) -> SourceAttributes:
    utm_source = normalize_attribution_label(payload.get("utm_source"), lower=True, limit=120)
    medium = normalize_attribution_label(payload.get("utm_medium"), lower=True, limit=80)
    paid_click_id = normalize_attribution_label(payload.get("paid_click_id"), lower=True, limit=32)
    source = normalize_source_label(utm_source) if utm_source != "Unknown" else normalize_source_label(payload.get("referrer_source"))
    if source == "Unknown":
        source = normalize_source_bucket(payload.get("referrer_bucket"))
    source = normalize_source_label(source)
    if source == "Unknown":
        source = "Referral"
    bucket = payload.get("referrer_bucket") if isinstance(payload.get("referrer_bucket"), str) else ""
    channel = classify_channel_label(source, bucket=bucket, medium=medium, paid_click_id=paid_click_id)
    return SourceAttributes(
        channel=channel,
        source=source,
        source_medium=build_source_medium_label(source, channel=channel, medium=medium, paid_click_id=paid_click_id),
        campaign=normalize_attribution_label(payload.get("utm_campaign"), limit=160),
        content=normalize_attribution_label(payload.get("utm_content"), limit=160),
        term=normalize_attribution_label(payload.get("utm_term"), limit=160),
    )


def normalize_segment_dimension(dimension: str) -> str:
    normalized = SEGMENT_DIMENSION_ALIASES.get(dimension.strip(), dimension.strip())
    if normalized not in SEGMENT_DIMENSIONS:
        raise ValueError(f"unsupported segment dimension: {dimension}")
    return normalized


def normalize_segment_value(dimension: str, value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("segment filter values cannot be blank")
    if dimension == "hostname":
        normalized = normalize_hostname(trimmed)
        if not normalized:
            raise ValueError("hostname segment filter must be a valid host value")
        return normalized[:255]
    if dimension == "source":
        return normalize_source_label(trimmed)[:120]
    if dimension == "source_medium":
        return trimmed[:160]
    if dimension in {"campaign", "content", "term"}:
        return normalize_attribution_label(trimmed, limit=160)[:160]
    if dimension == "channel":
        return trimmed[:120]
    if dimension == "country":
        return normalize_country_code(trimmed)[:32]
    if dimension == "device":
        return normalize_device_bucket(trimmed)[:32]
    if dimension == "page":
        return normalize_page_path(trimmed)[:220]
    if dimension == "conversion_type":
        return normalize_conversion_event(trimmed)[:120]
    return trimmed[:120]


def normalize_segment_filters(filters: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    by_dimension: dict[str, str] = {}
    for raw_dimension, raw_value in filters:
        dimension = normalize_segment_dimension(raw_dimension)
        if dimension in by_dimension:
            raise ValueError(f"duplicate segment dimension: {dimension}")
        by_dimension[dimension] = normalize_segment_value(dimension, raw_value)
    return tuple((dimension, by_dimension[dimension]) for dimension in SEGMENT_DIMENSIONS if dimension in by_dimension)


def resolve_segment_grain(filters: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], tuple[str, ...], str]:
    normalized_filters = normalize_segment_filters(filters)
    dimensions = tuple(dimension for dimension, _value in normalized_filters)
    if not dimensions:
        raise ValueError("at least one segment filter is required")
    if dimensions not in SUPPORTED_SEGMENT_GRAIN_SET:
        readable = ", ".join(dimensions)
        raise ValueError(f"segment combination is not available yet: {readable}")
    return normalized_filters, dimensions, grain_name(dimensions)


def segment_key_from_filters(normalized_filters: Iterable[tuple[str, str]], grain: str) -> SegmentKey:
    values = {dimension: value for dimension, value in normalized_filters}
    return SegmentKey(grain=grain, **{dimension: values.get(dimension, "") for dimension in SEGMENT_DIMENSIONS})


def _event_timestamp(report) -> dt.datetime:
    payload = report.payload if isinstance(report.payload, dict) else {}
    raw_value = payload.get("_client_timestamp")
    if isinstance(raw_value, str) and raw_value:
        try:
            parsed = dt.datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            pass
    timestamp = report.server_received_at
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=dt.timezone.utc)
    return timestamp.astimezone(dt.timezone.utc)


def _dimensions_for_report(report, source_by_session: dict[tuple[dt.datetime, str], SourceAttributes]) -> dict[str, str]:
    payload = report.payload if isinstance(report.payload, dict) else {}
    marker = session_marker(report.server_received_at, payload)
    source_attributes = source_by_session.get(marker) if marker else None
    if source_attributes is None:
        source_attributes = source_attributes_from_payload(payload)

    hostname = hostname_from_payload(payload) or "Unknown"
    return {
        "hostname": hostname[:255],
        "channel": source_attributes.channel[:120],
        "source": source_attributes.source[:120],
        "source_medium": source_attributes.source_medium[:160],
        "campaign": source_attributes.campaign[:160],
        "content": source_attributes.content[:160],
        "term": source_attributes.term[:160],
        "country": normalize_country_code(payload.get("_country_code"))[:32],
        "device": normalize_device_bucket(payload.get("_device_bucket"))[:32],
        "page": normalize_page_path(payload.get("url"))[:220],
        "conversion_type": normalize_conversion_event(payload.get("conversion_type"))[:120],
    }


def _build_source_context(reports: list) -> dict[tuple[dt.datetime, str], SourceAttributes]:
    source_by_session: dict[tuple[dt.datetime, str], SourceAttributes] = {}
    for report in reports:
        if report.kind != "sessions":
            continue
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        marker = session_marker(report.server_received_at, payload)
        if marker and marker not in source_by_session:
            source_by_session[marker] = source_attributes_from_payload(payload)
    return source_by_session


def _build_session_pages(reports: list) -> dict[tuple[dt.datetime, str], set[str]]:
    pages_by_session: defaultdict[tuple[dt.datetime, str], set[str]] = defaultdict(set)
    for report in reports:
        if report.kind != "pageviews":
            continue
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        marker = session_marker(report.server_received_at, payload)
        if marker:
            page = normalize_page_path(payload.get("url"))[:220]
            if page != "Unknown":
                pages_by_session[marker].add(page)
    return pages_by_session


def _report_grain_values(
    *,
    report,
    grain: tuple[str, ...],
    dimensions: dict[str, str],
    pages_by_session: dict[tuple[dt.datetime, str], set[str]],
) -> list[dict[str, str]]:
    payload = report.payload if isinstance(report.payload, dict) else {}
    if report.kind == "uniques" and any(dimension in SOURCE_DIMENSIONS for dimension in grain):
        return []
    if any(dimension in {"campaign", "content", "term"} and dimensions.get(dimension) == "Unknown" for dimension in grain):
        return []
    if "conversion_type" in grain and report.kind not in {"conversions", "revenue"}:
        return []
    if "page" not in grain:
        return [dimensions]
    if report.kind == "pageviews":
        return [] if dimensions["page"] == "Unknown" else [dimensions]
    if report.kind not in {"conversions", "revenue"}:
        return []
    marker = session_marker(report.server_received_at, payload)
    if not marker:
        return []
    pages = pages_by_session.get(marker)
    if not pages:
        return []
    return [{**dimensions, "page": page} for page in pages]


def aggregate_reports_for_segments(reports: list, *, max_gap_seconds: int) -> dict[SegmentKey, dict[str, float]]:
    source_by_session = _build_source_context(reports)
    pages_by_session = _build_session_pages(reports)
    metric_sums: defaultdict[SegmentKey, dict[str, float]] = defaultdict(lambda: {metric: 0.0 for metric in SEGMENT_METRICS})
    session_markers: defaultdict[SegmentKey, set[tuple[dt.datetime, str]]] = defaultdict(set)
    session_fallback_counts: defaultdict[SegmentKey, float] = defaultdict(float)
    visitor_markers: defaultdict[SegmentKey, set[tuple[dt.date, str]]] = defaultdict(set)
    visitor_fallback_counts: defaultdict[SegmentKey, float] = defaultdict(float)
    pageview_times: defaultdict[tuple[SegmentKey, tuple[dt.datetime, str]], list[dt.datetime]] = defaultdict(list)
    touched_keys: set[SegmentKey] = set()

    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        dimensions = _dimensions_for_report(report, source_by_session)
        report_session_marker = session_marker(report.server_received_at, payload)
        report_visitor_marker = visitor_marker(report.day, payload)

        for grain in SUPPORTED_SEGMENT_GRAINS:
            for grain_values in _report_grain_values(
                report=report,
                grain=grain,
                dimensions=dimensions,
                pages_by_session=pages_by_session,
            ):
                key = SegmentKey(
                    grain=grain_name(grain),
                    **{dimension: grain_values[dimension] if dimension in grain else "" for dimension in SEGMENT_DIMENSIONS},
                )
                touched_keys.add(key)
                metrics = metric_sums[key]
                if report.kind == "pageviews":
                    metrics["pageviews"] += 1.0
                    if report_session_marker:
                        pageview_times[(key, report_session_marker)].append(_event_timestamp(report))
                elif report.kind == "conversions":
                    metrics["conversions"] += 1.0
                elif report.kind == "revenue":
                    metrics["revenue"] += raw_report_value(report)

                if report_session_marker:
                    session_markers[key].add(report_session_marker)
                elif report.kind == "sessions":
                    session_fallback_counts[key] += 1.0

                if report_visitor_marker:
                    visitor_markers[key].add(report_visitor_marker)
                elif report.kind == "uniques":
                    visitor_fallback_counts[key] += 1.0

    for key in touched_keys:
        metric_sums[key]["sessions"] = float(len(session_markers[key])) + session_fallback_counts[key]
        metric_sums[key]["uniques"] = float(len(visitor_markers[key])) + visitor_fallback_counts[key]

    for (key, _session), timestamps in pageview_times.items():
        unique_timestamps = sorted(set(timestamps))
        if len(unique_timestamps) == 1:
            metric_sums[key]["bounced_sessions"] += 1.0
            continue
        for previous, current in zip(unique_timestamps, unique_timestamps[1:]):
            gap_seconds = (current - previous).total_seconds()
            if gap_seconds > 0:
                metric_sums[key]["visit_duration_seconds"] += min(gap_seconds, max_gap_seconds)

    return {
        key: {metric: value for metric, value in metrics.items() if value > 0}
        for key, metrics in metric_sums.items()
        if any(value > 0 for value in metrics.values())
    }
