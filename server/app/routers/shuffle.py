from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import hmac
import ipaddress
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
from ..hostnames import hostname_from_request_headers
from ..models import LdpReport, RawReport, SitePlan, TokenNonce, UploadToken, get_session
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

    stmt = select(UploadToken).where(
        UploadToken.site_id == claims.site_id,
        UploadToken.jti == claims.jti,
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token not registered")
    if record.revoked_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")
    record_exp = record.exp
    if record_exp.tzinfo is None:
        record_exp = record_exp.replace(tzinfo=dt.timezone.utc)
    if now > record_exp:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    try:
        password_hasher.verify(record.token_hash, token)
    except argon_exceptions.VerifyMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalid") from exc


async def resolve_plan(site_id: str, claims_plan: str, session: AsyncSession) -> str:
    record = await session.get(SitePlan, site_id)
    db_plan = record.plan if record else "free"
    token_plan = claims_plan or db_plan
    if token_plan != db_plan:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token plan mismatch")
    if db_plan == "pro" and not settings.ENABLE_PRO_INGEST:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Pro tier is not enabled")
    return db_plan


def _rate_limit_bucket_for_plan(plan: str) -> int:
    if plan == "standard":
        return settings.STANDARD_RATE_LIMIT_BUCKET_PER_MIN
    if plan == "pro":
        return settings.RATE_LIMIT_BUCKET_PER_MIN
    return settings.FREE_RATE_LIMIT_BUCKET_PER_MIN


def _coarsen_ip(ip_value: str) -> str:
    try:
        ip_obj = ipaddress.ip_address(ip_value)
    except ValueError:
        return "unknown"

    if isinstance(ip_obj, ipaddress.IPv4Address):
        prefix = max(0, min(32, settings.SESSION_HMAC_IP_PREFIX_V4))
        network = ipaddress.ip_network(f"{ip_obj}/{prefix}", strict=False)
        return str(network.network_address)

    prefix = max(0, min(128, settings.SESSION_HMAC_IP_PREFIX_V6))
    network = ipaddress.ip_network(f"{ip_obj}/{prefix}", strict=False)
    return str(network.network_address)


def _coarsen_ua(ua: str) -> str:
    if not ua:
        return "unknown"
    head = ua.split(" ", 1)[0]
    if "/" not in head:
        return head[:32].lower()
    family, version = head.split("/", 1)
    major = version.split(".", 1)[0]
    return f"{family[:24].lower()}:{major[:8]}"


def _derive_device_bucket(user_agent: str) -> str:
    if not user_agent:
        return "unknown"
    ua = user_agent.lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobile" in ua or "android" in ua or "iphone" in ua or "ipod" in ua:
        return "mobile"
    return "desktop"


def _derive_country_code(request: Request) -> str:
    # Common reverse-proxy headers. We store only a coarse country code.
    header_candidates = (
        "CF-IPCountry",
        "True-Client-Country",
        "X-Vercel-IP-Country",
        "CloudFront-Viewer-Country",
        "Fly-Client-Country",
        "Fastly-Country-Code",
        "Fastly-Client-Country-Code",
        "X-AppEngine-Country",
        "X-Geo-Country",
        "X-Country-Code",
    )
    for header in header_candidates:
        raw = request.headers.get(header)
        if not raw:
            continue
        value = raw.strip().upper()
        if len(value) == 2 and value.isalpha() and value != "XX":
            return value
    return "unknown"


def _parse_ip_candidate(raw_value: str | None) -> str | None:
    if not isinstance(raw_value, str):
        return None
    candidate = raw_value.strip().strip('"')
    if not candidate or candidate.lower() == "unknown":
        return None

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]

    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        pass

    # IPv4 with port: 203.0.113.10:12345
    if candidate.count(":") == 1 and "." in candidate:
        host, _, maybe_port = candidate.rpartition(":")
        if maybe_port.isdigit():
            try:
                return str(ipaddress.ip_address(host))
            except ValueError:
                return None
    return None


def _parse_forwarded_for(raw_value: str | None) -> str | None:
    if not isinstance(raw_value, str):
        return None
    for candidate in raw_value.split(","):
        parsed = _parse_ip_candidate(candidate)
        if parsed:
            return parsed
    return None


def _parse_forwarded_header(raw_value: str | None) -> str | None:
    # RFC 7239: Forwarded: for=203.0.113.43;proto=https;by=203.0.113.44
    if not isinstance(raw_value, str):
        return None
    for entry in raw_value.split(","):
        parts = [segment.strip() for segment in entry.split(";") if segment.strip()]
        for part in parts:
            if not part.lower().startswith("for="):
                continue
            candidate = part.split("=", 1)[1].strip()
            parsed = _parse_ip_candidate(candidate)
            if parsed:
                return parsed
    return None


def resolve_client_ip(request: Request) -> str:
    direct_headers = ("CF-Connecting-IP", "True-Client-IP", "X-Real-IP")
    for header in direct_headers:
        parsed = _parse_ip_candidate(request.headers.get(header))
        if parsed:
            return parsed

    parsed_xff = _parse_forwarded_for(request.headers.get("X-Forwarded-For"))
    if parsed_xff:
        return parsed_xff

    parsed_forwarded = _parse_forwarded_header(request.headers.get("Forwarded"))
    if parsed_forwarded:
        return parsed_forwarded

    parsed_client = _parse_ip_candidate(request.client.host if request.client else None)
    if parsed_client:
        return parsed_client
    return "unknown"


