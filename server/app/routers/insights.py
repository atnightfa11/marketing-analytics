from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import breakdown_logic
from ..dashboard_auth import require_dashboard_auth
from ..dependencies import get_site_plan, require_site_access
from ..entitlements import enforce_aggregate_retention
from ..models import BreakdownRollup, DashboardNote, DashboardSite, DpWindow, RawReport, ReducerWatermark, get_session
from ..scheduler.nightly_reduce import REDUCER_VERSION
from ..schemas import InsightItem, InsightsResponse

router = APIRouter(tags=["metrics"])

Metric = Literal["pageviews", "uniques", "sessions", "conversions", "revenue"]
Dimension = Literal["sources", "pages", "devices", "countries", "conversions"]
InsightDimension = Literal["channels", "sources", "pages", "devices", "countries", "conversions"]

METRICS: tuple[Metric, ...] = ("pageviews", "uniques", "sessions", "conversions", "revenue")
STORED_INSIGHT_DIMENSIONS: tuple[Dimension, ...] = ("sources", "pages", "devices", "countries", "conversions")
INSIGHT_DIMENSIONS: tuple[InsightDimension, ...] = ("channels", "sources", "pages", "devices", "countries", "conversions")
DEFAULT_DAYS = 30
MAX_DAYS = 180
MAX_INSIGHTS = 5
MIN_CONTRIBUTION_SHARE = 0.28
MIN_RELATIVE_CHANGE = 0.08
MIN_TOTAL_VOLUME: dict[str, float] = {
    "pageviews": 50.0,
    "uniques": 25.0,
    "sessions": 25.0,
    "conversions": 3.0,
    "revenue": 1.0,
}
MIN_ROW_DELTA: dict[str, float] = {
    "pageviews": 10.0,
    "uniques": 5.0,
    "sessions": 5.0,
    "conversions": 2.0,
    "revenue": 1.0,
}

METRIC_LABELS = {
    "pageviews": "Pageviews",
    "uniques": "Unique visitors",
    "sessions": "Sessions",
    "conversions": "Goal completions",
    "revenue": "Revenue",
}
DIMENSION_LABELS = {
    "channels": "Channel",
    "sources": "Traffic source",
    "pages": "Page",
    "devices": "Device",
    "countries": "Country",
    "conversions": "Goal completion",
}
DIMENSION_PHRASES = {
    "channels": "channel",
    "sources": "traffic source",
    "pages": "page",
    "devices": "device type",
    "countries": "country",
    "conversions": "goal completion type",
}

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
    "openai.com",
}
SOCIAL_SOURCE_SET = {
    "reddit",
    "reddit.com",
    "x",
    "x.com",
    "t.co",
    "twitter",
    "twitter.com",
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
PAID_SIGNAL_TOKENS = {"cpc", "ppc", "paid", "retargeting", "remarketing", "sponsored", "display", "cpm"}


def _day_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)


def _enumerate_days(start_day: dt.date, end_day: dt.date) -> list[dt.date]:
    return [start_day + dt.timedelta(days=offset) for offset in range((end_day - start_day).days + 1)]


def _resolve_window(start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    if start and end:
        start_day, end_day = (start, end) if start <= end else (end, start)
    elif start:
        start_day = end_day = start
    elif end:
        start_day = end_day = end
    else:
        end_day = dt.datetime.now(dt.timezone.utc).date()
        start_day = end_day - dt.timedelta(days=DEFAULT_DAYS - 1)

    day_count = (end_day - start_day).days + 1
    if day_count > MAX_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"insight range cannot exceed {MAX_DAYS} days",
        )
    return start_day, end_day


def _previous_window(start_day: dt.date, end_day: dt.date) -> tuple[dt.date, dt.date]:
    day_count = (end_day - start_day).days + 1
    compare_end = start_day - dt.timedelta(days=1)
    compare_start = compare_end - dt.timedelta(days=day_count - 1)
    return compare_start, compare_end


