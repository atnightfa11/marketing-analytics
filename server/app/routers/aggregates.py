from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DpWindow, get_session
from ..schemas import AggregateResponse, WindowAggregate

router = APIRouter(tags=["metrics"])


@router.get("/aggregate", response_model=AggregateResponse)
async def aggregate(
    site_id: str,
    metric: str,
    window: str = Query(default="standard", regex="^(live|standard)$"),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(DpWindow).where(DpWindow.site_id == site_id, DpWindow.metric == metric)
    if window == "live":
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)
        stmt = stmt.where(DpWindow.window_start >= cutoff)
    rows = (await session.execute(stmt)).scalars().all()
    windows = [
        WindowAggregate(
            window_start=row.window_start,
            window_end=row.window_end,
            value=row.value,
            variance=row.variance,
            ci80={"low": row.ci80_low, "high": row.ci80_high},
            ci95={"low": row.ci95_low, "high": row.ci95_high},
        )
        for row in rows
    ]
    return AggregateResponse(site_id=site_id, metric=metric, windows=windows)
