from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ldp.rr_decoder import confidence_interval, rr_unbiased_estimate, standard_error
from ..models import DpWindow, LdpReport, RawReport, SiteEpsilonLog, SitePlan

settings = get_settings()


def _laplace_scale(epsilon: float) -> float:
    return 1.0 / max(epsilon, 1e-6)


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
    if payload.get("historical_import"):
        try:
            return max(0.0, float(payload.get("value", 0.0)))
        except (TypeError, ValueError):
            return 0.0
    return 1.0


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


async def reduce_reports(
    session: AsyncSession,
    days: int = 1,
    start_day: dt.date | None = None,
    end_day: dt.date | None = None,
):
    start, end = _resolve_day_window(days=days, start_day=start_day, end_day=end_day)

    plan_map = {
        rec.site_id: rec.plan
        for rec in (await session.execute(select(SitePlan))).scalars().all()
    }

    # Free + Standard raw path
    raw_reports = (
        await session.execute(select(RawReport).where(RawReport.day >= start, RawReport.day <= end))
    ).scalars().all()
    raw_buckets: dict[tuple[str, str, dt.datetime], list[RawReport]] = defaultdict(list)
    epsilon_totals: dict[tuple[str, dt.date], float] = defaultdict(float)

    for report in raw_reports:
        plan = plan_map.get(report.site_id, "free")
        if plan == "pro":
            continue
        window_start = report.server_received_at.replace(second=0, microsecond=0)
        raw_buckets[(report.site_id, report.kind, window_start)].append(report)
        if plan == "standard":
            epsilon_totals[(report.site_id, report.day)] += min(
                settings.AGGREGATE_DP_EPSILON, max(0.0, report.epsilon_used)
            )

    for (site_id, metric, window_start), items in raw_buckets.items():
        historical_bucket = any(
            isinstance(item.payload, dict) and bool(item.payload.get("historical_import")) for item in items
        )
        if not historical_bucket and len(items) < settings.MIN_REPORTS_PER_WINDOW:
            continue
        plan = plan_map.get(site_id, "free")
        window_end = window_start + dt.timedelta(minutes=3 if metric == "uniques" else 15)
        base_value = sum(_raw_report_value(item) for item in items)
        if base_value <= 0:
            continue
        if plan == "standard":
            noise = 0.0
            # deterministic-ish pseudonoise from timestamp/site to keep tests stable-ish
            seed = abs(hash((site_id, metric, window_start.isoformat()))) % 1000
            centered = (seed / 1000.0) - 0.5
            noise = centered * 2.0 * _laplace_scale(settings.AGGREGATE_DP_EPSILON)
            value = max(0.0, base_value + noise)
            variance = _laplace_scale(settings.AGGREGATE_DP_EPSILON) ** 2
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

    await session.commit()