def _normalize_metric(metric: str) -> Metric:
    if metric in METRICS:
        return metric  # type: ignore[return-value]
    if metric in {"avg_pages_per_visit", "bounce_rate", "visit_duration"}:
        return "sessions"
    return "sessions"


def _format_value(metric: str, value: float) -> str:
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if metric == "revenue":
        if abs_value >= 1_000_000:
            return f"{sign}${abs_value / 1_000_000:.1f}M"
        if abs_value >= 1_000:
            return f"{sign}${abs_value / 1_000:.1f}K"
        return f"{sign}${round(abs_value):,.0f}"
    if abs_value >= 1_000_000:
        return f"{sign}{abs_value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{sign}{abs_value / 1_000:.1f}K"
    return f"{sign}{round(abs_value):,.0f}"


def _format_percent(value: float) -> str:
    return f"{round(value * 100):.0f}%"


def _format_day(day: dt.date) -> str:
    return f"{day.strftime('%b')} {day.day}"


def _format_day_ranges(days: list[dt.date]) -> str:
    if not days:
        return "selected days"
    ranges: list[tuple[dt.date, dt.date]] = []
    start = days[0]
    end = days[0]
    for day in days[1:]:
        if day == end + dt.timedelta(days=1):
            end = day
            continue
        ranges.append((start, end))
        start = end = day
    ranges.append((start, end))
    parts = [_format_day(start) if start == end else f"{_format_day(start)}-{_format_day(end)}" for start, end in ranges]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return " and ".join(parts)
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " ").title())


def _metric_keys_for_dimension(dimension: InsightDimension) -> tuple[str, ...]:
    if dimension == "channels":
        return breakdown_logic.BREAKDOWN_METRIC_ORDER["sources"]
    return breakdown_logic.BREAKDOWN_METRIC_ORDER[dimension]


def _primary_metric_for_dimension(dimension: InsightDimension) -> str:
    if dimension == "channels":
        return breakdown_logic.BREAKDOWN_PRIMARY_METRIC["sources"]
    return breakdown_logic.BREAKDOWN_PRIMARY_METRIC[dimension]


def _source_key(label: str) -> str:
    value = label.strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    return value


def _matches_source_set(label: str, candidates: set[str]) -> bool:
    value = _source_key(label)
    return any(value == candidate or value.endswith(f".{candidate}") for candidate in candidates)


def _has_paid_signal(label: str) -> bool:
    value = label.strip().lower()
    source_key = _source_key(value)
    normalized = " ".join(value.replace("_", " ").replace("-", " ").replace("/", " ").split())
    tokens = set(normalized.split())
    return source_key in PAID_SEARCH_SOURCE_SET or bool(tokens & PAID_SIGNAL_TOKENS)


def _classify_channel_label(label: str) -> str:
    normalized = label.strip().lower()
    if not normalized or normalized in {"unknown", "referral"}:
        return "Referral"
    if normalized == "direct":
        return "Direct"
    if normalized == "organic":
        return "Organic Search"
    if normalized == "social":
        return "Organic Social"
    if normalized == "email":
        return "Email"
    if normalized == "ai":
        return "AI Assistants"
    if _matches_source_set(normalized, AI_ASSISTANT_SOURCE_SET):
        return "AI Assistants"
    is_paid = _has_paid_signal(normalized)
    if is_paid and _matches_source_set(normalized, SOCIAL_SOURCE_SET):
        return "Paid Social"
    if is_paid and (_matches_source_set(normalized, SEARCH_SOURCE_SET) or _source_key(normalized) in PAID_SEARCH_SOURCE_SET):
        return "Paid Search"
    if is_paid:
        return "Paid Other"
    if _matches_source_set(normalized, SOCIAL_SOURCE_SET):
        return "Organic Social"
    if _matches_source_set(normalized, SEARCH_SOURCE_SET):
        return "Organic Search"
    if normalized in EMAIL_SOURCE_SET:
        return "Email"
    return "Referral"


