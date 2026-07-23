from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import require_dashboard_auth
from ..dependencies import require_site_access
from ..models import DashboardSite, get_session

router = APIRouter(prefix="/site-settings", tags=["settings"])


class SiteSettingsResponse(BaseModel):
    site_id: str
    site_name: str
    timezone: str


class SiteSettingsUpdate(BaseModel):
    timezone: str | None = None
    site_name: str | None = Field(default=None, max_length=255)


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
        return SiteSettingsResponse(site_id=site_id, site_name=site_id, timezone="UTC")
    return SiteSettingsResponse(site_id=site_id, site_name=site.site_name, timezone=site.timezone or "UTC")


@router.put("", response_model=SiteSettingsResponse, dependencies=[Depends(require_dashboard_auth)])
async def update_site_settings(
    site_id: str,
    payload: SiteSettingsUpdate,
    claims: dict | None = Depends(require_dashboard_auth),
    _: None = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
) -> SiteSettingsResponse:
    if payload.timezone is None and payload.site_name is None:
        raise HTTPException(status_code=400, detail="No settings provided")

    if payload.timezone is not None:
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(payload.timezone)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Invalid timezone") from exc

    site_name = payload.site_name.strip() if payload.site_name is not None else None
    if payload.site_name is not None and not site_name:
        raise HTTPException(status_code=400, detail="Site name is required")

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
            site_name=site_name or site_id,
            allowed_origin="https://pending.invalid",
            timezone=payload.timezone or "UTC",
        )
        session.add(site)
    if payload.timezone is not None:
        site.timezone = payload.timezone
    if site_name is not None:
        site.site_name = site_name
    await session.commit()
    return SiteSettingsResponse(site_id=site.site_id, site_name=site.site_name, timezone=site.timezone)
