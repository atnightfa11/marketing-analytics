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
settings = get_settings()


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
        "external": "External",
        "organic": "Organic",
        "referral": "Referral",
        "social": "Social",
        "email": "Email",
        "paid": "Paid",
    }
    return mapping.get(value, "Unknown")


def _normalize_source_label(raw_value: object) -> str:
    if not isinstance(raw_value, str):
        return "Unknown"
    value = raw_value.strip().lower()
    if not value:
        return "Unknown"
    if value == "direct":
        return "Direct"
    return value[:120]


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
        return BreakdownResponse(site_id=site_id, dimension=dimension, total=0.0, rows=[])

    start_day, end_day = _resolve_window(start, end)
    if dimension == "sources":
        report_kind = "sessions"
    elif dimension == "conversions":
        report_kind = "conversions"
    else:
        report_kind = "pageviews"
    stmt = (
        select(RawReport)
        .where(RawReport.site_id == site_id, RawReport.kind == report_kind)
        .where(RawReport.day >= start_day, RawReport.day <= end_day)
        .order_by(RawReport.server_received_at, RawReport.id)
    )
    reports = (await session.execute(stmt)).scalars().all()

    buckets: dict[str, float] = defaultdict(float)
    seen_session_markers: set[tuple[dt.datetime, str]] = set()
    total = 0.0
    for report in reports:
        payload = report.payload if isinstance(report.payload, dict) else {}
        if payload.get("historical_import"):
            continue
        if dimension == "sources":
            session_hmac = payload.get("_session_hmac")
            if isinstance(session_hmac, str) and session_hmac:
                marker = (_session_bucket_start(report.server_received_at), session_hmac)
                if marker in seen_session_markers:
                    continue
                seen_session_markers.add(marker)
        label = _resolve_label(dimension, payload)
        buckets[label] += 1.0
        total += 1.0

    ordered = sorted(buckets.items(), key=lambda item: (-item[1], item[0]))[:limit]
    rows = [BreakdownRow(label=label, value=value) for label, value in ordered]
    return BreakdownResponse(site_id=site_id, dimension=dimension, total=total, rows=rows)
