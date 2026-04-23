from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..dashboard_auth import create_access_token, require_dashboard_auth, settings, validate_credentials_async
from ..models import get_session
from ..schemas import AuthLoginRequest, AuthLoginResponse, AuthMeResponse, AuthStatusResponse

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
