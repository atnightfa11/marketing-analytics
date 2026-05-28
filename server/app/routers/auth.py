from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import create_access_token, require_dashboard_auth, settings, validate_credentials_async
from ..models import DashboardSite, SitePlan, get_session
from ..schemas import AuthLoginRequest, AuthLoginResponse, AuthMeResponse, AuthStatusResponse, DashboardSiteSummary, DashboardSitesResponse

router = APIRouter(tags=["auth"])


@router.get("/auth/status", response_model=AuthStatusResponse)
async def auth_status() -> AuthStatusResponse:
    return AuthStatusResponse(enabled=settings.DASHBOARD_AUTH_ENABLED)


@router.post("/auth/login", response_model=AuthLoginResponse)
async def auth_login(payload: AuthLoginRequest, session: AsyncSession = Depends(get_session)) -> AuthLoginResponse:
    if not settings.DASHBOARD_AUTH_ENABLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dashboard auth is disabled")
    if not await validate_credentials_async(payload.username, payload.password, session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token, expires_at = create_access_token(payload.username)
    return AuthLoginResponse(access_token=token, expires_at=expires_at)


@router.get("/auth/me", response_model=AuthMeResponse)
async def auth_me(claims: dict = Depends(require_dashboard_auth)) -> AuthMeResponse:
    if not settings.DASHBOARD_AUTH_ENABLED:
        return AuthMeResponse(username="anonymous")
    username = claims.get("sub")
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token")
    return AuthMeResponse(username=username)


@router.get("/sites", response_model=DashboardSitesResponse)
async def list_dashboard_sites(
    claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
) -> DashboardSitesResponse:
    username = claims.get("sub") if isinstance(claims, dict) else None
    normalized_username = username.strip().lower() if isinstance(username, str) else None
    allowed_site_ids: set[str] | None = None
    allow_all_sites = not settings.DASHBOARD_AUTH_ENABLED

    stmt = (
        select(DashboardSite, SitePlan.plan)
        .outerjoin(SitePlan, SitePlan.site_id == DashboardSite.site_id)
        .order_by(DashboardSite.created_at.desc(), DashboardSite.site_id)
    )
    if settings.DASHBOARD_AUTH_ENABLED:
        user_map = {}
        if settings.DASHBOARD_SITE_ACCESS_JSON:
            import json

            try:
                parsed = json.loads(settings.DASHBOARD_SITE_ACCESS_JSON)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Invalid DASHBOARD_SITE_ACCESS_JSON",
                ) from exc
            if not isinstance(parsed, dict):
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="DASHBOARD_SITE_ACCESS_JSON must be a JSON object",
                )
            user_map = parsed

        if normalized_username and normalized_username in user_map:
            raw_site_ids = user_map.get(normalized_username)
            if isinstance(raw_site_ids, str):
                mapped_ids = {raw_site_ids.strip()} if raw_site_ids.strip() else set()
            elif isinstance(raw_site_ids, list):
                mapped_ids = {str(site_id).strip() for site_id in raw_site_ids if str(site_id).strip()}
            else:
                mapped_ids = set()
            if "*" in mapped_ids:
                allow_all_sites = True
            else:
                allowed_site_ids = mapped_ids
        elif settings.DASHBOARD_SITE_ACCESS_JSON:
            if not normalized_username:
                return DashboardSitesResponse(sites=[])
            stmt = stmt.where(DashboardSite.owner_username == normalized_username)
        elif settings.DASHBOARD_ALLOWED_SITE_IDS:
            configured_ids = {item.strip() for item in settings.DASHBOARD_ALLOWED_SITE_IDS.split(",") if item.strip()}
            if "*" in configured_ids:
                allow_all_sites = True
            else:
                allowed_site_ids = configured_ids
        elif normalized_username:
            stmt = stmt.where(DashboardSite.owner_username == normalized_username)
        else:
            return DashboardSitesResponse(sites=[])

        if allowed_site_ids is not None:
            if not allowed_site_ids:
                return DashboardSitesResponse(sites=[])
            stmt = stmt.where(DashboardSite.site_id.in_(allowed_site_ids))

    rows = (await session.execute(stmt)).all()
    sites = [
        DashboardSiteSummary(
            site_id=site.site_id,
            site_name=site.site_name,
            allowed_origin=site.allowed_origin,
            plan=plan or "free",
        )
        for site, plan in rows
    ]

    if not allow_all_sites and allowed_site_ids:
        listed_ids = {site.site_id for site in sites}
        missing_ids = allowed_site_ids - listed_ids
        if missing_ids:
            fallback_rows = (
                await session.execute(select(SitePlan).where(SitePlan.site_id.in_(missing_ids)).order_by(SitePlan.site_id))
            ).scalars().all()
            sites.extend(
                DashboardSiteSummary(
                    site_id=record.site_id,
                    site_name=record.site_id,
                    allowed_origin="",
                    plan=record.plan,
                )
                for record in fallback_rows
            )

    return DashboardSitesResponse(sites=sites)
