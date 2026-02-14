from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Iterable

from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import DpWindow, Forecast, ModelStore, SitePlan

settings = get_settings()


async def train_prophet(session: AsyncSession, site_id: str, metric: str, plan: str = "free"):
    stmt = (
        select(DpWindow)
        .where(DpWindow.site_id == site_id, DpWindow.metric == metric, DpWindow.plan == plan)
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

    model = Prophet(interval_width=0.8)
    model.fit(df)

    cv = cross_validation(model, initial="45 days", period="7 days", horizon="15 days")
    perf = performance_metrics(cv)
    mape = perf["mape"].iloc[-1]

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
        payload = {
            "params": model.params,
            "history": df.to_dict(orient="records"),
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
    for forecast in forecasts:
        session.merge(forecast)
    await session.commit()
    return forecasts


def _distinct_by_day(rows: Iterable[dict]):

    seen = {}
    for row in rows:
        seen[row["ds"]] = row
    import pandas as pd

    data = list(seen.values())
    return pd.DataFrame(data)
