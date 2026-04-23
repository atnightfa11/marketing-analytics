from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .dashboard_auth import enforce_site_access_with_db, require_dashboard_auth
from .models import SitePlan, get_session


async def get_site_plan(site_id: str, session: AsyncSession = Depends(get_session)) -> str:
    record = await session.get(SitePlan, site_id)
    if not record:
        return "free"
    return record.plan


async def require_site_access(
    site_id: str,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> None:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
