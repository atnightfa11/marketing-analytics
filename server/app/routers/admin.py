from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import UploadToken, get_session
from ..schemas import RevokeTokenRequest, RevokeTokensRequest

router = APIRouter(tags=["admin"])


@router.post("/admin/revoke-token", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    payload: RevokeTokenRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(UploadToken)
    if payload.jti:
        stmt = stmt.where(UploadToken.jti == payload.jti)
    elif payload.token_hash:
        stmt = stmt.where(UploadToken.token_hash == payload.token_hash)
    token = (await session.execute(stmt)).scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    token.revoked_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    counters = request.app.state.prometheus_counters
    counters["tokens_revoked_total"].labels(site_id=token.site_id).inc()


@router.post("/admin/revoke-tokens", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_tokens(
    payload: RevokeTokensRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    now = dt.datetime.now(dt.timezone.utc)
    await session.execute(
        update(UploadToken)
        .where(UploadToken.site_id == payload.site_id)
        .values(revoked_at=now)
    )
    await session.commit()
    counters = request.app.state.prometheus_counters
    counters["tokens_revoked_total"].labels(site_id=payload.site_id).inc()
