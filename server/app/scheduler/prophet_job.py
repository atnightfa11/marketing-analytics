from __future__ import annotations

import datetime as dt
import json
import logging
import math
import statistics
import tempfile
from pathlib import Path
from typing import Iterable

from prophet import Prophet
from prophet.diagnostics import cross_validation
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import DpWindow, Forecast, ModelStore
from .ewma import ewma

settings = get_settings()
logger = logging.getLogger("marketing-analytics")

ANOMALY_LOOKBACK_DAYS = 28
ANOMALY_MIN_HISTORY = 14
ANOMALY_Z_THRESHOLD = 3.5
ANOMALY_RATIO_THRESHOLD = 2.5
RECENT_SCORE_DAYS = 60


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
    df = _daily_dataframe(data)
    if len(df) < 60:
        return None
    df = _with_anomaly_flags(df)
    latest_has_anomaly, latest_z_score = _latest_anomaly_state(df)
    fit_df = _forecast_fit_frame(df)
    if len(fit_df) < 60:
        fit_df = df[["ds", "y"]].copy()
    fit_df = fit_df.sort_values("ds")
    model_df = fit_df[["ds", "y"]].copy()
    model_df["y"] = model_df["y"].map(lambda value: math.log1p(max(0.0, float(value))))

    _try_set_bundled_cmdstan()
    try:
        model = Prophet(interval_width=0.8, stan_backend="CMDSTANPY")
        model.fit(model_df)

        mape = _score_log_prophet(model, len(model_df))
    except Exception:
        logger.exception(
            "Prophet unavailable for training; falling back to EWMA forecast",
            extra={"site_id": site_id, "metric": metric, "plan": plan},
        )
        return await _train_ewma_fallback(session, site_id, metric, plan, df)

    baseline_mape = _recent_baseline_mape(df)
    if math.isfinite(baseline_mape) and math.isfinite(mape) and mape > baseline_mape * 1.05:
        logger.info(
            "Prophet underperformed recent baseline; falling back to EWMA forecast",
            extra={
                "site_id": site_id,
                "metric": metric,
                "plan": plan,
                "prophet_mape": mape,
                "baseline_mape": baseline_mape,
            },
        )
        return await _train_ewma_fallback(session, site_id, metric, plan, df)

    horizon = max(1, settings.FORECAST_HORIZON_DAYS)
    future = _forecast_horizon_frame(df, horizon)
    forecast_df = model.predict(future)

    with tempfile.NamedTemporaryFile(prefix=f"{site_id}-{metric}-", suffix=".json", delete=False) as tmp:
        history_records = [
            {"ds": str(record["ds"]), "y": float(record["y"])}
            for record in df.to_dict(orient="records")
        ]
        payload = {
            "params": _json_compatible(model.params),
            "history": history_records,
            "target_transform": "log1p",
            "anomaly_policy": "excluded_from_fit",
        }
        tmp.write(json.dumps(payload).encode("utf-8"))
        artifact_path = Path(tmp.name)

    model_record = ModelStore(
        site_id=site_id,
        plan=plan,
        engine="prophet_log1p",
        metric=metric,
        uri=str(artifact_path),
        mape_cv=mape,
    )
    session.add(model_record)
    await session.flush()

    await _replace_metric_forecasts(session, site_id=site_id, metric=metric, plan=plan)
    forecasts = []
    for _, row in forecast_df.iterrows():
        raw_yhat = math.expm1(float(row["yhat"]))
        raw_lower = math.expm1(float(row["yhat_lower"]))
        raw_upper = math.expm1(float(row["yhat_upper"]))
        yhat, yhat_lower, yhat_upper = _non_negative_forecast_interval(
            raw_yhat,
            raw_lower,
            raw_upper,
        )
        forecasts.append(
            Forecast(
                site_id=site_id,
                plan=plan,
                metric=metric,
                day=row["ds"].date(),
                yhat=yhat,
                yhat_lower=yhat_lower,
                yhat_upper=yhat_upper,
                mape=mape,
                has_anomaly=latest_has_anomaly,
                z_score=latest_z_score,
                model_id=model_record.id,
            )
        )
    session.add_all(forecasts)
    await session.commit()
    return forecasts


def _daily_dataframe(rows: Iterable[dict]):
    totals: dict[dt.date, float] = {}
    for row in rows:
        day = row["ds"]
        totals[day] = totals.get(day, 0.0) + max(0.0, float(row["y"]))
    import pandas as pd

    data = [{"ds": day, "y": value} for day, value in sorted(totals.items())]
    return pd.DataFrame(data)


def _forecast_horizon_frame(df, horizon: int):
    import pandas as pd

    last_observed_day = max(df["ds"].tolist())
    days = [last_observed_day + dt.timedelta(days=offset) for offset in range(1, horizon + 1)]
    return pd.DataFrame({"ds": days})


def _with_anomaly_flags(df):
    df = df.sort_values("ds").copy()
    is_anomaly: list[bool] = []
    anomaly_z: list[float] = []
    values = [float(v) for v in df["y"].tolist()]
    for index, value in enumerate(values):
        history = values[max(0, index - ANOMALY_LOOKBACK_DAYS):index]
        if len(history) < ANOMALY_MIN_HISTORY:
            is_anomaly.append(False)
            anomaly_z.append(0.0)
            continue
        median = statistics.median(history)
        deviations = [abs(sample - median) for sample in history]
        mad = statistics.median(deviations)
        if mad <= 0:
            mad = statistics.pstdev(history) or 1.0
        robust_z = 0.6745 * (value - median) / mad
        high_ratio = median > 0 and value >= median * ANOMALY_RATIO_THRESHOLD
        low_ratio = median > 0 and value <= median / ANOMALY_RATIO_THRESHOLD
        flagged = abs(robust_z) >= ANOMALY_Z_THRESHOLD and (high_ratio or low_ratio)
        is_anomaly.append(flagged)
        anomaly_z.append(float(robust_z))
    df["is_anomaly"] = is_anomaly
    df["anomaly_z"] = anomaly_z
    return df


