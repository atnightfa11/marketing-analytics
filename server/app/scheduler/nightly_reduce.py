from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import math
import secrets
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..breakdown_logic import (
    BREAKDOWN_DIMENSIONS,
    BREAKDOWN_REPORT_KINDS,
    TIME_PARTING_DIMENSIONS,
    TIME_PARTING_STORAGE_DAY_TYPES,
    aggregate_reports_for_breakdown,
)
from ..config import get_settings
from ..hostnames import hostname_from_payload
from ..ldp.rr_decoder import confidence_interval, rr_unbiased_estimate, standard_error
from ..models import (
    BreakdownRollup,
    DashboardSite,
    DpWindow,
    LdpReport,
    RawReport,
    ReducerWatermark,
    SiteEpsilonLog,
    SitePlan,
)

settings = get_settings()
REDUCER_VERSION = "rollups-v1"


def _laplace_scale(epsilon: float) -> float:
    return 1.0 / max(epsilon, 1e-6)


def _laplace_variance(scale: float) -> float:
    # Laplace(0, b) variance is 2*b^2
    return 2.0 * (scale**2)


def _uniform_unit_interval(site_id: str, metric: str, window_start: dt.datetime, secret: str | None) -> float:
    # Use a keyed deterministic CSPRNG stream when a secret is configured so
    # noise is stable across reducer re-runs but still unpredictable externally.
    if secret:
        context = f"{site_id}|{metric}|{window_start.isoformat()}|standard-v1"
        digest = hmac.new(secret.encode("utf-8"), context.encode("utf-8"), hashlib.sha256).digest()
        raw = int.from_bytes(digest[:8], "big")
        # map to (0,1), avoiding exact endpoints
        return (raw + 0.5) / (2**64)

    # Fallback: true CSPRNG draw (non-deterministic across re-runs)
    raw = secrets.randbits(64)
    return (raw + 0.5) / (2**64)


def _laplace_noise(scale: float, site_id: str, metric: str, window_start: dt.datetime, secret: str | None) -> float:
    # Inverse CDF sampler for Laplace(0, scale)
    u = _uniform_unit_interval(site_id, metric, window_start, secret)
    if u < 0.5:
        return scale * math.log(2.0 * u)
    return -scale * math.log(2.0 * (1.0 - u))


def _resolve_day_window(
    *,
    days: int,
    start_day: dt.date | None,
    end_day: dt.date | None,
) -> tuple[dt.date, dt.date]:
    if start_day and end_day:
        return (start_day, end_day) if start_day <= end_day else (end_day, start_day)
    if start_day:
        return start_day, start_day
    if end_day:
        return end_day, end_day
    today = dt.date.today()
    window_days = max(1, days)
    return today - dt.timedelta(days=window_days), today


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


def _bucket_start(timestamp: dt.datetime, bucket_minutes: int) -> dt.datetime:
    bucket_seconds = max(1, bucket_minutes) * 60
    ts = int(timestamp.replace(second=0, microsecond=0).timestamp())
    floored = ts - (ts % bucket_seconds)
    return dt.datetime.fromtimestamp(floored, tz=dt.timezone.utc)


def _day_start(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)