def derive_standard_session_key(
    *,
    site_id: str,
    server_received_at: dt.datetime,
    ip_value: str,
    user_agent: str,
) -> str | None:
    secret = settings.SESSION_HMAC_SECRET
    if not secret:
        return None
    bucket_minutes = max(1, settings.SESSION_WINDOW_MINUTES)
    bucket_seconds = bucket_minutes * 60
    ts = int(server_received_at.timestamp())
    bucket = ts - (ts % bucket_seconds)
    coarse_ip = _coarsen_ip(ip_value)
    coarse_ua = _coarsen_ua(user_agent)
    canonical = f"{site_id}|{bucket}|{coarse_ip}|{coarse_ua}"
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def derive_daily_visitor_key(
    *,
    site_id: str,
    day: dt.date,
    ip_value: str,
    user_agent: str,
) -> str | None:
    secret = settings.SESSION_HMAC_SECRET
    if not secret:
        return None
    coarse_ip = _coarsen_ip(ip_value)
    coarse_ua = _coarsen_ua(user_agent)
    canonical = f"{site_id}|{day.isoformat()}|{coarse_ip}|{coarse_ua}"
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def apply_rate_limit(site_id: str, ip: str, request: Request, plan: str):
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    key = (site_id, ip)
    events = rate_limiter[key]
    events.append(now)
    one_minute = now - 60
    rate_limiter[key] = [ts for ts in events if ts >= one_minute]
    bucket_size = _rate_limit_bucket_for_plan(plan)
    if len(rate_limiter[key]) > bucket_size:
        counters = request.app.state.prometheus_counters
        counters["requests_rate_limited_total"].labels(site_id=site_id, ip=ip).inc()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limited")


@router.post("/shuffle", status_code=status.HTTP_202_ACCEPTED)
async def shuffle_ingest(
    payload: ShuffleRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    client_ip = resolve_client_ip(request)
    claims = decode_token(payload.token)
    origin = request.headers.get("Origin")
    if not origin:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Origin header is required")
    if not fnmatch(origin, claims.allowed_origin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Origin mismatch")
    await validate_token(claims, payload.token, session)
    plan = await resolve_plan(claims.site_id, claims.plan, session)
    apply_rate_limit(claims.site_id, client_ip, request, plan)

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
    await ingest_reports(collect_payload, request, session, plan, client_ip=client_ip)
    await purge_old_nonces(session)


async def ingest_reports(
    collect: CollectRequest,
    request: Request,
    session: AsyncSession,
    plan: str | None = None,
    client_ip: str | None = None,
):
    counters = request.app.state.prometheus_counters
    effective_plan = plan
    if effective_plan is None:
        record = await session.get(SitePlan, collect.site_id)
        effective_plan = record.plan if record else "free"
    if effective_plan == "pro" and not settings.ENABLE_PRO_INGEST:
        effective_plan = "standard"
    if effective_plan == "standard" and not settings.SESSION_HMAC_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SESSION_HMAC_SECRET is required for standard ingest",
        )

    resolved_client_ip = client_ip or resolve_client_ip(request)
    user_agent = request.headers.get("User-Agent", "")
    request_hostname = hostname_from_request_headers(
        request.headers.get("Origin"),
        request.headers.get("Referer"),
    )
    device_bucket = _derive_device_bucket(user_agent)
    country_code = _derive_country_code(request)
    standard_session_key = (
        derive_standard_session_key(
            site_id=collect.site_id,
            server_received_at=collect.server_received_at,
            ip_value=resolved_client_ip,
            user_agent=user_agent,
        )
        if effective_plan != "pro"
        else None
    )

    for report in collect.reports:
        if report.site_id != collect.site_id:
            continue
        payload_time = report.client_timestamp
        delta = (collect.server_received_at - payload_time).total_seconds()
        if delta > settings.MAX_OUT_OF_ORDER_SECONDS:
            counters["events_dropped_late_total"].labels(site_id=collect.site_id).inc()
            continue

        if effective_plan == "pro":
            record = LdpReport(
                site_id=collect.site_id,
                kind=report.kind,
                day=payload_time.date(),
                payload=report.payload,
                epsilon_used=report.epsilon_used,
                sampling_rate=report.sampling_rate,
                server_received_at=collect.server_received_at,
            )
        else:
            raw_payload = dict(report.payload) if isinstance(report.payload, dict) else {}
            if standard_session_key:
                raw_payload["_session_hmac"] = standard_session_key
            visitor_day_hmac = derive_daily_visitor_key(
                site_id=collect.site_id,
                day=payload_time.date(),
                ip_value=resolved_client_ip,
                user_agent=user_agent,
            )
            if visitor_day_hmac:
                raw_payload["_visitor_day_hmac"] = visitor_day_hmac
            raw_payload.setdefault("_device_bucket", device_bucket)
            raw_payload.setdefault("_country_code", country_code)
            if request_hostname:
                raw_payload.setdefault("_hostname", request_hostname)
            record = RawReport(
                site_id=collect.site_id,
                kind=report.kind,
                day=payload_time.date(),
                payload=raw_payload,
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
