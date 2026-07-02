from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DashboardSite

SOLO_PLANS = {"free", "solo"}
STANDARD_PLANS = {"standard", "pro"}

BASIC_FORECAST_METRICS = frozenset({"pageviews", "uniques", "sessions"})
ADVANCED_FORECAST_METRICS = frozenset({"conversions", "revenue"})
ALL_FORECAST_METRICS = BASIC_FORECAST_METRICS | ADVANCED_FORECAST_METRICS

SOLO_AGGREGATE_RETENTION_DAYS = 365
STANDARD_INCLUDED_SITES = 3
STANDARD_EXTRA_SITE_PRICE_USD = 5


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
        aggregate_retention_days=SOLO_AGGREGATE_RETENTION_DAYS,
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
                f"{entitlements.display_name} includes 12 months "
                "of aggregate history. Upgrade to Standard for forever aggregate retention."
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
