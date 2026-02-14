from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .models import SitePlan, get_session


async def get_site_plan(site_id: str, session: AsyncSession = Depends(get_session)) -> str:
    record = await session.get(SitePlan, site_id)
    if not record:
        return "free"
    return record.plan