def _clip_note_body(body: str, limit: int = 160) -> str:
    cleaned = " ".join(body.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}..."


def _blank_bucket(dimension: Dimension) -> dict[str, float]:
    return breakdown_logic.blank_metric_map(breakdown_logic.BREAKDOWN_METRIC_ORDER[dimension])


def _merge_buckets(
    target: defaultdict[str, dict[str, float]],
    source: dict[str, dict[str, float]],
    dimension: Dimension,
) -> None:
    metric_keys = breakdown_logic.BREAKDOWN_METRIC_ORDER[dimension]
    for label, metrics in source.items():
        for metric in metric_keys:
            target[label][metric] += metrics.get(metric, 0.0)


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


async def _metric_totals(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    start_day: dt.date,
    end_day: dt.date,
) -> dict[str, float]:
    rows = (
        await session.execute(
            select(DpWindow.metric, func.sum(DpWindow.value))
            .where(
                DpWindow.site_id == site_id,
                DpWindow.plan == plan,
                DpWindow.metric.in_(METRICS),
                DpWindow.window_start >= _day_start(start_day),
                DpWindow.window_start < _day_start(end_day + dt.timedelta(days=1)),
            )
            .group_by(DpWindow.metric)
        )
    ).all()
    totals = {metric: 0.0 for metric in METRICS}
    for metric, value in rows:
        if metric in totals:
            totals[metric] = max(0.0, float(value or 0.0))
    return totals


async def _daily_metric_totals(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    metric: Metric,
    start_day: dt.date,
    end_day: dt.date,
) -> dict[dt.date, float]:
    rows = (
        await session.execute(
            select(func.date(DpWindow.window_start), func.sum(DpWindow.value))
            .where(
                DpWindow.site_id == site_id,
                DpWindow.plan == plan,
                DpWindow.metric == metric,
                DpWindow.window_start >= _day_start(start_day),
                DpWindow.window_start < _day_start(end_day + dt.timedelta(days=1)),
            )
            .group_by(func.date(DpWindow.window_start))
        )
    ).all()
    daily = {day: 0.0 for day in _enumerate_days(start_day, end_day)}
    for raw_day, value in rows:
        day = raw_day if isinstance(raw_day, dt.date) else dt.date.fromisoformat(str(raw_day))
        daily[day] = max(0.0, float(value or 0.0))
    return daily


async def _aggregate_only_days(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    metric: Metric,
    daily_totals: dict[dt.date, float],
) -> list[dt.date]:
    dimensions = [
        dimension
        for dimension in STORED_INSIGHT_DIMENSIONS
        if metric in breakdown_logic.BREAKDOWN_METRIC_ORDER[dimension]
    ]
    if not dimensions:
        return []
    active_days = [day for day, value in daily_totals.items() if value >= MIN_ROW_DELTA.get(metric, 1.0)]
    if not active_days:
        return []
    rollup_rows = (
        await session.execute(
            select(BreakdownRollup.day, func.count(BreakdownRollup.id), func.sum(BreakdownRollup.value))
            .where(
                BreakdownRollup.site_id == site_id,
                BreakdownRollup.plan == plan,
                BreakdownRollup.metric == metric,
                BreakdownRollup.dimension.in_(dimensions),
                BreakdownRollup.hostname == "",
                BreakdownRollup.day_type == "all",
                BreakdownRollup.day.in_(active_days),
            )
            .group_by(BreakdownRollup.day)
        )
    ).all()
    rollup_coverage = {day: (int(row_count or 0), float(value or 0.0)) for day, row_count, value in rollup_rows}
    aggregate_only: list[dt.date] = []
    for day in active_days:
        row_count, rollup_value = rollup_coverage.get(day, (0, 0.0))
        if row_count == 0 or rollup_value < daily_totals[day] * 0.1:
            aggregate_only.append(day)
    return sorted(aggregate_only)