def _forecast_fit_frame(df):
    if "is_anomaly" not in df:
        df = _with_anomaly_flags(df)
    clean = df[~df["is_anomaly"]][["ds", "y"]].copy()
    return clean


def _latest_anomaly_state(df) -> tuple[bool, float]:
    if df.empty:
        return False, 0.0
    latest = df.sort_values("ds").iloc[-1]
    return bool(latest.get("is_anomaly", False)), float(latest.get("anomaly_z", 0.0) or 0.0)


def _mape(actual: Iterable[float], predicted: Iterable[float]) -> float:
    errors = [
        abs(float(a) - float(p)) / max(abs(float(a)), 1.0)
        for a, p in zip(actual, predicted)
        if math.isfinite(float(a)) and math.isfinite(float(p))
    ]
    if not errors:
        return float("inf")
    return sum(errors) / len(errors)


def _score_log_prophet(model: Prophet, history_len: int) -> float:
    if history_len < 60:
        return float("inf")
    initial_days = max(45, min(history_len - 14, 120))
    cv = cross_validation(
        model,
        initial=f"{initial_days} days",
        period="7 days",
        horizon="7 days",
        disable_tqdm=True,
    )
    actual = [max(0.0, math.expm1(float(value))) for value in cv["y"].tolist()]
    predicted = [max(0.0, math.expm1(float(value))) for value in cv["yhat"].tolist()]
    return _mape(actual, predicted)


def _recent_baseline_mape(df) -> float:
    scored = df.sort_values("ds").copy()
    if "is_anomaly" not in scored:
        scored = _with_anomaly_flags(scored)
    days = [d for d in scored["ds"].tolist()]
    values = [float(v) for v in scored["y"].tolist()]
    anomaly_flags = [bool(v) for v in scored["is_anomaly"].tolist()]
    actual: list[float] = []
    predicted: list[float] = []
    start_index = max(7, len(values) - RECENT_SCORE_DAYS)
    for index in range(start_index, len(values)):
        if anomaly_flags[index]:
            continue
        trailing = [
            values[pos]
            for pos in range(max(0, index - 28), index)
            if not anomaly_flags[pos]
        ]
        if len(trailing) < 7:
            continue
        same_weekday = [
            values[pos]
            for pos in range(max(0, index - 56), index)
            if not anomaly_flags[pos] and days[pos].weekday() == days[index].weekday()
        ]
        if same_weekday:
            prediction = statistics.median(same_weekday[-4:])
        else:
            prediction = statistics.median(trailing[-14:])
        actual.append(values[index])
        predicted.append(prediction)
    return _mape(actual, predicted)


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

    # Use the most recent non-anomalous daily history to estimate level, volatility, and weekday seasonality.
    df = _with_anomaly_flags(df).sort_values("ds")
    latest_has_anomaly, latest_z_score = _latest_anomaly_state(df)
    last_observed_day = max(df["ds"].tolist())
    clean_df = _forecast_fit_frame(df)
    if len(clean_df) >= 14:
        df_for_fit = clean_df.sort_values("ds")
    else:
        df_for_fit = df.sort_values("ds")
    values = [float(v) for v in df_for_fit["y"].tolist()]
    days = [d for d in df_for_fit["ds"].tolist()]
    if len(values) < 14:
        return None

    smoothed = ewma(values, span=min(14, max(3, len(values) // 4)))
    last_level = smoothed[-1]
    tail = values[-min(30, len(values)) :]
    smooth_tail = smoothed[-len(tail) :]
    mape = _recent_baseline_mape(df)
    if not math.isfinite(mape):
        mape = sum(abs(a - b) / max(abs(a), 1.0) for a, b in zip(tail, smooth_tail)) / len(tail)
    mape = max(mape, 0.03)

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
        day = last_observed_day + dt.timedelta(days=i + 1)
        base = weekday_mean.get(day.weekday(), last_level)
        yhat = base + trend * (i + 1)
        band = 1.2816 * sigma
        yhat, yhat_lower, yhat_upper = _non_negative_forecast_interval(
            yhat,
            yhat - band,
            yhat + band,
        )
        forecasts.append(
            Forecast(
                site_id=site_id,
                plan=plan,
                metric=metric,
                day=day,
                yhat=float(yhat),
                yhat_lower=float(yhat_lower),
                yhat_upper=float(yhat_upper),
                mape=float(mape),
                has_anomaly=latest_has_anomaly,
                z_score=latest_z_score,
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


def _non_negative_forecast_interval(
    yhat: float,
    yhat_lower: float,
    yhat_upper: float,
) -> tuple[float, float, float]:
    """Forecasted analytics counts are constrained to the non-negative domain."""
    bounded_yhat = max(0.0, float(yhat))
    bounded_lower = max(0.0, float(yhat_lower))
    bounded_upper = max(0.0, float(yhat_upper))
    if bounded_lower > bounded_yhat:
        bounded_lower = bounded_yhat
    if bounded_upper < bounded_yhat:
        bounded_upper = bounded_yhat
    return bounded_yhat, bounded_lower, bounded_upper
