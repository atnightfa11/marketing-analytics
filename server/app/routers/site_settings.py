from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import require_dashboard_auth
from ..dependencies import require_site_access
from ..models import DashboardSite, get_session

router = APIRouter(prefix="/site-settings", tags=["settings"])


class SiteSettingsResponse(BaseModel):
    site_id: str
    timezone: str


class SiteSettingsUpdate(BaseModel):
    timezone: str


@router.get("", response_model=SiteSettingsResponse, dependencies=[Depends(require_dashboard_auth)])
async def get_site_settings(
    site_id: str,
    _: None = Depends(require_site_access),
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
    claims: dict | None = Depends(require_dashboard_auth),
    _: None = Depends(require_site_access),
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
        owner_username = claims.get("sub") if isinstance(claims, dict) else None
        if not isinstance(owner_username, str) or not owner_username.strip():
            raise HTTPException(status_code=400, detail="Unable to determine site owner for settings update")
        site = DashboardSite(
            site_id=site_id,
            owner_username=owner_username.strip(),
            site_name=site_id,
            allowed_origin="https://pending.invalid",
            timezone=payload.timezone,
        )
        session.add(site)
    site.timezone = payload.timezone
    await session.commit()
    return SiteSettingsResponse(site_id=site.site_id, timezone=site.timezone)
