"""Owner-scoped, retry-safe site creation with explicitly approved extra slots."""
import asyncio
import hashlib
import hmac
from uuid import UUID

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..dashboard_auth import require_dashboard_auth
from ..entitlements import (
    account_subscription,
    collection_is_active,
    effective_plan_for_record,
    owned_site_count,
)
from ..models import (
    DashboardSite,
    DashboardUser,
    SiteApiKey,
    SitePlan,
    SiteProvisioning,
    get_session,
)
from ..site_keys import canonical_origin_for_domain, hash_site_key, site_id_from_domain
from .stripe_billing import _object_get, _price_id_for_item, _stripe_items

router = APIRouter(tags=["sites"])
settings = get_settings()


class CreateSite(BaseModel):
    request_id: UUID
    site_name: str = Field(min_length=1, max_length=255)
    site_domain: str = Field(min_length=3, max_length=255)
    approved_monthly_increase_usd: int = Field(default=0, ge=0, le=5)


async def owner_lock(session, claims):
    username = (claims or {}).get("sub", "")
    user = await session.scalar(
        select(DashboardUser)
        .where(DashboardUser.username == username)
        .with_for_update()
    )
    if not user:
        raise HTTPException(403, "Sign in to an owner account to add a website.")
    return user


def public_request(row):
    return {
        "request_id": row.request_id,
        "site_id": row.site_id,
        "site_name": row.site_name,
        "site_domain": row.allowed_origin,
        "status": row.status,
    }


@router.get("/sites/provisioning")
async def pending_site(
    claims=Depends(require_dashboard_auth), session: AsyncSession = Depends(get_session)
):
    owner = await owner_lock(session, claims)
    row = await session.scalar(
        select(SiteProvisioning).where(
            SiteProvisioning.owner_username == owner.username,
            SiteProvisioning.status == "pending",
        )
    )
    return public_request(row) if row else None


