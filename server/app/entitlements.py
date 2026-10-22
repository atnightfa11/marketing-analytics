from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DashboardSite, SitePlan

SOLO_PLANS = {"free", "solo"}
STANDARD_PLANS = {"standard", "pro"}

BASIC_FORECAST_METRICS = frozenset({"pageviews", "uniques", "sessions"})
ADVANCED_FORECAST_METRICS = frozenset({"conversions", "revenue"})
ALL_FORECAST_METRICS = BASIC_FORECAST_METRICS | ADVANCED_FORECAST_METRICS

SOLO_MONTHLY_PAGEVIEWS = 100_000
STANDARD_MONTHLY_PAGEVIEWS = 1_000_000
PAGEVIEW_CAPACITY_BLOCK = 1_000_000
PAGEVIEW_CAPACITY_PRICE_USD = 15
STANDARD_INCLUDED_SITES = 3
STANDARD_EXTRA_SITE_PRICE_USD = 5
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}
GRACE_SUBSCRIPTION_STATUSES = {"past_due", "unpaid"}
ENDED_SUBSCRIPTION_STATUSES = {"canceled", "incomplete_expired"}


@dataclass(frozen=True)
class PlanEntitlements:
    plan: str
    display_name: str
    included_sites: int
    extra_site_price_usd: int | None
    aggregate_retention_days: int | None
    historical_imports: bool
    anomaly_alerts: bool
    team_access: bool
    forecast_metrics: tuple[str, ...]


def normalize_plan(plan: str | None) -> str:
    normalized = (plan or "free").strip().lower()
    if normalized == "solo":
        return "free"
    if normalized in {"free", "standard", "pro"}:
        return normalized
    return "free"


def _as_aware_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def effective_plan_for_record(record: Any | None, now: dt.datetime | None = None) -> str:
    if record is None:
        return "free"
    normalized = normalize_plan(getattr(record, "plan", None))
    if normalized == "free":
        return "free"

    status_value = getattr(record, "stripe_subscription_status", None)
    subscription_status = status_value.strip().lower() if isinstance(status_value, str) else ""
    if not subscription_status:
        # Manual beta/admin upgrades do not always have Stripe subscription state.
        return normalized
    if subscription_status in ACTIVE_SUBSCRIPTION_STATUSES:
        return normalized
    if subscription_status in GRACE_SUBSCRIPTION_STATUSES:
        grace_ends_at = _as_aware_utc(getattr(record, "billing_grace_ends_at", None))
        if grace_ends_at and (now or dt.datetime.now(dt.timezone.utc)) <= grace_ends_at:
            return normalized
        return "free"
    if subscription_status in ENDED_SUBSCRIPTION_STATUSES:
        return "free"
    return "free"


def collection_is_active(record: Any | None, now: dt.datetime | None = None) -> bool:
    """Legacy unbilled beta sites stay complimentary; new signups start incomplete."""
    if record is None:
        return True
    state = (record.stripe_subscription_status or "").lower()
    if not state:
        return not bool(record.stripe_subscription_id)
    if state in ACTIVE_SUBSCRIPTION_STATUSES:
        return True
    grace_end = _as_aware_utc(record.billing_grace_ends_at)
    return bool(state in GRACE_SUBSCRIPTION_STATUSES and grace_end
                and (now or dt.datetime.now(dt.timezone.utc)) <= grace_end)


async def account_subscription(session: AsyncSession, owner_username: str):
    records = (await session.execute(select(SitePlan).join(
        DashboardSite, DashboardSite.site_id == SitePlan.site_id,
    ).where(DashboardSite.owner_username == owner_username,
            SitePlan.stripe_subscription_id.is_not(None))
      .order_by(SitePlan.updated_at.desc(), SitePlan.site_id))).scalars().all()
    current = [row for row in records if row.stripe_subscription_status not in ENDED_SUBSCRIPTION_STATUSES]
    if len({row.stripe_subscription_id for row in current}) > 1:
        return None, True
    return (current[0] if current else records[0] if records else None), False


async def billing_record_for_site(session: AsyncSession, site_id: str):
    local = await session.get(SitePlan, site_id)
    site = await session.get(DashboardSite, site_id)
    if not site:
        return local
    account, ambiguous = await account_subscription(session, site.owner_username)
    if ambiguous:
        # Do not silently choose another subscription's privileges.
        return local
    return account or local


