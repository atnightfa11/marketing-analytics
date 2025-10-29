from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import CollectRequest
from ..models import get_session
from .shuffle import ingest_reports

router = APIRouter(tags=["ingest"])


@router.post("/collect", status_code=status.HTTP_202_ACCEPTED)
async def collect(
    payload: CollectRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),  # type: ignore
):
    await ingest_reports(payload, request, session)
