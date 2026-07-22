from __future__ import annotations

import datetime as dt
import logging
import os

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Gauge
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from .config import Settings, get_settings
from .cors import PathAwareCORSMiddleware
from .entitlements import forecast_metrics_for_plan
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .geoip_db import ensure_geoip_database
from .job_status import mark_job_error, mark_job_run, mark_job_success
from .maintenance import purge_expired_upload_tokens
from .metrics_auth import MetricsAuthMiddleware
from .models import async_session_factory
from .ops_alerts import notify_ops_alert
from .scheduler.nightly_reduce import reduce_reports, unreduced_recent_raw_days
from .scheduler.prophet_job import refresh_site_metric_forecast
from .models import Base, async_engine, init_db
from .routers import (
    auth,
    admin,
    alert_webhook,
    aggregates,
    breakdowns,
    forecast,
    health,
    imports,
    ingest,
    job_status,
    metrics as metrics_router,
    notes,
    public_signup,
    site_settings,
    site_access,
    site_alerts,
    site_goals,
    site_health,
    site_shields,
    sdk_bootstrap,
    shuffle,
    stripe_billing,
    upload_token,
)

logger = logging.getLogger("marketing-analytics")

settings: Settings = get_settings()

app = FastAPI(
    title="Marketing Analytics",
    version="1.0.0",
    docs_url="/docs" if settings.expose_docs else None,
    redoc_url=None,
)
Instrumentator().instrument(app).expose(app)

app.add_middleware(PathAwareCORSMiddleware, settings=settings)
app.add_middleware(MetricsAuthMiddleware, settings=settings)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
        response.headers.setdefault(
            "Content-Security-Policy",
            settings.csp_policy,
        )
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response


app.add_middleware(SecurityHeadersMiddleware)

prometheus_counters = {
    "events_received_total": Counter(
        "events_received_total", "Count of events accepted", ["site_id"]
    ),
    "events_dropped_late_total": Counter(
        "events_dropped_late_total", "Count of events dropped for lateness", ["site_id"]
    ),
    "events_dropped_bot_total": Counter(
        "events_dropped_bot_total", "Count of events dropped by bot filter", ["site_id"]
    ),
    "events_dropped_ip_block_total": Counter(
        "events_dropped_ip_block_total", "Count of events dropped by customer IP block list", ["site_id"]
    ),
    "tokens_revoked_total": Counter(
        "tokens_revoked_total", "Count of token revocations", ["site_id"]
    ),
    "requests_rate_limited_total": Counter(
        "requests_rate_limited_total", "Requests dropped for rate limiting", ["site_id", "ip"]
    ),
    "anomaly_flagged_total": Counter(
        "anomaly_flagged_total", "Anomalies flagged by detector", ["site_id", "metric"]
    ),
}
prometheus_gauges = {
    "forecast_mape_gauge": Gauge(
        "forecast_mape_gauge", "Latest forecast MAPE", ["site_id", "metric"]
    )
}
app.state.prometheus_counters = prometheus_counters
app.state.prometheus_gauges = prometheus_gauges


async def run_forecast_training_once():
    mark_job_run("forecast")
    had_error = False
    async with async_session_factory() as session:
        from sqlalchemy import select
        from .models import DpWindow

        site_plan_rows = (
            await session.execute(select(DpWindow.site_id, DpWindow.plan).distinct())
        ).all()

        for site_id, plan in site_plan_rows:
            for metric in forecast_metrics_for_plan(plan):
                try:
                    await refresh_site_metric_forecast(session, site_id=site_id, metric=metric, plan=plan)
                except Exception as exc:
                    had_error = True
                    mark_job_error("forecast", RuntimeError(f"site={site_id} metric={metric} plan={plan}: {exc}"))
                    await notify_ops_alert(
                        source="forecast",
                        severity="critical",
                        message="Forecast training failed",
                        metadata={"site_id": site_id, "metric": metric, "plan": plan, "error": str(exc)},
                    )
                    logger.exception(
                        "Forecast training failed",
                        extra={"site_id": site_id, "metric": metric, "plan": plan},
                    )
    if not had_error:
        mark_job_success("forecast")