async def _dimension_buckets(
    *,
    session: AsyncSession,
    site_id: str,
    plan: str,
    dimension: InsightDimension,
    start_day: dt.date,
    end_day: dt.date,
) -> dict[str, dict[str, float]]:
    if plan == "pro":
        return {}
    if dimension == "channels":
        source_buckets = await _dimension_buckets(
            session=session,
            site_id=site_id,
            plan=plan,
            dimension="sources",
            start_day=start_day,
            end_day=end_day,
        )
        channel_buckets: defaultdict[str, dict[str, float]] = defaultdict(lambda: _blank_bucket("sources"))
        metric_keys = breakdown_logic.BREAKDOWN_METRIC_ORDER["sources"]
        for source_label, metrics in source_buckets.items():
            channel = _classify_channel_label(source_label)
            for metric in metric_keys:
                channel_buckets[channel][metric] += metrics.get(metric, 0.0)
        return dict(channel_buckets)

    all_days = set(_enumerate_days(start_day, end_day))
    reduced_days = await _successful_reduced_days(
        session=session,
        site_id=site_id,
        plan=plan,
        start_day=start_day,
        end_day=end_day,
    )
    unreduced_days = all_days - reduced_days
    buckets: defaultdict[str, dict[str, float]] = defaultdict(lambda: _blank_bucket(dimension))

    if reduced_days:
        metric_keys = breakdown_logic.BREAKDOWN_METRIC_ORDER[dimension]
        rollups = (
            await session.execute(
                select(BreakdownRollup).where(
                    BreakdownRollup.site_id == site_id,
                    BreakdownRollup.plan == plan,
                    BreakdownRollup.dimension == dimension,
                    BreakdownRollup.day.in_(reduced_days),
                    BreakdownRollup.hostname == "",
                    BreakdownRollup.day_type == "all",
                )
            )
        ).scalars().all()
        for rollup in rollups:
            if rollup.metric in metric_keys:
                buckets[rollup.label][rollup.metric] += max(0.0, rollup.value)

    if unreduced_days:
        site = await session.get(DashboardSite, site_id)
        site_timezone = site.timezone if site and site.timezone else "UTC"
        reports = (
            await session.execute(
                select(RawReport)
                .where(
                    RawReport.site_id == site_id,
                    RawReport.kind.in_(breakdown_logic.BREAKDOWN_REPORT_KINDS[dimension]),
                    RawReport.day.in_(unreduced_days),
                )
                .order_by(RawReport.server_received_at, RawReport.id)
            )
        ).scalars().all()
        raw_buckets = breakdown_logic.aggregate_reports_for_breakdown(
            reports=list(reports),
            dimension=dimension,
            site_timezone=site_timezone,
        )
        _merge_buckets(buckets, raw_buckets, dimension)

    return dict(buckets)


