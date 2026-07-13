from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache
from urllib.parse import urlsplit

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..dashboard_auth import enforce_site_access_with_db, require_dashboard_auth
from ..entitlements import additional_site_count, entitlements_for_plan, normalize_plan, owned_site_count
from ..models import DashboardSite, SitePlan, get_session
from ..schemas import BillingStatusResponse, CheckoutSessionRequest, CheckoutSessionResponse

router = APIRouter(tags=["billing"])
settings: Settings = get_settings()
logger = logging.getLogger("marketing-analytics.billing")


def _require_stripe_settings() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe is not configured")
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe webhook secret missing")


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme in {"http", "https"} and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return None


@lru_cache(1)
def _allowed_redirect_origins() -> frozenset[str]:
    """Origins a client may redirect to after checkout.

    Derived from the configured Stripe redirect URLs plus the dashboard/marketing
    CORS origins, so a caller can't smuggle an attacker-controlled URL into a
    payment flow served from our domain.
    """
    candidates = (
        settings.STRIPE_CHECKOUT_SUCCESS_URL,
        settings.STRIPE_CHECKOUT_CANCEL_URL,
        settings.STRIPE_SIGNUP_SUCCESS_URL,
        settings.STRIPE_SIGNUP_CANCEL_URL,
        *settings.cors_origins,
    )
    return frozenset(origin for url in candidates if (origin := _origin_of(url)))


def _safe_redirect_url(candidate: str | None, default: str) -> str:
    if not candidate:
        return default
    origin = _origin_of(candidate)
    if origin is None or origin not in _allowed_redirect_origins():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="redirect URL is not allowed")
    return candidate


def _stored_plan_for_checkout_plan(plan: str) -> str:
    if plan == "solo":
        return "free"
    if plan == "early_adopter_standard":
        return "standard"
    return normalize_plan(plan)


def _price_id_for_checkout_plan(plan: str) -> str:
    def require_price_id(value: str, label: str) -> str:
        if not value.startswith("price_"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"{label} is not a Stripe Price ID (expected prefix price_)",
            )
        return value

    if plan == "solo":
        if not settings.STRIPE_SOLO_PRICE_ID:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Solo price is not configured")
        return require_price_id(settings.STRIPE_SOLO_PRICE_ID, "Solo price")
    if plan == "standard":
        if not settings.STRIPE_STANDARD_PRICE_ID:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Standard price is not configured")
        return require_price_id(settings.STRIPE_STANDARD_PRICE_ID, "Standard price")
    if plan == "early_adopter_standard":
        if not settings.STRIPE_EARLY_ADOPTER_STANDARD_PRICE_ID:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Early Adopter Standard price is not configured",
            )
        return require_price_id(settings.STRIPE_EARLY_ADOPTER_STANDARD_PRICE_ID, "Early Adopter Standard price")
    if plan == "pro":
        if not settings.STRIPE_PRO_PRICE_ID:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pro price is not configured")
        return require_price_id(settings.STRIPE_PRO_PRICE_ID, "Pro price")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported plan")


def _plan_for_price_id(price_id: str | None) -> str:
    if not price_id:
        return "free"
    if price_id == settings.STRIPE_SOLO_PRICE_ID:
        return "free"
    if price_id == settings.STRIPE_STANDARD_PRICE_ID:
        return "standard"
    if price_id == settings.STRIPE_EARLY_ADOPTER_STANDARD_PRICE_ID:
        return "standard"
    if price_id == settings.STRIPE_PRO_PRICE_ID:
        return "pro"
    return "free"


def _normalize_plan(raw: str | None) -> str | None:
    if not raw:
        return None
    plan = raw.strip().lower()
    if plan in {"free", "solo", "standard", "pro", "early_adopter_standard"}:
        if plan == "early_adopter_standard":
            return "standard"
        return normalize_plan(plan)
    return None


