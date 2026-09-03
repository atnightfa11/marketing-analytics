from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import _normalize_username, enforce_site_access_with_db, require_dashboard_auth, require_site_owner_with_db
from ..entitlements import effective_plan_for_record, require_team_access
from ..models import DashboardSite, DashboardSiteAccess, DashboardUser, SitePlan, get_session
from ..schemas import SiteAccessGrantRequest, SiteAccessListResponse, SiteAccessMemberResponse

router = APIRouter(prefix="/site-access", tags=["site-access"])


async def _require_standard_site_access_management(session: AsyncSession, site_id: str) -> None:
    plan_record = await session.get(SitePlan, site_id)
    require_team_access(effective_plan_for_record(plan_record))


@router.get("", response_model=SiteAccessListResponse)
async def list_site_access(
    site_id: str,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteAccessListResponse:
    await enforce_site_access_with_db(site_id=site_id, claims=claims, session=session)
    site = await session.get(DashboardSite, site_id)
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    access_rows = (
        await session.execute(
            select(DashboardSiteAccess)
            .where(DashboardSiteAccess.site_id == site_id)
            .order_by(DashboardSiteAccess.created_at.asc(), DashboardSiteAccess.username.asc())
        )
    ).scalars().all()
    members = [
        SiteAccessMemberResponse(
            username=site.owner_username,
            role="owner",
            created_by=None,
            created_at=site.created_at,
        )
    ]
    members.extend(
        SiteAccessMemberResponse(
            username=row.username,
            role="member",
            created_by=row.created_by,
            created_at=row.created_at,
        )
        for row in access_rows
    )
    return SiteAccessListResponse(site_id=site_id, members=members)


@router.post("", response_model=SiteAccessListResponse)
async def grant_site_access(
    payload: SiteAccessGrantRequest,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteAccessListResponse:
    site = await require_site_owner_with_db(site_id=payload.site_id, claims=claims, session=session)
    await _require_standard_site_access_management(session, payload.site_id)
    username = _normalize_username(payload.username)
    if not username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")
    if username == _normalize_username(site.owner_username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The owner already has access")

    user = await session.get(DashboardUser, username)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard user not found")

    existing = (
        await session.execute(
            select(DashboardSiteAccess).where(
                DashboardSiteAccess.site_id == payload.site_id,
                DashboardSiteAccess.username == username,
            )
        )
    ).scalar_one_or_none()
    actor = _normalize_username(claims.get("sub") if isinstance(claims, dict) else None)
    if existing:
        existing.role = payload.role
    else:
        session.add(
            DashboardSiteAccess(
                site_id=payload.site_id,
                username=username,
                role=payload.role,
                created_by=actor,
            )
        )
    await session.commit()
    return await list_site_access(payload.site_id, claims=claims, session=session)


@router.delete("/{username}", response_model=SiteAccessListResponse)
async def revoke_site_access(
    username: str,
    site_id: str,
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> SiteAccessListResponse:
    site = await require_site_owner_with_db(site_id=site_id, claims=claims, session=session)
    await _require_standard_site_access_management(session, site_id)
    normalized_username = _normalize_username(username)
    if not normalized_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")
    if normalized_username == _normalize_username(site.owner_username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The site owner cannot be removed")

    existing = (
        await session.execute(
            select(DashboardSiteAccess).where(
                DashboardSiteAccess.site_id == site_id,
                DashboardSiteAccess.username == normalized_username,
            )
        )
    ).scalar_one_or_none()
    if existing:
        await session.delete(existing)
        await session.commit()
    return await list_site_access(site_id, claims=claims, session=session)