def _best_dimension_driver(
    *,
    selected_metric: Metric,
    dimension: InsightDimension,
    current_totals: dict[str, float],
    previous_totals: dict[str, float],
    current_buckets: dict[str, dict[str, float]],
    previous_buckets: dict[str, dict[str, float]],
) -> InsightItem | None:
    metric_keys = _metric_keys_for_dimension(dimension)
    metric = selected_metric if selected_metric in metric_keys else _primary_metric_for_dimension(dimension)
    current_total = current_totals.get(metric, 0.0)
    previous_total = previous_totals.get(metric, 0.0)
    total_delta = current_total - previous_total
    total_baseline = max(current_total, previous_total)
    if total_baseline < MIN_TOTAL_VOLUME.get(metric, 10.0):
        return None
    if abs(total_delta) < MIN_ROW_DELTA.get(metric, 5.0):
        return None
    if previous_total > 0 and abs(total_delta / previous_total) < MIN_RELATIVE_CHANGE:
        return None

    direction = 1 if total_delta > 0 else -1
    labels = set(current_buckets) | set(previous_buckets)
    candidates: list[tuple[float, float, str, float, float]] = []
    for label in labels:
        current_value = current_buckets.get(label, {}).get(metric, 0.0)
        previous_value = previous_buckets.get(label, {}).get(metric, 0.0)
        row_delta = current_value - previous_value
        if row_delta == 0 or (row_delta > 0) != (direction > 0):
            continue
        if abs(row_delta) < MIN_ROW_DELTA.get(metric, 5.0):
            continue
        if max(current_value, previous_value) < MIN_ROW_DELTA.get(metric, 5.0):
            continue
        contribution_share = min(1.0, abs(row_delta) / max(abs(total_delta), 1.0))
        if contribution_share < MIN_CONTRIBUTION_SHARE:
            continue
        candidates.append((contribution_share, abs(row_delta), label, current_value, previous_value))

    if not candidates:
        return None

    contribution_share, _abs_delta, label, current_value, previous_value = sorted(
        candidates,
        key=lambda item: (-item[0], -item[1], item[2]),
    )[0]
    row_delta = current_value - previous_value
    metric_label = _metric_label(metric)
    total_change_word = "up" if total_delta > 0 else "down"
    row_change_word = "added" if row_delta > 0 else "lost"
    effect_word = "lift" if total_delta > 0 else "decline"
    severity: Literal["info", "warning", "success"] = "success" if total_delta > 0 else "warning"
    change = _format_percent(abs(total_delta / previous_total)) if previous_total > 0 else _format_value(metric, abs(total_delta))
    return InsightItem(
        type="change_driver",
        severity=severity,
        label=DIMENSION_LABELS[dimension],
        text=(
            f"{label} accounted for {_format_percent(contribution_share)} of the {metric_label.lower()} {effect_word}. "
            f"{metric_label} are {total_change_word} {change} vs the prior period; this "
            f"{DIMENSION_PHRASES[dimension]} {row_change_word} {_format_value(metric, abs(row_delta))}."
        ),
        metric=metric,
        dimension=dimension,
        driver=label,
        contribution_share=contribution_share,
    )


def _conversion_rate_insight(
    current_totals: dict[str, float],
    previous_totals: dict[str, float],
) -> InsightItem | None:
    current_sessions = current_totals.get("sessions", 0.0)
    previous_sessions = previous_totals.get("sessions", 0.0)
    current_conversions = current_totals.get("conversions", 0.0)
    previous_conversions = previous_totals.get("conversions", 0.0)
    if min(current_sessions, previous_sessions) < 25 or max(current_conversions, previous_conversions) < 3:
        return None
    current_rate = current_conversions / current_sessions
    previous_rate = previous_conversions / previous_sessions
    if previous_rate <= 0:
        return None
    rate_delta = current_rate - previous_rate
    relative_delta = rate_delta / previous_rate
    if abs(relative_delta) < 0.15:
        return None
    sessions_delta = current_sessions - previous_sessions
    conversions_delta = current_conversions - previous_conversions
    direction = "improved" if rate_delta > 0 else "softened"
    severity: Literal["info", "warning", "success"] = "success" if rate_delta > 0 else "warning"
    return InsightItem(
        type="conversion_rate_shift",
        severity=severity,
        label="Conversion rate",
        text=(
            f"Goal completion rate {direction} from {_format_percent(previous_rate)} to {_format_percent(current_rate)}. "
            f"Sessions changed by {_format_value('sessions', sessions_delta)} while goal completions changed by "
            f"{_format_value('conversions', conversions_delta)}."
        ),
        metric="conversions",
        dimension="conversions",
    )


