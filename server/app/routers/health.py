from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import get_session
from ..schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health/liveness", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def liveness():
    return HealthResponse(status="ok")


@router.get("/health/readiness", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def readiness(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not ready") from exc
    return HealthResponse(status="ok")
