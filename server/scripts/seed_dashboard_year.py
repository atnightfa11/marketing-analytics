#!/usr/bin/env python3
import argparse
import asyncio
import datetime as dt
import math
import os
import random
import sys

from sqlalchemy import delete

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import DpWindow, Forecast, async_session_factory  # noqa: E402


def _series_seeded(days: int):
  random.seed(42)
  base_pageviews = 1200
  values = []
  for i in range(days):
    weekday = i % 7
    weekly = 1.0 + 0.18 * math.sin((2 * math.pi * weekday) / 7)
    monthly = 1.0 + 0.08 * math.sin((2 * math.pi * i) / 30.0)
    trend = 1.0 + 0.0009 * i
    noise = 1.0 + random.gauss(0, 0.05)
    pageviews = max(50, base_pageviews * weekly * monthly * trend * noise)
    uniques_ratio = max(0.35, min(0.7, 0.55 + random.gauss(0, 0.03)))
    uniques = max(30, pageviews * uniques_ratio)
    sessions = max(40, uniques * (1.2 + random.gauss(0, 0.04)))
    conv_rate = max(0.005, 0.03 + random.gauss(0, 0.004))
    conversions = max(3, sessions * conv_rate)
    aov = max(40, 75 + 10 * math.sin((2 * math.pi * i) / 90.0) + random.gauss(0, 5))
    revenue = max(200, conversions * aov)
    values.append(
      {
        "pageviews": pageviews,
        "uniques": uniques,
        "sessions": sessions,
        "conversions": conversions,
        "revenue": revenue,
      }
    )
  return values


def _variance(value: float, rel: float) -> float:
  se = max(1.0, value * rel)
  return se * se


def _interval(value: float, variance: float, z: float):
  se = math.sqrt(max(variance, 0.0))
  low = max(0.0, value - z * se)
  high = max(0.0, value + z * se)
  return low, high


async def seed(site_id: str, days: int, forecast_days: int):
  start_date = dt.date.today() - dt.timedelta(days=days - 1)
  total_days = days + forecast_days
  series = _series_seeded(total_days)

  async with async_session_factory() as session:
    metrics = ["pageviews", "uniques", "sessions", "conversions", "revenue"]
    await session.execute(delete(DpWindow).where(DpWindow.site_id == site_id, DpWindow.metric.in_(metrics)))
    await session.execute(delete(Forecast).where(Forecast.site_id == site_id, Forecast.metric.in_(metrics)))

    windows = []
    for i in range(days):
      day = start_date + dt.timedelta(days=i)
      window_start = dt.datetime.combine(day, dt.time(0, 0), tzinfo=dt.timezone.utc)
      window_end = window_start + dt.timedelta(days=1)
      values = series[i]
      for metric, value in values.items():
        variance = _variance(value, 0.06 if metric != "revenue" else 0.08)
        ci80 = _interval(value, variance, 1.2816)
        ci95 = _interval(value, variance, 1.9599)
        windows.append(
          DpWindow(
            site_id=site_id,
            window_start=window_start,
            window_end=window_end,
            metric=metric,
            value=float(round(value, 2)),
            variance=variance,
            ci80_low=ci80[0],
            ci80_high=ci80[1],
            ci95_low=ci95[0],
            ci95_high=ci95[1],
            published_at=window_end,
          )
        )

    now = dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)
    live_start = now - dt.timedelta(minutes=2)
    live_end = now + dt.timedelta(minutes=1)
    live_values = series[days - 1]
    for metric, value in live_values.items():
      variance = _variance(value / 30, 0.1)
      ci80 = _interval(value / 30, variance, 1.2816)
      ci95 = _interval(value / 30, variance, 1.9599)
      windows.append(
        DpWindow(
          site_id=site_id,
          window_start=live_start,
          window_end=live_end,
          metric=metric,
          value=float(round(value / 30, 2)),
          variance=variance,
          ci80_low=ci80[0],
          ci80_high=ci80[1],
          ci95_low=ci95[0],
          ci95_high=ci95[1],
          published_at=now,
        )
      )

    session.add_all(windows)

    forecast_rows = []
    forecast_start = start_date + dt.timedelta(days=days)
    for i in range(forecast_days):
      day = forecast_start + dt.timedelta(days=i)
      values = series[days + i]
      for metric, value in values.items():
        forecast_rows.append(
          Forecast(
            site_id=site_id,
            metric=metric,
            day=day,
            yhat=float(round(value, 2)),
            yhat_lower=float(round(value * 0.9, 2)),
            yhat_upper=float(round(value * 1.1, 2)),
            mape=0.06,
            has_anomaly=False,
            z_score=0.0,
          )
        )

    session.add_all(forecast_rows)
    await session.commit()


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--site-id", default="local-validanalytics-io")
  parser.add_argument("--days", type=int, default=365)
  parser.add_argument("--forecast-days", type=int, default=90)
  args = parser.parse_args()

  asyncio.run(seed(args.site_id, args.days, args.forecast_days))


if __name__ == "__main__":
  main()
