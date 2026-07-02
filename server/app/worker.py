from __future__ import annotations

import asyncio
import datetime as dt
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from .config import Settings, get_settings
from .entitlements import forecast_metrics_for_plan
from .geoip_db import ensure_geoip_database
from .maintenance import purge_expired_upload_tokens
from .models import Base, DpWindow, async_engine, async_session_factory, init_db
from .scheduler.nightly_reduce import reduce_reports
from .scheduler.prophet_job import refresh_site_metric_forecast

logger = logging.getLogger("marketing-analytics-worker")
settings: Settings = get_settings()


async def initialize_worker() -> None:
    ensure_geoip_database(settings)
    if settings.AUTO_CREATE_DB_SCHEMA:
        logger.info("AUTO_CREATE_DB_SCHEMA enabled; creating database metadata if missing")
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        logger.info("Skipping create_all; database schema is managed by Alembic migrations")
    await init_db()


async def run_reduce_once() -> None:
    async with async_session_factory() as session:
        await reduce_reports(session)
        deleted_tokens = await purge_expired_upload_tokens(session)
    logger.info("Reducer completed", extra={"deleted_upload_tokens": deleted_tokens})


async def run_forecast_training_once() -> None:
    had_error = False
    async with async_session_factory() as session:
        site_plan_rows = (
            await session.execute(select(DpWindow.site_id, DpWindow.plan).distinct())
        ).all()

        for site_id, plan in site_plan_rows:
            for metric in forecast_metrics_for_plan(plan):
                try:
                    await refresh_site_metric_forecast(session, site_id=site_id, metric=metric, plan=plan)
                except Exception as exc:
                    had_error = True
                    logger.exception(
                        "Forecast training failed",
                        extra={"site_id": site_id, "metric": metric, "plan": plan, "error": str(exc)},
                    )

    if not had_error:
        logger.info("Forecast training completed")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await initialize_worker()

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_reduce_once,
        "interval",
        minutes=max(1, settings.PROD_REDUCER_INTERVAL_MINUTES),
        id="worker_reducer_interval",
        replace_existing=True,
        next_run_time=dt.datetime.now(dt.timezone.utc),
    )
    scheduler.add_job(
        run_forecast_training_once,
        "cron",
        hour=settings.PROD_SCHEDULER_HOUR_UTC,
        minute=15,
        id="worker_forecast_daily",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Started worker scheduler",
        extra={
            "reducer_interval_minutes": settings.PROD_REDUCER_INTERVAL_MINUTES,
            "forecast_hour_utc": settings.PROD_SCHEDULER_HOUR_UTC,
        },
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows fallback
            pass

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        await async_engine.dispose()
        logger.info("Worker scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
