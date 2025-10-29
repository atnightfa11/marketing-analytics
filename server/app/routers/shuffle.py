from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
from collections import defaultdict
from fnmatch import fnmatch
from typing import DefaultDict

from argon2 import PasswordHasher, exceptions as argon_exceptions
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import TokenClaims, get_settings
from ..models import LdpReport, TokenNonce, UploadToken, get_session
from ..schemas import CollectRequest, ShuffleRequest

router = APIRouter(tags=["ingest"])
rate_limiter: DefaultDict[tuple[str, str], list[float]] = defaultdict(list)
password_hasher = PasswordHasher()
settings = get_settings()


def decode_token(token: str) -> TokenClaims:
    try:
        serialized, signature = token.split(".", 1)
        message = base64.urlsafe_b64decode(serialized + "=" * (-len(serialized) % 4))
        provided_sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        expected_sig = hmac.new(
            settings.UPLOAD_TOKEN_SECRET.encode("utf-8"), message, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(provided_sig, expected_sig):
            raise ValueError("Invalid token signature")
        claims = json.loads(message)
        return TokenClaims(**claims)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def validate_token(claims: TokenClaims, token: str, session: AsyncSession):
    now = dt.datetime.now(dt.timezone.utc)
    if now.timestamp() > claims.exp:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    stmt = select(UploadToken).where(UploadToken.site_id == claims.site_id)
    tokens = (await session.execute(stmt)).scalars().all()
    if not tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token not registered")
    verified = False
    for record in tokens:
        if record.revoked_at:
            continue
        try:
            password_hasher.verify(record.token_hash, token)
            verified = True
            break
        except argon_exceptions.VerifyMismatchError:
            continue
    if not verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")


def apply_rate_limit(site_id: str, ip: str, request: Request):
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    key = (site_id, ip)
    events = rate_limiter[key]
    events.append(now)
    one_minute = now - 60
    rate_limiter[key] = [ts for ts in events if ts >= one_minute]
    if len(rate_limiter[key]) > settings.RATE_LIMIT_BUCKET_PER_MIN:
        counters = request.app.state.prometheus_counters
        counters["requests_rate_limited_total"].labels(site_id=site_id, ip=ip).inc()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limited")


@router.post("/shuffle", status_code=status.HTTP_202_ACCEPTED)
async def shuffle_ingest(
    payload: ShuffleRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    claims = decode_token(payload.token)
    origin = request.headers.get("Origin")
    if origin and not fnmatch(origin, claims.allowed_origin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Origin mismatch")
    await validate_token(claims, payload.token, session)
    apply_rate_limit(claims.site_id, request.client.host if request.client else "unknown", request)

    nonce_exists = await session.execute(
        select(TokenNonce).where(TokenNonce.jti == payload.nonce)
    )
    if nonce_exists.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Replay detected")

    session.add(
        TokenNonce(
            site_id=claims.site_id,
            jti=payload.nonce,
        )
    )
    await session.commit()

    delay = secrets.randbelow(121)
    if not request.headers.get("X-Bypass-Delay"):
        await asyncio.sleep(delay)

    server_received_at = dt.datetime.now(dt.timezone.utc)
    collect_payload = CollectRequest(
        site_id=claims.site_id,
        server_received_at=server_received_at,
        reports=payload.batch,
    )
    await ingest_reports(collect_payload, request, session)
    await purge_old_nonces(session)


async def ingest_reports(collect: CollectRequest, request: Request, session: AsyncSession):
    counters = request.app.state.prometheus_counters
    for report in collect.reports:
        if report.site_id != collect.site_id:
            continue
        payload_time = report.client_timestamp
        delta = (collect.server_received_at - payload_time).total_seconds()
        if delta > settings.MAX_OUT_OF_ORDER_SECONDS:
            counters["events_dropped_late_total"].labels(site_id=collect.site_id).inc()
            continue
        record = LdpReport(
            site_id=collect.site_id,
            kind=report.kind,
            day=payload_time.date(),
            payload=report.payload,
            epsilon_used=report.epsilon_used,
            sampling_rate=report.sampling_rate,
            server_received_at=collect.server_received_at,
        )
        session.add(record)
        counters["events_received_total"].labels(site_id=collect.site_id).inc()
    await session.commit()


async def purge_old_nonces(session: AsyncSession):
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=15)
    await session.execute(delete(TokenNonce).where(TokenNonce.seen_at < cutoff))
    await session.commit()