async def _upsert_site_plan(
    session: AsyncSession,
    *,
    site_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    plan: str | None = None,
) -> None:
    record = None
    if site_id:
        record = await session.get(SitePlan, site_id)
    if not record and customer_id:
        record = (
            await session.execute(select(SitePlan).where(SitePlan.stripe_customer_id == customer_id))
        ).scalar_one_or_none()
    if not record and subscription_id:
        record = (
            await session.execute(select(SitePlan).where(SitePlan.stripe_subscription_id == subscription_id))
        ).scalar_one_or_none()

    now = dt.datetime.now(dt.timezone.utc)
    if record:
        if plan:
            record.plan = plan
        if customer_id:
            record.stripe_customer_id = customer_id
        if subscription_id:
            record.stripe_subscription_id = subscription_id
        record.updated_at = now
    elif site_id:
        session.add(
            SitePlan(
                site_id=site_id,
                plan=plan or "free",
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()


@router.post("/checkout/session", response_model=CheckoutSessionResponse, status_code=status.HTTP_200_OK)
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    await enforce_site_access_with_db(site_id=payload.site_id, claims=auth_claims, session=session)
    _require_stripe_settings()
    stripe.api_key = settings.STRIPE_SECRET_KEY
    checkout_plan = payload.plan
    stored_plan = _stored_plan_for_checkout_plan(checkout_plan)
    price_id = _price_id_for_checkout_plan(checkout_plan)
    base_success_url = _safe_redirect_url(payload.success_url, settings.STRIPE_CHECKOUT_SUCCESS_URL)
    success_sep = "&" if "?" in base_success_url else "?"
    success_url = f"{base_success_url}{success_sep}session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = _safe_redirect_url(payload.cancel_url, settings.STRIPE_CHECKOUT_CANCEL_URL)

    # Ensure the site has a baseline plan row before Stripe events arrive.
    await _upsert_site_plan(session, site_id=payload.site_id, plan="free")

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"site_id": payload.site_id, "plan": stored_plan, "checkout_plan": checkout_plan},
            subscription_data={"metadata": {"site_id": payload.site_id, "plan": stored_plan, "checkout_plan": checkout_plan}},
            client_reference_id=payload.site_id,
            allow_promotion_codes=True,
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc.user_message or str(exc))) from exc

    return CheckoutSessionResponse(checkout_url=checkout_session.url, session_id=checkout_session.id)


@router.get("/billing/status", response_model=BillingStatusResponse, status_code=status.HTTP_200_OK)
async def billing_status(
    site_id: str,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    await enforce_site_access_with_db(site_id=site_id, claims=auth_claims, session=session)
    record = await session.get(SitePlan, site_id)
    plan = record.plan if record else "free"
    entitlements = entitlements_for_plan(plan)
    has_subscription = bool(record and record.stripe_subscription_id)
    site = await session.get(DashboardSite, site_id)
    site_count = max(1, await owned_site_count(session, site.owner_username if site else None))
    return BillingStatusResponse(
        site_id=site_id,
        plan=entitlements.plan,  # type: ignore[arg-type]
        display_plan=entitlements.display_name,
        has_subscription=has_subscription,
        included_sites=entitlements.included_sites,
        owned_site_count=site_count,
        additional_site_count=additional_site_count(plan, site_count),
        extra_site_price_usd=entitlements.extra_site_price_usd,
        aggregate_retention_days=entitlements.aggregate_retention_days,
        can_import_historical_data=entitlements.historical_imports,
        can_manage_anomaly_alerts=entitlements.anomaly_alerts,
        can_manage_site_access=entitlements.team_access,
        forecast_metrics=list(entitlements.forecast_metrics),
    )


@router.post("/stripe/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    _require_stripe_settings()
    stripe.api_key = settings.STRIPE_SECRET_KEY
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=settings.STRIPE_WEBHOOK_SECRET)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload") from exc
    except stripe.error.SignatureVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from exc

    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        metadata = data_object.get("metadata") or {}
        await _upsert_site_plan(
            session,
            site_id=metadata.get("site_id") or data_object.get("client_reference_id"),
            customer_id=data_object.get("customer"),
            subscription_id=data_object.get("subscription"),
            plan=metadata.get("plan") or "free",
        )
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        items = (data_object.get("items") or {}).get("data") or []
        price_id = None
        if items and items[0].get("price"):
            price_id = items[0]["price"].get("id")
        metadata = data_object.get("metadata") or {}
        plan_from_metadata = _normalize_plan(metadata.get("plan"))
        resolved_plan = plan_from_metadata or _plan_for_price_id(price_id)
        await _upsert_site_plan(
            session,
            site_id=metadata.get("site_id"),
            customer_id=data_object.get("customer"),
            subscription_id=data_object.get("id"),
            plan=resolved_plan,
        )
    elif event_type == "customer.subscription.deleted":
        metadata = data_object.get("metadata") or {}
        await _upsert_site_plan(
            session,
            site_id=metadata.get("site_id"),
            customer_id=data_object.get("customer"),
            subscription_id=data_object.get("id"),
            plan="free",
        )
    elif event_type == "invoice.payment_failed":
        logger.warning("Invoice payment failed", extra={"invoice_id": data_object.get("id")})

    return {"status": "ok"}
