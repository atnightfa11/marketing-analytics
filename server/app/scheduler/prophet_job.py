from __future__ import annotations

import datetime as dt
import json
import logging
import statistics
import tempfile
from pathlib import Path
from typing import Iterable

from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import DpWindow, Forecast, ModelStore
from .ewma import ewma

settings = get_settings()
logger = logging.getLogger("marketing-analytics")


async def train_prophet(session: AsyncSession, site_id: str, metric: str, plan: str = "free"):
    today_start = dt.datetime.combine(dt.datetime.now(dt.timezone.utc).date(), dt.time.min, tzinfo=dt.timezone.utc)
    stmt = (
        select(DpWindow)
        .where(
            DpWindow.site_id == site_id,
            DpWindow.metric == metric,
            DpWindow.plan == plan,
            DpWindow.window_start < today_start,
        )
        .order_by(DpWindow.window_start.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    if len(rows) < 60:
        return None

    data = []
    for row in rows:
        data.append({"ds": row.window_start.date(), "y": row.value})
    df = _distinct_by_day(data)
    if len(df) < 60:
        return None

    _try_set_bundled_cmdstan()
    try:
        model = Prophet(interval_width=0.8, stan_backend="CMDSTANPY")
        model.fit(df)

        cv = cross_validation(model, initial="45 days", period="7 days", horizon="15 days")
        perf = performance_metrics(cv)
        mape = perf["mape"].iloc[-1]
    except Exception:
        logger.exception(
            "Prophet unavailable for training; falling back to EWMA forecast",
            extra={"site_id": site_id, "metric": metric, "plan": plan},
        )
        return await _train_ewma_fallback(session, site_id, metric, plan, df)

    prior = (
        await session.execute(
            select(ModelStore)
            .where(
                ModelStore.site_id == site_id,
                ModelStore.engine == "prophet",
                ModelStore.metric == metric,
                ModelStore.plan == plan,
            )
            .order_by(ModelStore.created_at.desc())
        )
    ).scalar_one_or_none()

    if prior and mape > prior.mape_cv * 0.95:
        return None

    future = model.make_future_dataframe(periods=max(1, settings.FORECAST_HORIZON_DAYS), freq="D")
    forecast_df = model.predict(future)

    with tempfile.NamedTemporaryFile(prefix=f"{site_id}-{metric}-", suffix=".json", delete=False) as tmp:
        history_records = [
            {"ds": str(record["ds"]), "y": float(record["y"])}
            for record in df.to_dict(orient="records")
        ]
        payload = {
            "params": _json_compatible(model.params),
            "history": history_records,
        }
        tmp.write(json.dumps(payload).encode("utf-8"))
        artifact_path = Path(tmp.name)

    model_record = ModelStore(
        site_id=site_id,
        plan=plan,
        engine="prophet",
        metric=metric,
        uri=str(artifact_path),
        mape_cv=mape,
    )
    session.add(model_record)
    await session.flush()

    await _replace_metric_forecasts(session, site_id=site_id, metric=metric, plan=plan)
    forecasts = []
    horizon = max(1, settings.FORECAST_HORIZON_DAYS)
    for _, row in forecast_df.tail(horizon).iterrows():
        forecasts.append(
            Forecast(
                site_id=site_id,
                plan=plan,
                metric=metric,
                day=row["ds"].date(),
                yhat=row["yhat"],
                yhat_lower=row["yhat_lower"],
                yhat_upper=row["yhat_upper"],
                mape=mape,
                has_anomaly=False,
                z_score=0.0,
                model_id=model_record.id,
            )
        )
    session.add_all(forecasts)
    await session.commit()
    return forecasts


def _distinct_by_day(rows: Iterable[dict]):

    seen = {}
    for row in rows:
        seen[row["ds"]] = row
    import pandas as pd

    data = list(seen.values())
    return pd.DataFrame(data)


def _json_compatible(value):
    if isinstance(value, dict):
        return {k: _json_compatible(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(v) for v in value]
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        return _json_compatible(to_list())
    return value


def _try_set_bundled_cmdstan() -> None:
    try:
        from cmdstanpy import cmdstan_path, set_cmdstan_path
        import prophet as prophet_pkg
    except Exception:
        return

    try:
        existing = cmdstan_path()
        if existing:
            return
    except Exception:
        pass

    stan_model_dir = Path(prophet_pkg.__file__).resolve().parent / "stan_model"
    for candidate in sorted(stan_model_dir.glob("cmdstan-*")):
        if (candidate / "bin").exists():
            try:
                set_cmdstan_path(str(candidate))
                return
            except Exception:
                continue


async def _train_ewma_fallback(
    session: AsyncSession,
    site_id: str,
    metric: str,
    plan: str,
    df,
):
    if df.empty:
        return None

    # Use the most recent daily history to estimate level, volatility, and weekday seasonality.
    df = df.sort_values("ds")
    values = [float(v) for v in df["y"].tolist()]
    days = [d for d in df["ds"].tolist()]
    if len(values) < 14:
        return None

    smoothed = ewma(values, span=min(14, max(3, len(values) // 4)))
    last_level = smoothed[-1]
    tail = values[-min(30, len(values)) :]
    smooth_tail = smoothed[-len(tail) :]
    mape = sum(abs(a - b) / max(abs(a), 1.0) for a, b in zip(tail, smooth_tail)) / len(tail)
    mape = min(max(mape, 0.03), 0.35)

    weekday_buckets: dict[int, list[float]] = {k: [] for k in range(7)}
    for day, value in zip(days[-56:], values[-56:]):
        weekday_buckets[day.weekday()].append(value)
    weekday_mean = {
        k: (sum(v) / len(v) if v else last_level) for k, v in weekday_buckets.items()
    }

    trend = 0.0
    if len(smoothed) >= 8:
        trend = (smoothed[-1] - smoothed[-8]) / 7.0

    sigma = max(1.0, statistics.pstdev(tail)) if len(tail) > 1 else max(1.0, abs(last_level) * 0.08)
    horizon = max(1, settings.FORECAST_HORIZON_DAYS)
    last_day = max(days)

    model_record = ModelStore(
        site_id=site_id,
        plan=plan,
        engine="ewma_fallback",
        metric=metric,
        uri="inline://ewma-fallback",
        mape_cv=float(mape),
    )
    session.add(model_record)
    await session.flush()

    await _replace_metric_forecasts(session, site_id=site_id, metric=metric, plan=plan)
    forecasts: list[Forecast] = []
    for i in range(horizon):
        day = last_day + dt.timedelta(days=i + 1)
        base = weekday_mean.get(day.weekday(), last_level)
        yhat = max(0.0, base + trend * (i + 1))
        band = 1.2816 * sigma
        forecasts.append(
            Forecast(
                site_id=site_id,
                plan=plan,
                metric=metric,
                day=day,
                yhat=float(yhat),
                yhat_lower=float(max(0.0, yhat - band)),
                yhat_upper=float(max(0.0, yhat + band)),
                mape=float(mape),
                has_anomaly=False,
                z_score=0.0,
                model_id=model_record.id,
            )
        )
    session.add_all(forecasts)
    await session.commit()
    return forecasts


async def _replace_metric_forecasts(
    session: AsyncSession,
    *,
    site_id: str,
    metric: str,
    plan: str,
) -> None:
    await session.execute(
        delete(Forecast).where(
            Forecast.site_id == site_id,
            Forecast.plan == plan,
            Forecast.metric == metric,
        )
    )
