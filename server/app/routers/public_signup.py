from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from typing import DefaultDict
from urllib.parse import quote_plus

import stripe
from argon2 import PasswordHasher
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import create_access_token
from ..models import DashboardSite, DashboardUser, SiteApiKey, SitePlan, get_session
from ..schemas import PublicSignupRequest, PublicSignupResponse
from ..site_keys import build_site_key, canonical_origin_for_domain, hash_site_key, site_id_from_domain

router = APIRouter(tags=["public-signup"])
settings = get_settings()
password_hasher = PasswordHasher()
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
signup_rate_limiter: DefaultDict[str, list[float]] = defaultdict(list)
MAX_SIGNUPS_PER_MINUTE = 20


def _apply_signup_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    events = signup_rate_limiter[ip]
    events.append(now)
    one_minute = now - 60
    signup_rate_limiter[ip] = [ts for ts in events if ts >= one_minute]
    if len(signup_rate_limiter[ip]) > MAX_SIGNUPS_PER_MINUTE:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limited")


def _normalize_username(raw: str) -> str:
    username = raw.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3-64 chars: letters, numbers, dot, underscore, or dash",
        )
    return username


def _normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email")
    return email


async def _next_unique_site_id(base_site_id: str, session: AsyncSession) -> str:
    candidate = base_site_id
    suffix = 1
    while True:
        existing = (
            await session.execute(
                select(SitePlan.site_id).where(SitePlan.site_id == candidate)
            )
        ).scalar_one_or_none()
        if not existing:
            return candidate
        suffix += 1
        candidate = f"{base_site_id}-{suffix}"


def _create_checkout_session_for_signup(site_id: str, plan: str) -> str:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe is not configured")
    if plan != "standard":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported paid plan")
    if not settings.STRIPE_STANDARD_PRICE_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Standard plan is not configured",
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY
    success_url = (
        f"{settings.STRIPE_SIGNUP_SUCCESS_URL}"
        f"?site_id={quote_plus(site_id)}&plan=standard&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{settings.STRIPE_SIGNUP_CANCEL_URL}?site_id={quote_plus(site_id)}&plan=standard"
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[{"price": settings.STRIPE_STANDARD_PRICE_ID, "quantity": 1}],
            metadata={"site_id": site_id, "plan": "standard"},
            subscription_data={"metadata": {"site_id": site_id, "plan": "standard"}},
            client_reference_id=site_id,
            allow_promotion_codes=True,
        )
    except stripe.error.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc.user_message or str(exc)),
        ) from exc
    if not checkout_session.url:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Checkout URL unavailable")
    return checkout_session.url


@router.post("/public/signup", response_model=PublicSignupResponse, status_code=status.HTTP_201_CREATED)
async def public_signup(
    payload: PublicSignupRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PublicSignupResponse:
    if not settings.DASHBOARD_AUTH_ENABLED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signup is unavailable")

    _apply_signup_rate_limit(request)
    username = _normalize_username(payload.username)
    email = _normalize_email(payload.email)
    site_name = payload.site_name.strip()
    if not site_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="site_name is required")

    user_exists = await session.get(DashboardUser, username)
    if user_exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username is already in use")
    email_exists = (
        await session.execute(select(DashboardUser.username).where(DashboardUser.email == email))
    ).scalar_one_or_none()
    if email_exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already in use")

    allowed_origin = canonical_origin_for_domain(payload.site_domain)
    base_site_id = site_id_from_domain(allowed_origin)
    site_id = await _next_unique_site_id(base_site_id, session)

    checkout_url: str | None = None
    if payload.plan == "standard":
        checkout_url = _create_checkout_session_for_signup(site_id, payload.plan)

    key_id, key_prefix, plaintext_site_key = build_site_key()
    user = DashboardUser(
        username=username,
        email=email,
        password_hash=password_hasher.hash(payload.password),
    )
    site = DashboardSite(
        site_id=site_id,
        owner_username=username,
        site_name=site_name,
        allowed_origin=allowed_origin,
    )
    plan = SitePlan(site_id=site_id, plan="free")
    site_key = SiteApiKey(
        site_id=site_id,
        key_id=key_id,
        key_prefix=key_prefix,
        key_hash=hash_site_key(plaintext_site_key),
        allowed_origin_pattern=allowed_origin,
        is_active=True,
    )

    session.add(user)
    session.add(site)
    session.add(plan)
    session.add(site_key)
    await session.commit()

    access_token, expires_at = create_access_token(username)
    return PublicSignupResponse(
        username=username,
        access_token=access_token,
        expires_at=expires_at,
        site_id=site_id,
        site_name=site_name,
        site_domain=allowed_origin,
        site_key=plaintext_site_key,
        checkout_url=checkout_url,
        requires_checkout=payload.plan == "standard",
    )

