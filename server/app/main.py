from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from .config import Settings, get_settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .models import async_session_factory
from .scheduler.nightly_reduce import reduce_reports
from .models import Base, async_engine, init_db
from .routers import (
    admin,
    alert_webhook,
    aggregates,
    forecast,
    health,
    ingest,
    metrics as metrics_router,
    shuffle,
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
    expose_headers=["Retry-After"],
)


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


@app.on_event("startup")
async def on_startup():
    logger.info("Creating database metadata if missing")
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_db()
    # Enable a lightweight reducer loop in dev if requested
    if os.environ.get("ENABLE_DEV_SCHEDULER", "").lower() in {"1", "true", "yes"}:
        try:
            scheduler = AsyncIOScheduler()
            async def job():
                async with async_session_factory() as session:
                    await reduce_reports(session)
            scheduler.add_job(job, "interval", seconds=60, id="dev_reducer", replace_existing=True)
            scheduler.start()
            app.state.dev_scheduler = scheduler
            logger.info("Started dev reducer scheduler (every 60s)")
        except Exception:
            logger.exception("Failed to start dev reducer scheduler")


@app.on_event("shutdown")
async def on_shutdown():
    scheduler = getattr(app.state, "dev_scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
    await async_engine.dispose()


app.include_router(upload_token.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(shuffle.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(metrics_router.router, prefix="/api")
app.include_router(aggregates.router, prefix="/api")
app.include_router(forecast.router, prefix="/api")
app.include_router(alert_webhook.router, prefix="/api")
app.include_router(health.router)
