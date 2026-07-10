from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import get_session
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health/liveness", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def liveness():
    return HealthResponse(status="ok", checks={"app": True})


@router.get("/health/readiness", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def readiness(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not ready") from exc
    checks = {
        "database": True,
        "dashboard_auth_configured": settings.auth_configured(),
        "billing_configured": (not settings.BILLING_ENABLED) or settings.billing_configured(),
        "production_secrets_configured": (not settings.production_like()) or settings.production_secrets_configured(),
        "metrics_exposure_safe": settings.metrics_exposure_safe(),
    }
    details = {
        "dashboard_auth_enabled": settings.DASHBOARD_AUTH_ENABLED,
        "billing_enabled": settings.BILLING_ENABLED,
        "production_like": settings.production_like(),
        "valid_process_type": settings.VALID_PROCESS_TYPE,
        "metrics_public": settings.METRICS_PUBLIC,
        "metrics_auth_configured": bool(settings.METRICS_AUTH_TOKEN),
    }
    if not all(checks.values()):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={"checks": checks, "details": details})
    return HealthResponse(status="ok", checks=checks, details=details)