@app.on_event("startup")
async def on_startup():
    ensure_geoip_database(settings)
    if settings.AUTO_CREATE_DB_SCHEMA:
        logger.info("AUTO_CREATE_DB_SCHEMA enabled; creating database metadata if missing")
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        logger.info("Skipping create_all; database schema is managed by Alembic migrations")
    await init_db()
    try:
        async with async_session_factory() as session:
            deleted_tokens = await purge_expired_upload_tokens(session)
        if deleted_tokens:
            logger.info("Purged expired upload tokens", extra={"deleted_tokens": deleted_tokens})
    except Exception:
        logger.exception("Failed to purge expired upload tokens on startup")
    # Enable a lightweight reducer loop in dev if requested
    if os.environ.get("ENABLE_DEV_SCHEDULER", "").lower() in {"1", "true", "yes"}:
        try:
            scheduler = AsyncIOScheduler()

            async def job():
                mark_job_run("reduce")
                async with async_session_factory() as session:
                    try:
                        await reduce_reports(session)
                        await purge_expired_upload_tokens(session)
                        mark_job_success("reduce")
                    except Exception as exc:
                        mark_job_error("reduce", exc)
                        await notify_ops_alert(
                            source="dev_reducer",
                            severity="warning",
                            message="Development reducer job failed",
                            metadata={"error": str(exc)},
                        )
                        raise

            scheduler.add_job(job, "interval", seconds=60, id="dev_reducer", replace_existing=True)
            scheduler.start()
            app.state.dev_scheduler = scheduler
            logger.info("Started dev reducer scheduler (every 60s)")
        except Exception:
            logger.exception("Failed to start dev reducer scheduler")

    # Production scheduler for daily reduction and forecast training
    if settings.ENABLE_PROD_SCHEDULER:
        try:
            prod_scheduler = AsyncIOScheduler(timezone="UTC")

            async def reduce_job():
                mark_job_run("reduce")
                reducer_lookback_days = max(1, settings.PROD_REDUCER_LOOKBACK_DAYS)
                async with async_session_factory() as session:
                    try:
                        await reduce_reports(session)
                        catchup_days = await unreduced_recent_raw_days(session, days=reducer_lookback_days)
                        for day in catchup_days:
                            await reduce_reports(session, start_day=day, end_day=day)
                        await purge_expired_upload_tokens(session)
                        mark_job_success("reduce")
                        logger.info(
                            "Production reducer completed",
                            extra={
                                "reducer_lookback_days": reducer_lookback_days,
                                "catchup_days": [day.isoformat() for day in catchup_days],
                            },
                        )
                    except Exception as exc:
                        mark_job_error("reduce", exc)
                        await notify_ops_alert(
                            source="reducer",
                            severity="critical",
                            message="Production reducer job failed",
                            metadata={"error": str(exc)},
                        )
                        raise

            prod_scheduler.add_job(
                reduce_job,
                "interval",
                minutes=max(1, settings.PROD_REDUCER_INTERVAL_MINUTES),
                id="prod_reducer_interval",
                replace_existing=True,
            )
            prod_scheduler.add_job(
                run_forecast_training_once,
                "cron",
                hour=settings.PROD_SCHEDULER_HOUR_UTC,
                minute=15,
                id="prod_forecast_daily",
                replace_existing=True,
                next_run_time=(
                    dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
                    if settings.FORECAST_TRAIN_ON_STARTUP
                    else None
                ),
            )
            prod_scheduler.start()
            app.state.prod_scheduler = prod_scheduler
            logger.info(
                "Started production scheduler (hourly reducer + daily forecast)",
                extra={
                    "reducer_interval_minutes": settings.PROD_REDUCER_INTERVAL_MINUTES,
                    "reducer_lookback_days": settings.PROD_REDUCER_LOOKBACK_DAYS,
                    "forecast_hour_utc": settings.PROD_SCHEDULER_HOUR_UTC,
                    "forecast_train_on_startup": settings.FORECAST_TRAIN_ON_STARTUP,
                },
            )
        except Exception:
            logger.exception("Failed to start production scheduler")


@app.on_event("shutdown")
async def on_shutdown():
    scheduler = getattr(app.state, "dev_scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
    prod_scheduler = getattr(app.state, "prod_scheduler", None)
    if prod_scheduler:
        prod_scheduler.shutdown(wait=False)
    await async_engine.dispose()


app.include_router(upload_token.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(shuffle.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(metrics_router.router, prefix="/api")
app.include_router(aggregates.router, prefix="/api")
app.include_router(breakdowns.router, prefix="/api")
app.include_router(forecast.router, prefix="/api")
app.include_router(imports.router, prefix="/api")
app.include_router(notes.router, prefix="/api")
app.include_router(stripe_billing.router, prefix="/api")
app.include_router(public_signup.router, prefix="/api")
app.include_router(site_settings.router, prefix="/api")
app.include_router(site_access.router, prefix="/api")
app.include_router(site_alerts.router, prefix="/api")
app.include_router(site_goals.router, prefix="/api")
app.include_router(site_health.router, prefix="/api")
app.include_router(site_shields.router, prefix="/api")
app.include_router(sdk_bootstrap.router, prefix="/api")
app.include_router(job_status.router, prefix="/api")
app.include_router(alert_webhook.router, prefix="/api")
app.include_router(health.router)
