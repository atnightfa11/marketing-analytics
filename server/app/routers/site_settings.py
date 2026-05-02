from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import require_dashboard_auth
from ..dependencies import require_site_access
from ..models import DashboardSite, get_session

router = APIRouter(prefix="/api/site-settings", tags=["settings"])


class SiteSettingsResponse(BaseModel):
    site_id: str
    timezone: str


class SiteSettingsUpdate(BaseModel):
    timezone: str


@router.get("", response_model=SiteSettingsResponse, dependencies=[Depends(require_dashboard_auth)])
async def get_site_settings(
    site_id: str,
    _: str = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
) -> SiteSettingsResponse:
    site = (
        await session.execute(select(DashboardSite).where(DashboardSite.site_id == site_id))
    ).scalar_one_or_none()
    if site is None:
        return SiteSettingsResponse(site_id=site_id, timezone="UTC")
    return SiteSettingsResponse(site_id=site_id, timezone=site.timezone or "UTC")


@router.put("", response_model=SiteSettingsResponse, dependencies=[Depends(require_dashboard_auth)])
async def update_site_settings(
    site_id: str,
    payload: SiteSettingsUpdate,
    _: str = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
) -> SiteSettingsResponse:
    try:
        import zoneinfo
        zoneinfo.ZoneInfo(payload.timezone)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid timezone") from exc

    site = (
        await session.execute(select(DashboardSite).where(DashboardSite.site_id == site_id))
    ).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    site.timezone = payload.timezone
    await session.commit()
    return SiteSettingsResponse(site_id=site.site_id, timezone=site.timezone)
