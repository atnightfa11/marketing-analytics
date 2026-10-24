"""Site-local reporting dates; stored daily windows use UTC-midnight date labels.

Timezone changes are prospective. A recorded cutover preserves the old day labels
instead of pretending purged historical aggregates can be re-bucketed exactly.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from .models import DashboardSite


def as_utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


def reporting_timezone(site: DashboardSite | None, timestamp: dt.datetime) -> str:
    if site is None:
        return "UTC"
    cutoff = site.reporting_timezone_effective_at
    if cutoff is not None and as_utc(timestamp) < as_utc(cutoff):
        return site.previous_reporting_timezone or "UTC"
    return site.timezone or "UTC"


def reporting_day(site: DashboardSite | None, timestamp: dt.datetime) -> dt.date:
    timestamp = as_utc(timestamp)
    day = timestamp.astimezone(ZoneInfo(reporting_timezone(site, timestamp))).date()
    if site is not None and site.reporting_timezone_effective_at is not None:
        cutoff = as_utc(site.reporting_timezone_effective_at)
        if timestamp >= cutoff:
            # A westward timezone change must not reopen yesterday's completed
            # bucket. Its first day is longer; subsequent days are local days.
            first_day = cutoff.astimezone(ZoneInfo(site.previous_reporting_timezone or "UTC")).date()
            day = max(day, first_day)
    return day


async def site_today(session: AsyncSession, site_id: str, now: dt.datetime | None = None) -> dt.date:
    return reporting_day(await session.get(DashboardSite, site_id), now or dt.datetime.now(dt.timezone.utc))


def schedule_timezone(site: DashboardSite, timezone: str, now: dt.datetime) -> None:
    """Finish the active reporting day before applying a new timezone."""
    now = as_utc(now)
    active = reporting_timezone(site, now)
    if timezone == active:
        site.timezone = timezone
        # Preserve an already completed transition for late-arriving events.
        if site.reporting_timezone_effective_at and now < as_utc(site.reporting_timezone_effective_at):
            site.reporting_timezone_effective_at = None
            site.previous_reporting_timezone = None
        return
    if site.reporting_timezone_effective_at is None or now >= as_utc(site.reporting_timezone_effective_at):
        next_day = reporting_day(site, now) + dt.timedelta(days=1)
        site.previous_reporting_timezone = active
        finish_current_day = dt.datetime.combine(next_day, dt.time.min, ZoneInfo(active))
        local = finish_current_day.astimezone(ZoneInfo(timezone))
        cutoff = dt.datetime.combine(local.date(), dt.time.min, ZoneInfo(timezone))
        if cutoff < local:
            cutoff += dt.timedelta(days=1)
        site.reporting_timezone_effective_at = cutoff.astimezone(dt.timezone.utc)
    else:
        # Changing a pending selection must also move its cutover to midnight
        # in the newly selected zone, without shortening the active day.
        local = as_utc(site.reporting_timezone_effective_at).astimezone(ZoneInfo(timezone))
        cutoff = dt.datetime.combine(local.date(), dt.time.min, ZoneInfo(timezone))
        if cutoff < local:
            cutoff += dt.timedelta(days=1)
        site.reporting_timezone_effective_at = cutoff.astimezone(dt.timezone.utc)
    site.timezone = timezone