def _aggregate_only_insight(
    *,
    metric: Metric,
    current_totals: dict[str, float],
    previous_totals: dict[str, float],
    current_daily: dict[dt.date, float],
    current_aggregate_only_days: list[dt.date],
    previous_aggregate_only_days: list[dt.date],
) -> InsightItem | None:
    if not current_aggregate_only_days and not previous_aggregate_only_days:
        return None
    current_value = current_totals.get(metric, 0.0)
    previous_value = previous_totals.get(metric, 0.0)
    total_delta = current_value - previous_value
    if current_value < MIN_TOTAL_VOLUME.get(metric, 10.0) or abs(total_delta) < MIN_ROW_DELTA.get(metric, 5.0):
        return None
    if previous_value > 0 and abs(total_delta / previous_value) < MIN_RELATIVE_CHANGE:
        return None
    aggregate_only_total = sum(current_daily.get(day, 0.0) for day in current_aggregate_only_days)
    if aggregate_only_total < max(MIN_ROW_DELTA.get(metric, 5.0), abs(total_delta) * 0.25):
        if not previous_aggregate_only_days:
            return None
    metric_label = _metric_label(metric)
    direction = "up" if total_delta >= 0 else "down"
    change = _format_percent(abs(total_delta / previous_value)) if previous_value > 0 else _format_value(metric, abs(total_delta))
    share = min(1.0, aggregate_only_total / max(abs(total_delta), 1.0))
    if current_aggregate_only_days:
        period_phrase = (
            f"with a large part of the current period concentrated on {_format_day_ranges(current_aggregate_only_days)}"
        )
    else:
        period_phrase = f"and the comparison period has aggregate-only days on {_format_day_ranges(previous_aggregate_only_days)}"
    return InsightItem(
        type="attribution_limited",
        severity="warning",
        label="Attribution",
        text=(
            f"{metric_label} are {direction} {change} vs the prior period, {period_phrase}. "
            "Those days have aggregate KPI data without matching breakdowns, so Valid can show the change but not attribute it."
        ),
        metric=metric,
        contribution_share=share,
    )


async def _note_context_insight(
    *,
    session: AsyncSession,
    site_id: str,
    metric: Metric,
    start_day: dt.date,
    end_day: dt.date,
    highlighted_days: list[dt.date],
) -> InsightItem | None:
    stmt = (
        select(DashboardNote)
        .where(
            DashboardNote.site_id == site_id,
            DashboardNote.day >= start_day,
            DashboardNote.day <= end_day,
        )
        .order_by(DashboardNote.day.desc(), DashboardNote.created_at.desc())
        .limit(25)
    )
    notes = (await session.execute(stmt)).scalars().all()
    relevant_notes = [note for note in notes if note.metric in (None, metric)]
    if highlighted_days:
        highlighted = set(highlighted_days)
        relevant_notes = [note for note in relevant_notes if note.day in highlighted]
    if not relevant_notes:
        return None
    note = relevant_notes[0]
    return InsightItem(
        type="annotation",
        severity="info",
        label="Note",
        text=f"{_format_day(note.day)} note: {_clip_note_body(note.body)}",
        metric=metric,
    )


def _metric_change_insight(metric: Metric, current_totals: dict[str, float], previous_totals: dict[str, float]) -> InsightItem | None:
    current_value = current_totals.get(metric, 0.0)
    previous_value = previous_totals.get(metric, 0.0)
    metric_label = _metric_label(metric)
    total_baseline = max(current_value, previous_value)
    if total_baseline < MIN_TOTAL_VOLUME.get(metric, 10.0):
        return None
    if previous_value > 0:
        delta_pct = (current_value - previous_value) / previous_value
        if abs(delta_pct) >= MIN_RELATIVE_CHANGE:
            return InsightItem(
                type="metric_change",
                label="Trend",
                text=(
                    f"{metric_label} are {'up' if delta_pct >= 0 else 'down'} {_format_percent(abs(delta_pct))} "
                    "vs the prior period."
                ),
                metric=metric,
            )
    return None


