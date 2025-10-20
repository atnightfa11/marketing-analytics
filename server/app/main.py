from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette_prometheus import metrics, PrometheusMiddleware
from .middleware import SecurityHeadersMiddleware
from .config import settings
from .routers import health, shuffle, ingest, upload_token, admin

def create_app() -> FastAPI:
    app = FastAPI(title="Zero-Access Analytics API", version="1.0.0")

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # token claim still enforces allowed origin in shuffle
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if settings.PROMETHEUS_ENABLED:
        app.add_middleware(PrometheusMiddleware)
        app.add_route("/metrics", metrics)

    app.include_router(health.router)
    app.include_router(upload_token.router)
    app.include_router(admin.router)
    app.include_router(shuffle.router)
    app.include_router(ingest.router)
    return app

app = create_app()