async def _upsert_window(
    session: AsyncSession,
    *,
    site_id: str,
    plan: str,
    metric: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    value: float,
    variance: float,
) -> None:
    se = standard_error(variance)
    ci80 = confidence_interval(value, se, 1.2816)
    ci95 = confidence_interval(value, se, 1.9599)
    existing = (
        await session.execute(
            select(DpWindow).where(
                DpWindow.site_id == site_id,
                DpWindow.plan == plan,
                DpWindow.metric == metric,
                DpWindow.window_start == window_start,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.window_end = window_end
        existing.value = max(0.0, value)
        existing.variance = max(0.0, variance)
        existing.ci80_low = max(0.0, ci80[0])
        existing.ci80_high = max(0.0, ci80[1])
        existing.ci95_low = max(0.0, ci95[0])
        existing.ci95_high = max(0.0, ci95[1])
        return

    session.add(
        DpWindow(
            site_id=site_id,
            plan=plan,
            window_start=window_start,
            window_end=window_end,
            metric=metric,
            value=max(0.0, value),
            variance=max(0.0, variance),
            ci80_low=max(0.0, ci80[0]),
            ci80_high=max(0.0, ci80[1]),
            ci95_low=max(0.0, ci95[0]),
            ci95_high=max(0.0, ci95[1]),
        )
    )


async def _replace_breakdown_rollups(
    session: AsyncSession,
    *,
    site_id: str,
    plan: str,
    day: dt.date,
    reports: list[RawReport],
    site_timezone: str,
) -> int:
    await session.execute(
        delete(BreakdownRollup).where(
            BreakdownRollup.site_id == site_id,
            BreakdownRollup.plan == plan,
            BreakdownRollup.day == day,
        )
    )

    hostnames = sorted(
        {
            host
            for report in reports
            for host in [hostname_from_payload(report.payload if isinstance(report.payload, dict) else {})]
            if host
        }
    )
    hostname_scopes: list[tuple[str, str | None]] = [("", None)]
    hostname_scopes.extend((hostname, hostname) for hostname in hostnames)

    inserted = 0
    now = dt.datetime.now(dt.timezone.utc)
    for hostname_scope, hostname_filter in hostname_scopes:
        for dimension in BREAKDOWN_DIMENSIONS:
            dimension_reports = [report for report in reports if report.kind in BREAKDOWN_REPORT_KINDS[dimension]]
            storage_day_types = (
                TIME_PARTING_STORAGE_DAY_TYPES if dimension in TIME_PARTING_DIMENSIONS else ("all",)
            )
            for day_type in storage_day_types:
                buckets = aggregate_reports_for_breakdown(
                    reports=dimension_reports,
                    dimension=dimension,
                    site_timezone=site_timezone,
                    hostname_filter=hostname_filter,
                    day_type=day_type,
                )
                for label, metrics in buckets.items():
                    for metric, value in metrics.items():
                        if value <= 0:
                            continue
                        session.add(
                            BreakdownRollup(
                                site_id=site_id,
                                plan=plan,
                                day=day,
                                dimension=dimension,
                                hostname=hostname_scope,
                                day_type=day_type,
                                label=label,
                                metric=metric,
                                value=value,
                                updated_at=now,
                            )
                        )
                        inserted += 1
    return inserted


async def _count_dp_windows_for_day(
    session: AsyncSession,
    *,
    site_id: str,
    plan: str,
    day: dt.date,
) -> int:
    rows = (
        await session.execute(
            select(DpWindow).where(
                DpWindow.site_id == site_id,
                DpWindow.plan == plan,
                DpWindow.window_start >= _day_start(day),
                DpWindow.window_start < _day_start(day + dt.timedelta(days=1)),
            )
        )
    ).scalars().all()
    return len(rows)


async def _mark_reducer_success(
    session: AsyncSession,
    *,
    site_id: str,
    plan: str,
    day: dt.date,
    raw_report_count: int,
    dp_window_count: int,
    breakdown_rollup_count: int,
    reduced_at: dt.datetime,
) -> None:
    existing = (
        await session.execute(
            select(ReducerWatermark).where(
                ReducerWatermark.site_id == site_id,
                ReducerWatermark.plan == plan,
                ReducerWatermark.day == day,
                ReducerWatermark.reducer_version == REDUCER_VERSION,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.status = "success"
        existing.raw_report_count = raw_report_count
        existing.dp_window_count = dp_window_count
        existing.breakdown_rollup_count = breakdown_rollup_count
        existing.reduced_at = reduced_at
        existing.raw_purged_at = None
        existing.error = None
        return

    session.add(
        ReducerWatermark(
            site_id=site_id,
            plan=plan,
            day=day,
            reducer_version=REDUCER_VERSION,
            status="success",
            raw_report_count=raw_report_count,
            dp_window_count=dp_window_count,
            breakdown_rollup_count=breakdown_rollup_count,
            reduced_at=reduced_at,
            raw_purged_at=None,
            error=None,
        )
    )


async def purge_reduced_raw_reports(
    session: AsyncSession,
    *,
    now: dt.datetime | None = None,
) -> int:
    if not settings.RAW_REPORT_PURGE_ENABLED:
        return 0

    effective_now = now or dt.datetime.now(dt.timezone.utc)
    retention_hours = max(0, settings.RAW_REPORT_RETENTION_HOURS)
    cutoff = effective_now - dt.timedelta(hours=retention_hours)
    watermarks = (
        await session.execute(
            select(ReducerWatermark).where(
                ReducerWatermark.reducer_version == REDUCER_VERSION,
                ReducerWatermark.status == "success",
                ReducerWatermark.raw_purged_at.is_(None),
                ReducerWatermark.dp_window_count > 0,
                ReducerWatermark.breakdown_rollup_count > 0,
                ReducerWatermark.reduced_at <= cutoff,
            )
        )
    ).scalars().all()
    if not settings.FREE_RAW_PURGE_ENABLED:
        watermarks = [watermark for watermark in watermarks if watermark.plan == "standard"]

    plan_map = {
        rec.site_id: rec.plan
        for rec in (await session.execute(select(SitePlan))).scalars().all()
    }

    deleted_total = 0
    for watermark in watermarks:
        if watermark.plan == "pro":
            continue
        if plan_map.get(watermark.site_id, "free") != watermark.plan:
            continue
        result = await session.execute(
            delete(RawReport).where(
                RawReport.site_id == watermark.site_id,
                RawReport.day == watermark.day,
                RawReport.server_received_at <= watermark.reduced_at,
            )
        )
        if result.rowcount and result.rowcount > 0:
            deleted_total += int(result.rowcount)

        remaining = (
            await session.execute(
                select(RawReport).where(
                    RawReport.site_id == watermark.site_id,
                    RawReport.day == watermark.day,
                    RawReport.server_received_at <= watermark.reduced_at,
                )
            )
        ).scalars().first()
        if remaining is None:
            watermark.raw_purged_at = effective_now

    return deleted_total


async def reduce_reports(
    session: AsyncSession,
    days: int = 1,
    start_day: dt.date | None = None,
    end_day: dt.date | None = None,
):
    start, end = _resolve_day_window(days=days, start_day=start_day, end_day=end_day)
    noise_secret = settings.AGGREGATE_DP_NOISE_SECRET or settings.SESSION_HMAC_SECRET

    plan_map = {
        rec.site_id: rec.plan
        for rec in (await session.execute(select(SitePlan))).scalars().all()
    }
    site_timezones = {
        rec.site_id: rec.timezone
        for rec in (await session.execute(select(DashboardSite))).scalars().all()
    }
    standard_site_ids = [site_id for site_id, plan in plan_map.items() if plan == "standard"]
    if standard_site_ids:
        await session.execute(
            delete(DpWindow).where(
                DpWindow.site_id.in_(standard_site_ids),
                DpWindow.plan == "standard",
                DpWindow.window_start >= _day_start(start),
                DpWindow.window_start < _day_start(end + dt.timedelta(days=1)),
            )
        )

    # Solo/internal free + Standard raw path
    raw_reports = (
        await session.execute(
            select(RawReport)
            .where(RawReport.day >= start, RawReport.day <= end)
            .order_by(RawReport.server_received_at, RawReport.id)
        )
    ).scalars().all()
    raw_buckets: dict[tuple[str, str, dt.datetime], list[RawReport]] = defaultdict(list)
    raw_reports_by_site_day: dict[tuple[str, str, dt.date], list[RawReport]] = defaultdict(list)
    raw_counts_by_site_day: dict[tuple[str, str, dt.date], int] = defaultdict(int)
    deduped_session_markers: set[tuple[str, dt.datetime, str]] = set()
    deduped_unique_markers: set[tuple[str, dt.date, str]] = set()
    epsilon_totals: dict[tuple[str, dt.date], float] = defaultdict(float)

    for report in raw_reports:
        plan = plan_map.get(report.site_id, "free")
        if plan == "pro":
            continue
        raw_reports_by_site_day[(report.site_id, plan, report.day)].append(report)
        raw_counts_by_site_day[(report.site_id, plan, report.day)] += 1
        payload = report.payload if isinstance(report.payload, dict) else {}
        if report.kind == "sessions":
            session_hmac = payload.get("_session_hmac")
            if isinstance(session_hmac, str) and session_hmac:
                session_bucket_start = _bucket_start(report.server_received_at, settings.SESSION_WINDOW_MINUTES)
                marker = (report.site_id, session_bucket_start, session_hmac)
                if marker in deduped_session_markers:
                    continue
                deduped_session_markers.add(marker)
        elif report.kind == "uniques":
            visitor_day_hmac = payload.get("_visitor_day_hmac")
            if isinstance(visitor_day_hmac, str) and visitor_day_hmac:
                marker = (report.site_id, report.day, visitor_day_hmac)
                if marker in deduped_unique_markers:
                    continue
                deduped_unique_markers.add(marker)
        window_start = (
            _day_start(report.day) if plan == "standard" else report.server_received_at.replace(second=0, microsecond=0)
        )
        raw_buckets[(report.site_id, report.kind, window_start)].append(report)
        if plan == "standard":
            epsilon_totals[(report.site_id, report.day)] += min(
                settings.AGGREGATE_DP_EPSILON, max(0.0, report.epsilon_used)
            )

    standard_pageview_counts: dict[tuple[str, dt.datetime], float] = defaultdict(float)
    for (site_id, metric, window_start), items in raw_buckets.items():
        if metric != "pageviews":
            continue
        count = sum(_raw_report_value(item) for item in items)
        if plan_map.get(site_id, "free") == "standard":
            standard_pageview_counts[(site_id, window_start)] += count

    for (site_id, metric, window_start), items in raw_buckets.items():
        historical_bucket = any(
            isinstance(item.payload, dict) and bool(item.payload.get("historical_import")) for item in items
        )
        plan = plan_map.get(site_id, "free")
        if plan != "standard" and not historical_bucket and len(items) < settings.MIN_REPORTS_PER_WINDOW:
            continue
        window_end = (
            window_start + dt.timedelta(days=1)
            if plan == "standard"
            else window_start + dt.timedelta(minutes=3 if metric == "uniques" else 15)
        )
        base_value = sum(_raw_report_value(item) for item in items)
        if plan == "standard" and metric == "sessions":
            pageview_cap = standard_pageview_counts.get((site_id, window_start))
            if pageview_cap is not None:
                base_value = min(base_value, pageview_cap)
        if base_value <= 0:
            continue
        if plan == "standard":
            scale = _laplace_scale(settings.AGGREGATE_DP_EPSILON)
            noise = _laplace_noise(scale, site_id, metric, window_start, noise_secret)
            value = max(0.0, base_value + noise)
            if metric == "sessions":
                # Keep standard sessions bounded by deduped session keys for replay resistance.
                value = min(value, base_value)
            # Privacy for standard windows comes from the Laplace noise added above.
            # We intentionally do not apply an additional SNR suppression gate here:
            # truncating small daily values one-sidedly biased sparse metrics
            # (notably conversions/revenue) downward and created gaps in the series.
            variance = _laplace_variance(scale)
        else:
            value = base_value
            variance = max(1.0, base_value)

        await _upsert_window(
            session,
            site_id=site_id,
            plan=plan,
            metric=metric,
            window_start=window_start,
            window_end=window_end,
            value=value,
            variance=variance,
        )

    breakdown_counts_by_site_day: dict[tuple[str, str, dt.date], int] = defaultdict(int)
    for (site_id, plan, day), reports_for_day in raw_reports_by_site_day.items():
        breakdown_counts_by_site_day[(site_id, plan, day)] = await _replace_breakdown_rollups(
            session,
            site_id=site_id,
            plan=plan,
            day=day,
            reports=reports_for_day,
            site_timezone=site_timezones.get(site_id, "UTC"),
        )

    # Pro LDP path
    ldp_reports = (
        await session.execute(select(LdpReport).where(LdpReport.day >= start, LdpReport.day <= end))
    ).scalars().all()
    pro_buckets: dict[tuple[str, str, dt.datetime], list[LdpReport]] = defaultdict(list)
    for report in ldp_reports:
        plan = plan_map.get(report.site_id, "free")
        if plan != "pro":
            continue
        window_start = report.server_received_at.replace(second=0, microsecond=0)
        pro_buckets[(report.site_id, report.kind, window_start)].append(report)

    for (site_id, metric, window_start), items in pro_buckets.items():
        if len(items) < settings.MIN_REPORTS_PER_WINDOW:
            continue
        ones = sum(item.payload.get("randomized_bit", 0) for item in items)
        total = len(items)
        epsilon = items[0].epsilon_used
        sampling = items[0].sampling_rate
        estimate, variance = rr_unbiased_estimate(ones, total, epsilon, sampling)
        se = standard_error(variance)
        if se == 0:
            continue
        snr = estimate / se
        if snr < 1.5:
            continue
        window_end = window_start + dt.timedelta(minutes=3 if metric == "uniques" else 15)
        await _upsert_window(
            session,
            site_id=site_id,
            plan="pro",
            metric=metric,
            window_start=window_start,
            window_end=window_end,
            value=estimate,
            variance=variance,
        )

    for (site_id, day), epsilon_total in epsilon_totals.items():
        existing_eps = (
            await session.execute(
                select(SiteEpsilonLog).where(
                    SiteEpsilonLog.site_id == site_id,
                    SiteEpsilonLog.day == day,
                    SiteEpsilonLog.plan == "standard",
                )
            )
        ).scalar_one_or_none()
        if existing_eps:
            existing_eps.epsilon_total = epsilon_total
        else:
            session.add(SiteEpsilonLog(site_id=site_id, day=day, plan="standard", epsilon_total=epsilon_total))

    reduced_at = dt.datetime.now(dt.timezone.utc)
    for (site_id, plan, day), raw_report_count in raw_counts_by_site_day.items():
        await _mark_reducer_success(
            session,
            site_id=site_id,
            plan=plan,
            day=day,
            raw_report_count=raw_report_count,
            dp_window_count=await _count_dp_windows_for_day(session, site_id=site_id, plan=plan, day=day),
            breakdown_rollup_count=breakdown_counts_by_site_day.get((site_id, plan, day), 0),
            reduced_at=reduced_at,
        )

    await purge_reduced_raw_reports(session)
    await session.commit()