async def require_active_collection(session: AsyncSession, site_id: str) -> None:
    if not collection_is_active(await billing_record_for_site(session, site_id)):
        raise HTTPException(403, "Collection requires an active subscription. Existing reports remain available.")


def display_plan_name(plan: str | None) -> str:
    normalized = normalize_plan(plan)
    if normalized == "free":
        return "Solo"
    if normalized == "standard":
        return "Standard"
    if normalized == "pro":
        return "Pro"
    return "Solo"


def has_standard_entitlements(plan: str | None) -> bool:
    return normalize_plan(plan) in STANDARD_PLANS


def entitlements_for_plan(plan: str | None) -> PlanEntitlements:
    normalized = normalize_plan(plan)
    if normalized == "standard":
        return PlanEntitlements(
            plan=normalized,
            display_name="Standard",
            included_sites=STANDARD_INCLUDED_SITES,
            extra_site_price_usd=STANDARD_EXTRA_SITE_PRICE_USD,
            aggregate_retention_days=None,
            historical_imports=True,
            anomaly_alerts=True,
            team_access=True,
            forecast_metrics=tuple(sorted(ALL_FORECAST_METRICS)),
        )
    if normalized == "pro":
        return PlanEntitlements(
            plan=normalized,
            display_name="Pro",
            included_sites=STANDARD_INCLUDED_SITES,
            extra_site_price_usd=STANDARD_EXTRA_SITE_PRICE_USD,
            aggregate_retention_days=None,
            historical_imports=False,
            anomaly_alerts=True,
            team_access=True,
            forecast_metrics=tuple(sorted(ALL_FORECAST_METRICS)),
        )
    return PlanEntitlements(
        plan="free",
        display_name="Solo",
        included_sites=1,
        extra_site_price_usd=None,
        aggregate_retention_days=None,
        historical_imports=False,
        anomaly_alerts=False,
        team_access=False,
        forecast_metrics=tuple(sorted(BASIC_FORECAST_METRICS)),
    )


def forecast_metric_allowed(plan: str | None, metric: str) -> bool:
    return metric in entitlements_for_plan(plan).forecast_metrics


def forecast_metrics_for_plan(plan: str | None) -> tuple[str, ...]:
    return entitlements_for_plan(plan).forecast_metrics


def require_historical_imports(plan: str | None) -> None:
    if not entitlements_for_plan(plan).historical_imports:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Historical imports require the Standard plan",
        )


def require_anomaly_alerts(plan: str | None) -> None:
    if not entitlements_for_plan(plan).anomaly_alerts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anomaly alerts require the Standard plan",
        )


def require_team_access(plan: str | None) -> None:
    if not entitlements_for_plan(plan).team_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Site access management requires the Standard plan",
        )


def enforce_aggregate_retention(plan: str | None, start_day: dt.date, end_day: dt.date) -> None:
    entitlements = entitlements_for_plan(plan)
    if entitlements.aggregate_retention_days is None:
        return
    newest_available_start = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(
        days=entitlements.aggregate_retention_days - 1
    )
    if start_day < newest_available_start:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Requested dates exceed {entitlements.display_name}'s aggregate history policy."
            ),
        )


def retention_cutoff_day(plan: str | None) -> dt.date | None:
    days = entitlements_for_plan(plan).aggregate_retention_days
    if days is None:
        return None
    return dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days - 1)


async def owned_site_count(session: AsyncSession, owner_username: str | None) -> int:
    username = owner_username.strip().lower() if isinstance(owner_username, str) else ""
    if not username:
        return 0
    return int(
        (
            await session.execute(
                select(func.count(DashboardSite.site_id)).where(DashboardSite.owner_username == username)
            )
        ).scalar_one()
        or 0
    )


def additional_site_count(plan: str | None, site_count: int) -> int:
    included = entitlements_for_plan(plan).included_sites
    return max(0, site_count - included)


def filter_allowed_forecast_metrics(plan: str | None, metrics: Iterable[str]) -> tuple[str, ...]:
    allowed = set(forecast_metrics_for_plan(plan))
    return tuple(metric for metric in metrics if metric in allowed)
