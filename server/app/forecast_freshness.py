from __future__ import annotations

import datetime as dt
from typing import Protocol


# Forecasts retrain daily; allow a short grace period before treating a row as stale.
FORECAST_STALE_AFTER_DAYS = 2


class ForecastFreshnessRow(Protocol):
    trained_at: dt.datetime | None


def forecast_is_fresh(forecast: ForecastFreshnessRow, now: dt.datetime | None = None) -> bool:
    trained_at = forecast.trained_at
    if trained_at is None:
        return False
    if trained_at.tzinfo is None:
        trained_at = trained_at.replace(tzinfo=dt.timezone.utc)
    reference = now or dt.datetime.now(dt.timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=dt.timezone.utc)
    return (reference - trained_at) <= dt.timedelta(days=FORECAST_STALE_AFTER_DAYS)
