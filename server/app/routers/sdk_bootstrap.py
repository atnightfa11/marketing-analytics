from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import DefaultDict
from urllib.parse import urlsplit

from argon2 import PasswordHasher, exceptions as argon_exceptions
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import require_dashboard_auth
from ..dependencies import require_site_access
from ..models import RawReport, SiteApiKey, SitePlan, get_session
from ..origin_policy import origin_matches_allowed_pattern
from ..routers.upload_token import issue_upload_token
from ..schemas import SdkBootstrapConfig, SdkBootstrapRequest, SdkBootstrapResponse, SdkInstallVerifyResponse

router = APIRouter(tags=["sdk"])
settings = get_settings()
password_hasher = PasswordHasher()
bootstrap_rate_limiter: DefaultDict[tuple[str, str, str], list[float]] = defaultdict(list)


def _parse_site_key(site_key: str) -> tuple[str, str]:
    # Format: <prefix>_<key_id>_<secret>
    prefix = settings.SDK_SITE_KEY_PREFIX
    if not site_key.startswith(f"{prefix}_"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid site key")
    parts = site_key.split("_", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid site key")
    return parts[1], site_key


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Origin header")
    return f"{parsed.scheme}://{parsed.netloc}"


def _apply_bootstrap_rate_limit(site_id: str, origin: str, ip: str) -> None:
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    key = (site_id, origin, ip)
    events = bootstrap_rate_limiter[key]
    events.append(now)
    one_minute = now - 60
    bootstrap_rate_limiter[key] = [ts for ts in events if ts >= one_minute]
    if len(bootstrap_rate_limiter[key]) > settings.SDK_BOOTSTRAP_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limited")


@router.post("/sdk/bootstrap", response_model=SdkBootstrapResponse)
async def sdk_bootstrap(
    payload: SdkBootstrapRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    origin = request.headers.get("Origin")
    if not origin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Origin header is required")
    origin = _normalize_origin(origin)

    key_id, provided_key = _parse_site_key(payload.site_key)
    key_record = (
        await session.execute(
            select(SiteApiKey).where(
                SiteApiKey.key_id == key_id,
            )
        )
    ).scalar_one_or_none()
    if not key_record or not key_record.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Site key is invalid or inactive")
    if payload.site_id and payload.site_id != key_record.site_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Site key does not match site_id")
    if not settings.SDK_ALLOW_WILDCARD_ORIGIN_KEYS and "*" in key_record.allowed_origin_pattern:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wildcard key origins are disabled by policy",
        )

    try:
        password_hasher.verify(key_record.key_hash, provided_key)
    except argon_exceptions.VerifyMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Site key is invalid") from exc

    if not origin_matches_allowed_pattern(origin, key_record.allowed_origin_pattern):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed for this site key")

    ip = request.client.host if request.client else "unknown"
    _apply_bootstrap_rate_limit(key_record.site_id, origin, ip)

    plan_record = await session.get(SitePlan, key_record.site_id)
    plan = plan_record.plan if plan_record else "free"
    if plan == "pro" and not settings.ENABLE_PRO_INGEST:
        plan = "standard"

    token, exp, _ = await issue_upload_token(
        session=session,
        site_id=key_record.site_id,
        allowed_origin=key_record.allowed_origin_pattern,
        epsilon_budget=1.0,
        sampling_rate=1.0,
        plan=plan,
        ttl_seconds=settings.UPLOAD_TOKEN_TTL_SECONDS,
        request_origin=origin,
    )

    return SdkBootstrapResponse(
        upload_token=token,
        expires_at=exp,
        config=SdkBootstrapConfig(
            site_id=key_record.site_id,
            sampling_rate=1.0,
            epsilon_budget=1.0,
            shuffle_url="/api/shuffle",
            token_ttl_seconds=settings.UPLOAD_TOKEN_TTL_SECONDS,
        ),
    )


@router.get(
    "/sdk/verify-install",
    response_model=SdkInstallVerifyResponse,
    dependencies=[Depends(require_dashboard_auth)],
)
async def sdk_verify_install(
    site_id: str,
    lookback_minutes: int = Query(default=15, ge=1, le=24 * 60),
    _: None = Depends(require_site_access),
    session: AsyncSession = Depends(get_session),
):
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(minutes=lookback_minutes)

    counts_rows = (
        await session.execute(
            select(RawReport.kind, func.count(RawReport.id))
            .where(
                RawReport.site_id == site_id,
                RawReport.server_received_at >= cutoff,
            )
            .group_by(RawReport.kind)
        )
    ).all()
    counts_by_kind = {kind: int(count) for kind, count in counts_rows}
    recent_reports = int(sum(counts_by_kind.values()))

    last_report_at = (
        await session.execute(
            select(func.max(RawReport.server_received_at)).where(
                RawReport.site_id == site_id,
                RawReport.server_received_at >= cutoff,
            )
        )
    ).scalar_one_or_none()

    return SdkInstallVerifyResponse(
        site_id=site_id,
        lookback_minutes=lookback_minutes,
        has_recent_activity=recent_reports > 0,
        recent_reports=recent_reports,
        counts_by_kind=counts_by_kind,
        last_report_at=last_report_at,
    )
