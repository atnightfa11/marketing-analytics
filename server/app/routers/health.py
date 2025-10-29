from __future__ import annotations

from fastapi import APIRouter, status

from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health/liveness", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def liveness():
    return HealthResponse(status="ok")


@router.get("/health/readiness", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def readiness():
    return HealthResponse(status="ok")
