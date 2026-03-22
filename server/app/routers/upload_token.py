from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
from fnmatch import fnmatch
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, TokenClaims, get_settings
from ..models import UploadToken, get_session
from ..schemas import UploadTokenRequest, UploadTokenResponse

router = APIRouter(tags=["tokens"])
password_hasher = PasswordHasher()
settings: Settings = get_settings()


def sign_claims(claims: dict[str, str | float | int]) -> str:
    message = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(
        settings.UPLOAD_TOKEN_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    return f"{base64.urlsafe_b64encode(message).decode().rstrip('=')}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid origin")
    return f"{parsed.scheme}://{parsed.netloc}"


@router.post("/upload-token", response_model=UploadTokenResponse, status_code=status.HTTP_200_OK)
async def create_upload_token(
    payload: UploadTokenRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    token, exp, jti = await issue_upload_token(
        session=session,
        site_id=payload.site_id,
        allowed_origin=payload.allowed_origin,
        epsilon_budget=payload.epsilon_budget,
        sampling_rate=payload.sampling_rate,
        plan=payload.plan,
        ttl_seconds=payload.ttl_seconds,
        request_origin=request.headers.get("Origin"),
    )
    return UploadTokenResponse(token=token, expires_at=exp, jti=jti)


async def issue_upload_token(
    *,
    session: AsyncSession,
    site_id: str,
    allowed_origin: str,
    epsilon_budget: float,
    sampling_rate: float,
    plan: str = "free",
    ttl_seconds: int | None = None,
    request_origin: str | None = None,
) -> tuple[str, dt.datetime, str]:
    ttl = ttl_seconds or settings.UPLOAD_TOKEN_TTL_SECONDS
    now = dt.datetime.now(dt.timezone.utc)
    exp = now + dt.timedelta(seconds=ttl)
    if ttl > settings.UPLOAD_TOKEN_TTL_SECONDS * 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TTL exceeds policy")

    normalized_origin = _normalize_origin(request_origin) if request_origin else None
    if normalized_origin and not fnmatch(normalized_origin, allowed_origin):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Origin does not match allowed pattern")

    claims = TokenClaims(
        site_id=site_id,
        plan=plan,
        allowed_origin=allowed_origin,
        iat=int(now.timestamp()),
        exp=int(exp.timestamp()),
        jti=secrets.token_hex(16),
        sampling_rate=sampling_rate,
        epsilon_budget=epsilon_budget,
    )

    token = sign_claims(claims.model_dump())
    hashed = password_hasher.hash(token)

    record = UploadToken(
        site_id=site_id,
        jti=claims.jti,
        token_hash=hashed,
        iat=now,
        exp=exp,
        allowed_origin=allowed_origin,
        sampling_rate=sampling_rate,
        epsilon_budget=epsilon_budget,
    )
    session.add(record)
    await session.commit()

    return token, exp, claims.jti