@router.get("/insights", response_model=InsightsResponse)
async def insights(
    site_id: str,
    metric: str = Query(default="sessions"),
    start: dt.date | None = None,
    end: dt.date | None = None,
    compare_start: dt.date | None = None,
    compare_end: dt.date | None = None,
    _auth_claims: dict | None = Depends(require_dashboard_auth),
    _site_access: None = Depends(require_site_access),
    plan: str = Depends(get_site_plan),
    session: AsyncSession = Depends(get_session),
) -> InsightsResponse:
    start_day, end_day = _resolve_window(start, end)
    if compare_start and compare_end:
        compare_start_day, compare_end_day = (
            (compare_start, compare_end) if compare_start <= compare_end else (compare_end, compare_start)
        )
    else:
        compare_start_day, compare_end_day = _previous_window(start_day, end_day)

    enforce_aggregate_retention(plan, start_day, end_day)
    enforce_aggregate_retention(plan, compare_start_day, compare_end_day)
    selected_metric = _normalize_metric(metric)
    current_totals = await _metric_totals(
        session=session,
        site_id=site_id,
        plan=plan,
        start_day=start_day,
        end_day=end_day,
    )
    previous_totals = await _metric_totals(
        session=session,
        site_id=site_id,
        plan=plan,
        start_day=compare_start_day,
        end_day=compare_end_day,
    )
    current_daily = await _daily_metric_totals(
        session=session,
        site_id=site_id,
        plan=plan,
        metric=selected_metric,
        start_day=start_day,
        end_day=end_day,
    )
    aggregate_only = await _aggregate_only_days(
        session=session,
        site_id=site_id,
        plan=plan,
        metric=selected_metric,
        daily_totals=current_daily,
    )
    previous_daily = await _daily_metric_totals(
        session=session,
        site_id=site_id,
        plan=plan,
        metric=selected_metric,
        start_day=compare_start_day,
        end_day=compare_end_day,
    )
    previous_aggregate_only = await _aggregate_only_days(
        session=session,
        site_id=site_id,
        plan=plan,
        metric=selected_metric,
        daily_totals=previous_daily,
    )

    insights_out: list[InsightItem] = []
    limited_attribution = _aggregate_only_insight(
        metric=selected_metric,
        current_totals=current_totals,
        previous_totals=previous_totals,
        current_daily=current_daily,
        current_aggregate_only_days=aggregate_only,
        previous_aggregate_only_days=previous_aggregate_only,
    )
    if limited_attribution is not None:
        insights_out.append(limited_attribution)
    else:
        seen_driver_keys: set[tuple[str | None, str | None]] = set()
        for dimension in INSIGHT_DIMENSIONS:
            current_buckets = await _dimension_buckets(
                session=session,
                site_id=site_id,
                plan=plan,
                dimension=dimension,
                start_day=start_day,
                end_day=end_day,
            )
            previous_buckets = await _dimension_buckets(
                session=session,
                site_id=site_id,
                plan=plan,
                dimension=dimension,
                start_day=compare_start_day,
                end_day=compare_end_day,
            )
            insight = _best_dimension_driver(
                selected_metric=selected_metric,
                dimension=dimension,
                current_totals=current_totals,
                previous_totals=previous_totals,
                current_buckets=current_buckets,
                previous_buckets=previous_buckets,
            )
            if insight is not None:
                driver_key = (insight.metric, insight.driver)
                if driver_key in seen_driver_keys:
                    continue
                seen_driver_keys.add(driver_key)
                insights_out.append(insight)

        conversion_rate = _conversion_rate_insight(current_totals, previous_totals)
        if conversion_rate is not None:
            insights_out.append(conversion_rate)

    note_context = await _note_context_insight(
        session=session,
        site_id=site_id,
        metric=selected_metric,
        start_day=start_day,
        end_day=end_day,
        highlighted_days=aggregate_only,
    )
    if note_context is not None:
        insights_out.append(note_context)

    insights_out.sort(key=lambda item: (-(item.contribution_share or 0.0), 0 if item.severity == "warning" else 1))
    if not insights_out:
        metric_change = _metric_change_insight(selected_metric, current_totals, previous_totals)
        if metric_change is not None:
            insights_out.append(metric_change)

    return InsightsResponse(
        site_id=site_id,
        start=start_day,
        end=end_day,
        compare_start=compare_start_day,
        compare_end=compare_end_day,
        metric=selected_metric,
        insights=insights_out[:MAX_INSIGHTS],
    )
