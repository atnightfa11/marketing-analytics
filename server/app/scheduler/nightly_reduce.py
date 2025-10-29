from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..ldp.rr_decoder import confidence_interval, rr_unbiased_estimate, standard_error
from ..models import DpWindow, LdpReport, SiteEpsilonLog, get_session

settings = get_settings()


async def reduce_reports(session: AsyncSession):
    today = dt.date.today()
    start = today - dt.timedelta(days=1)

    stmt = select(LdpReport).where(LdpReport.day >= start)
    reports = (await session.execute(stmt)).scalars().all()

    buckets: dict[tuple[str, str, dt.datetime], list[LdpReport]] = defaultdict(list)
    epsilon_totals: dict[tuple[str, dt.date], float] = defaultdict(float)

    for report in reports:
        window_start = report.server_received_at.replace(second=0, microsecond=0)
        window_end = window_start + dt.timedelta(minutes=3 if report.kind == "uniques" else 15)
        metric_name = report.kind
        if report.kind == "conversions":
            conversion_type = str(report.payload.get("conversion_type", "unknown"))
            metric_name = f"conversion:{conversion_type}"
        key = (report.site_id, metric_name, window_start)
        buckets[key].append(report)
        epsilon_totals[(report.site_id, report.day)] += report.epsilon_used

    for (site_id, kind, window_start), items in buckets.items():
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
        window_end = window_start + dt.timedelta(minutes=3 if kind == "uniques" else 15)
        ci80 = confidence_interval(estimate, se, 1.2816)
        ci95 = confidence_interval(estimate, se, 1.9599)

        # Upsert by (site_id, window_start, metric) to avoid duplicate key errors
        existing = (
            await session.execute(
                select(DpWindow).where(
                    DpWindow.site_id == site_id,
                    DpWindow.metric == kind,
                    DpWindow.window_start == window_start,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.window_end = window_end
            existing.value = max(0.0, estimate)
            existing.variance = variance
            existing.ci80_low = max(0.0, ci80[0])
            existing.ci80_high = max(0.0, ci80[1])
            existing.ci95_low = max(0.0, ci95[0])
            existing.ci95_high = max(0.0, ci95[1])
            # object is already in session; changes will be flushed on commit
        else:
            await session.merge(
                DpWindow(
                    site_id=site_id,
                    window_start=window_start,
                    window_end=window_end,
                    metric=kind,
                    value=max(0.0, estimate),
                    variance=variance,
                    ci80_low=max(0.0, ci80[0]),
                    ci80_high=max(0.0, ci80[1]),
                    ci95_low=max(0.0, ci95[0]),
                    ci95_high=max(0.0, ci95[1]),
                )
            )

    for (site_id, day), epsilon_total in epsilon_totals.items():
        existing_eps = (
            await session.execute(
                select(SiteEpsilonLog).where(
                    SiteEpsilonLog.site_id == site_id,
                    SiteEpsilonLog.day == day,
                )
            )
        ).scalar_one_or_none()
        if existing_eps:
            existing_eps.epsilon_total = epsilon_total
        else:
            session.add(SiteEpsilonLog(site_id=site_id, day=day, epsilon_total=epsilon_total))

    await session.commit()