def provisioned_key(row):
    # The public installation key is recoverable for owner retries without storing
    # plaintext credentials. Domain separation keeps it independent of upload tokens.
    if not settings.UPLOAD_TOKEN_SECRET:
        raise HTTPException(503, "Site key signing is not configured")
    key_id = UUID(row.request_id).hex[:16]
    secret = hmac.new(
        settings.UPLOAD_TOKEN_SECRET.encode(),
        f"site-key-v1:{row.owner_username}:{row.request_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return key_id, f"{settings.SDK_SITE_KEY_PREFIX}_{key_id}_{secret}"


def purchase_slots(row):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    subscription = stripe.Subscription.retrieve(row.subscription_id)
    if _object_get(subscription, "status") not in {"active", "trialing"}:
        raise HTTPException(
            409, "Restore the subscription in Manage billing before adding a website."
        )
    price = settings.STRIPE_ADDITIONAL_SITE_PRICE_ID
    item = next(
        (
            item
            for item in _stripe_items(subscription)
            if _price_id_for_item(item) == price
        ),
        None,
    )
    if item and int(_object_get(item, "quantity", 0) or 0) >= row.extra_quantity:
        return _object_get(item, "id"), int(_object_get(item, "quantity"))
    options = {
        "quantity": row.extra_quantity,
        "proration_behavior": "none",
        "idempotency_key": f"valid-site:{row.request_id}",
    }
    if item:
        item = stripe.SubscriptionItem.modify(_object_get(item, "id"), **options)
    else:
        item = stripe.SubscriptionItem.create(
            subscription=row.subscription_id, price=price, **options
        )
    return _object_get(item, "id"), row.extra_quantity


@router.post("/sites")
async def create_site(
    payload: CreateSite,
    claims=Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    owner = await owner_lock(session, claims)
    name = payload.site_name.strip()
    if not name:
        raise HTTPException(400, "Site name is required")
    origin = canonical_origin_for_domain(payload.site_domain)
    request_id = str(payload.request_id)
    row = await session.get(SiteProvisioning, request_id)
    if row and (
        row.owner_username != owner.username
        or row.site_name != name
        or row.allowed_origin != origin
    ):
        raise HTTPException(409, "This request belongs to a different website")
    account, ambiguous = await account_subscription(session, owner.username)
    if row is None:
        pending = await session.scalar(
            select(SiteProvisioning.request_id).where(
                SiteProvisioning.owner_username == owner.username,
                SiteProvisioning.status == "pending",
            )
        )
        if pending:
            raise HTTPException(
                409, "Finish your pending website setup before adding another."
            )
        if (
            ambiguous
            or not collection_is_active(account)
            or effective_plan_for_record(account) != "standard"
        ):
            raise HTTPException(
                403, "Adding websites requires an active Standard subscription."
            )
        duplicate = await session.scalar(
            select(DashboardSite.site_id).where(
                DashboardSite.owner_username == owner.username,
                DashboardSite.allowed_origin == origin,
            )
        )
        if duplicate:
            raise HTTPException(409, "This website is already on your account")
        extra = max(0, await owned_site_count(session, owner.username) + 1 - 3)
        if extra > (account.extra_site_quantity or 0):
            if extra - (account.extra_site_quantity or 0) != 1:
                raise HTTPException(
                    409,
                    "Existing website capacity needs review. Contact support before adding another website.",
                )
            if payload.approved_monthly_increase_usd != 5:
                raise HTTPException(
                    409, "This website adds $5/month. Approve the increase to continue."
                )
            if not settings.STRIPE_SECRET_KEY or not (
                settings.STRIPE_ADDITIONAL_SITE_PRICE_ID or ""
            ).startswith("price_"):
                raise HTTPException(
                    503,
                    "Additional-site billing is not configured. No website or charge was created.",
                )
        row = SiteProvisioning(
            request_id=request_id,
            owner_username=owner.username,
            site_id=f"{site_id_from_domain(origin)}-{payload.request_id.hex[:8]}",
            site_name=name,
            allowed_origin=origin,
            status="pending",
            subscription_id=account.stripe_subscription_id,
            extra_quantity=extra if extra > (account.extra_site_quantity or 0) else 0,
        )
        session.add(row)
        await session.commit()
    if row.status == "complete":
        return {**public_request(row), "site_key": provisioned_key(row)[1]}
    if (
        ambiguous
        or not account
        or account.stripe_subscription_id != row.subscription_id
    ):
        raise HTTPException(
            409, "The account subscription changed. Contact support to finish setup."
        )
    item_id, quantity = None, None
    if row.extra_quantity:
        try:
            item_id, quantity = await asyncio.to_thread(purchase_slots, row)
        except stripe.error.StripeError as exc:
            raise HTTPException(
                502,
                "Billing could not be confirmed. Retry this setup; it will not create a duplicate charge.",
            ) from exc
    # Serialize finalization, including simultaneous retries of the same request.
    await owner_lock(session, claims)
    await session.refresh(row)
    if row.status != "complete":
        await session.refresh(account)
        if (
            not collection_is_active(account)
            or effective_plan_for_record(account) != "standard"
        ):
            raise HTTPException(
                409, "Restore your Standard subscription before finishing setup."
            )
        key_id, key = provisioned_key(row)
        session.add(
            DashboardSite(
                site_id=row.site_id,
                owner_username=row.owner_username,
                site_name=row.site_name,
                allowed_origin=row.allowed_origin,
            )
        )
        session.add(SitePlan(site_id=row.site_id, plan="free"))
        session.add(
            SiteApiKey(
                site_id=row.site_id,
                key_id=key_id,
                key_prefix=f"{settings.SDK_SITE_KEY_PREFIX}_{key_id}",
                key_hash=hash_site_key(key),
                allowed_origin_pattern=row.allowed_origin,
                is_active=True,
            )
        )
        if quantity is not None:
            account.extra_site_quantity = quantity
            account.extra_site_subscription_item_id = item_id
        row.status = "complete"
        await session.commit()
    return {**public_request(row), "site_key": provisioned_key(row)[1]}
