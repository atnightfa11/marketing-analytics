"""Accepted traffic accounting, independent of noisy analytics and raw retention."""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AccountUsage, DashboardSite, IngestReceipt, SitePlan


def insert_for(session: AsyncSession, model):
    return (pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert)(model)


def utc(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=dt.timezone.utc) if value.tzinfo is None else value.astimezone(dt.timezone.utc)


async def claim_event(session: AsyncSession, report, *, accepted_at: dt.datetime, retry_seconds: int) -> bool:
    # SDK nonces survive re-batching. Legacy clients use the exact event envelope.
    identity = [report.site_id, report.nonce] if report.nonce else [
        report.site_id, report.kind, report.client_timestamp.isoformat(), report.payload,
    ]
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    statement = insert_for(session, IngestReceipt).values(
        event_hash=digest,
        expires_at=accepted_at + dt.timedelta(seconds=max(86400, retry_seconds + 3600)),
    ).on_conflict_do_nothing(index_elements=["event_hash"]).returning(IngestReceipt.event_hash)
    return (await session.execute(statement)).scalar_one_or_none() is not None


async def usage_context(session: AsyncSession, site_id: str, now: dt.datetime):
    site = await session.get(DashboardSite, site_id)
    account = f"owner:{site.owner_username}" if site else f"site:{site_id}"
    query = select(SitePlan).where(SitePlan.site_id == site_id)
    if site:
        query = select(SitePlan).join(DashboardSite, DashboardSite.site_id == SitePlan.site_id).where(
            DashboardSite.owner_username == site.owner_username,
        )
    records = (await session.execute(query)).scalars().all()
    periods = {
        (utc(row.stripe_current_period_start), utc(row.stripe_current_period_end))
        for row in records
        if row.stripe_subscription_id and row.stripe_current_period_start and row.stripe_current_period_end
        and utc(row.stripe_current_period_start) <= now < utc(row.stripe_current_period_end)
    }
    if len(periods) == 1:
        start, end = periods.pop()
        return account, start, end, "stripe_period"
    # Preserve traffic when a renewal webhook is late or legacy config lacks a start.
    # These explicitly provisional counters must never be treated as billable totals.
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return account, start, end, "unassigned_calendar_month"


async def record_pageviews(session: AsyncSession, site_id: str, count: int, now: dt.datetime) -> None:
    if not count:
        return
    account, start, end, basis = await usage_context(session, site_id, now)
    statement = insert_for(session, AccountUsage).values(
        account_key=account, site_id=site_id, period_start=start, period_end=end,
        period_basis=basis, accepted_pageviews=count, first_recorded_at=now, updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["account_key", "site_id", "period_start", "period_basis"],
        set_={"accepted_pageviews": AccountUsage.accepted_pageviews + count, "updated_at": now},
    )
    await session.execute(statement)
