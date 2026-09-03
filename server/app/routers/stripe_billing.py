from __future__ import annotations

import datetime as dt
import logging
from functools import lru_cache
from urllib.parse import urlsplit

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..dashboard_auth import enforce_site_access_with_db, require_dashboard_auth
from ..entitlements import (
    ACTIVE_SUBSCRIPTION_STATUSES,
    ENDED_SUBSCRIPTION_STATUSES,
    GRACE_SUBSCRIPTION_STATUSES,
    additional_site_count,
    effective_plan_for_record,
    entitlements_for_plan,
    normalize_plan,
    owned_site_count,
)
from ..models import DashboardSite, SitePlan, StripeEvent, get_session
from ..schemas import (
    BillingPortalSessionRequest,
    BillingPortalSessionResponse,
    BillingStatusResponse,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
)

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
        settings.STRIPE_CUSTOMER_PORTAL_RETURN_URL,
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


def _require_price_id(value: str | None, label: str) -> str:
    if not value:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{label} is not configured")
    if not value.startswith("price_"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{label} is not a Stripe Price ID (expected prefix price_)",
        )
    return value


def _additional_site_price_id() -> str:
    return _require_price_id(settings.STRIPE_ADDITIONAL_SITE_PRICE_ID, "Additional site price")


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


def _object_get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _timestamp_to_datetime(value) -> dt.datetime | None:
    if value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(int(value), tz=dt.timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _stripe_items(data_object) -> list:
    items = _object_get(data_object, "items", {}) or {}
    data = _object_get(items, "data", []) or []
    return list(data)


def _price_id_for_item(item) -> str | None:
    price = _object_get(item, "price", {}) or {}
    return _object_get(price, "id")


def _base_subscription_price_id(data_object) -> str | None:
    extra_price_id = settings.STRIPE_ADDITIONAL_SITE_PRICE_ID
    for item in _stripe_items(data_object):
        price_id = _price_id_for_item(item)
        if price_id and price_id != extra_price_id:
            return price_id
    return None


def _extra_site_item_state(data_object) -> tuple[str | None, int]:
    extra_price_id = settings.STRIPE_ADDITIONAL_SITE_PRICE_ID
    if not extra_price_id:
        return None, 0
    for item in _stripe_items(data_object):
        if _price_id_for_item(item) == extra_price_id:
            quantity = _object_get(item, "quantity", 0) or 0
            try:
                parsed_quantity = int(quantity)
            except (TypeError, ValueError):
                parsed_quantity = 0
            return _object_get(item, "id"), max(0, parsed_quantity)
    return None, 0


def _subscription_status_fields(data_object) -> dict:
    extra_item_id, extra_quantity = _extra_site_item_state(data_object)
    return {
        "subscription_status": (_object_get(data_object, "status") or "").strip().lower() or None,
        "current_period_end": _timestamp_to_datetime(_object_get(data_object, "current_period_end")),
        "cancel_at_period_end": bool(_object_get(data_object, "cancel_at_period_end", False)),
        "extra_site_subscription_item_id": extra_item_id,
        "extra_site_quantity": extra_quantity,
    }


def _apply_subscription_status(
    record: SitePlan,
    subscription_status: str | None,
    *,
    now: dt.datetime,
) -> None:
    if not subscription_status:
        return
    status_value = subscription_status.strip().lower()
    record.stripe_subscription_status = status_value
    if status_value in ACTIVE_SUBSCRIPTION_STATUSES:
        record.billing_past_due_at = None
        record.billing_grace_ends_at = None
    elif status_value in GRACE_SUBSCRIPTION_STATUSES:
        if record.billing_past_due_at is None:
            record.billing_past_due_at = now
        if record.billing_grace_ends_at is None:
            record.billing_grace_ends_at = now + dt.timedelta(days=settings.STRIPE_PAYMENT_FAILURE_GRACE_DAYS)
    elif status_value in ENDED_SUBSCRIPTION_STATUSES:
        record.plan = "free"
        record.billing_past_due_at = None
        record.billing_grace_ends_at = None
        record.extra_site_subscription_item_id = None
        record.extra_site_quantity = 0


async def _upsert_site_plan(
    session: AsyncSession,
    *,
    site_id: str | None = None,
    customer_id: str | None = None,
    subscription_id: str | None = None,
    plan: str | None = None,
    subscription_status: str | None = None,
    current_period_end: dt.datetime | None = None,
    cancel_at_period_end: bool | None = None,
    extra_site_subscription_item_id: str | None = None,
    extra_site_quantity: int | None = None,
    commit: bool = True,
) -> SitePlan | None:
    record = None
    if site_id:
        record = await session.get(SitePlan, site_id)
    if not record and subscription_id:
        record = (
            await session.execute(select(SitePlan).where(SitePlan.stripe_subscription_id == subscription_id))
        ).scalar_one_or_none()
    if not record and customer_id:
        record = (
            await session.execute(select(SitePlan).where(SitePlan.stripe_customer_id == customer_id))
        ).scalar_one_or_none()

    now = dt.datetime.now(dt.timezone.utc)
    if record:
        if plan:
            record.plan = normalize_plan(plan)
        if customer_id:
            record.stripe_customer_id = customer_id
        if subscription_id:
            record.stripe_subscription_id = subscription_id
        if current_period_end is not None:
            record.stripe_current_period_end = current_period_end
        if cancel_at_period_end is not None:
            record.stripe_cancel_at_period_end = cancel_at_period_end
        if extra_site_subscription_item_id is not None:
            record.extra_site_subscription_item_id = extra_site_subscription_item_id
        if extra_site_quantity is not None:
            record.extra_site_quantity = max(0, int(extra_site_quantity))
        _apply_subscription_status(record, subscription_status, now=now)
        record.updated_at = now
    elif site_id:
        record = SitePlan(
            site_id=site_id,
            plan=normalize_plan(plan),
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            stripe_current_period_end=current_period_end,
            stripe_cancel_at_period_end=bool(cancel_at_period_end),
            extra_site_subscription_item_id=extra_site_subscription_item_id,
            extra_site_quantity=max(0, int(extra_site_quantity or 0)),
            created_at=now,
            updated_at=now,
        )
        _apply_subscription_status(record, subscription_status, now=now)
        session.add(record)
    if commit:
        await session.commit()
    return record


async def _find_site_plan_for_billing_event(
    session: AsyncSession,
    *,
    customer_id: str | None = None,
    subscription_id: str | None = None,
) -> SitePlan | None:
    if subscription_id:
        record = (
            await session.execute(select(SitePlan).where(SitePlan.stripe_subscription_id == subscription_id))
        ).scalar_one_or_none()
        if record:
            return record
    if customer_id:
        return (
            await session.execute(select(SitePlan).where(SitePlan.stripe_customer_id == customer_id))
        ).scalar_one_or_none()
    return None


async def _record_stripe_event_once(session: AsyncSession, event_id: str | None, event_type: str | None) -> bool:
    if not event_id:
        return True
    existing = await session.get(StripeEvent, event_id)
    if existing:
        return False
    session.add(StripeEvent(event_id=event_id, event_type=event_type or "unknown"))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return False
    return True


async def _owner_site_count(session: AsyncSession, site_id: str) -> int:
    site = await session.get(DashboardSite, site_id)
    return max(1, await owned_site_count(session, site.owner_username if site else None))


async def _extra_site_quantity_for_site(session: AsyncSession, site_id: str, plan: str) -> int:
    return additional_site_count(plan, await _owner_site_count(session, site_id))


async def _sync_extra_site_subscription_item(session: AsyncSession, record: SitePlan | None) -> None:
    if record is None or not record.stripe_subscription_id:
        return
    plan = effective_plan_for_record(record)
    if plan not in {"standard", "pro"}:
        record.extra_site_quantity = 0
        return

    quantity = await _extra_site_quantity_for_site(session, record.site_id, plan)
    if quantity <= 0:
        if record.extra_site_subscription_item_id:
            try:
                stripe.SubscriptionItem.delete(record.extra_site_subscription_item_id, proration_behavior="none")
            except stripe.error.StripeError:
                logger.exception("Stripe additional-site subscription item removal failed")
                return
        record.extra_site_subscription_item_id = None
        record.extra_site_quantity = 0
        return

    if record.extra_site_quantity == quantity and record.extra_site_subscription_item_id:
        return

    price_id = _additional_site_price_id()
    try:
        subscription = stripe.Subscription.retrieve(record.stripe_subscription_id)
        existing_item_id = record.extra_site_subscription_item_id
        existing_quantity = record.extra_site_quantity
        for item in _stripe_items(subscription):
            if _price_id_for_item(item) == price_id:
                existing_item_id = _object_get(item, "id")
                try:
                    existing_quantity = int(_object_get(item, "quantity", 0) or 0)
                except (TypeError, ValueError):
                    existing_quantity = 0
                break

        if existing_item_id:
            if existing_quantity != quantity:
                stripe.SubscriptionItem.modify(existing_item_id, quantity=quantity, proration_behavior="none")
            record.extra_site_subscription_item_id = existing_item_id
            record.extra_site_quantity = quantity
            return

        item = stripe.SubscriptionItem.create(
            subscription=record.stripe_subscription_id,
            price=price_id,
            quantity=quantity,
            proration_behavior="none",
        )
        record.extra_site_subscription_item_id = _object_get(item, "id")
        record.extra_site_quantity = quantity
    except stripe.error.StripeError:
        logger.exception("Stripe additional-site subscription item sync failed")


def _billing_payment_status(record: SitePlan | None, plan: str) -> str:
    if record is None:
        return "ok"
    stored_plan = normalize_plan(record.plan)
    status_value = (record.stripe_subscription_status or "").strip().lower()
    if status_value in GRACE_SUBSCRIPTION_STATUSES:
        grace_ends_at = record.billing_grace_ends_at
        if grace_ends_at and grace_ends_at.tzinfo is None:
            grace_ends_at = grace_ends_at.replace(tzinfo=dt.timezone.utc)
        if grace_ends_at and dt.datetime.now(dt.timezone.utc) <= grace_ends_at:
            return "grace"
        return "downgraded" if stored_plan != "free" and plan == "free" else "past_due"
    if status_value in ENDED_SUBSCRIPTION_STATUSES and stored_plan != "free":
        return "downgraded"
    return "ok"


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
    line_items = [{"price": price_id, "quantity": 1}]
    extra_quantity = await _extra_site_quantity_for_site(session, payload.site_id, stored_plan) if stored_plan in {"standard", "pro"} else 0
    if extra_quantity > 0:
        line_items.append({"price": _additional_site_price_id(), "quantity": extra_quantity})

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            line_items=line_items,
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
    if record and settings.STRIPE_SECRET_KEY and settings.STRIPE_ADDITIONAL_SITE_PRICE_ID:
        stripe.api_key = settings.STRIPE_SECRET_KEY
        await _sync_extra_site_subscription_item(session, record)
        await session.commit()
    plan = effective_plan_for_record(record)
    entitlements = entitlements_for_plan(plan)
    has_subscription = bool(record and record.stripe_subscription_id)
    site = await session.get(DashboardSite, site_id)
    site_count = max(1, await owned_site_count(session, site.owner_username if site else None))
    billable_additional_sites = additional_site_count(plan, site_count) if plan in {"standard", "pro"} else 0
    return BillingStatusResponse(
        site_id=site_id,
        plan=entitlements.plan,  # type: ignore[arg-type]
        display_plan=entitlements.display_name,
        has_subscription=has_subscription,
        subscription_status=record.stripe_subscription_status if record else None,
        payment_status=_billing_payment_status(record, entitlements.plan),
        billing_grace_ends_at=record.billing_grace_ends_at if record else None,
        stripe_current_period_end=record.stripe_current_period_end if record else None,
        cancel_at_period_end=bool(record.stripe_cancel_at_period_end) if record else False,
        can_manage_billing=bool(has_subscription and settings.STRIPE_SECRET_KEY),
        included_sites=entitlements.included_sites,
        owned_site_count=site_count,
        additional_site_count=billable_additional_sites,
        extra_site_quantity=record.extra_site_quantity if record else 0,
        extra_site_price_usd=entitlements.extra_site_price_usd,
        aggregate_retention_days=entitlements.aggregate_retention_days,
        can_import_historical_data=entitlements.historical_imports,
        can_manage_anomaly_alerts=entitlements.anomaly_alerts,
        can_manage_site_access=entitlements.team_access,
        forecast_metrics=list(entitlements.forecast_metrics),
    )


@router.post("/billing/portal", response_model=BillingPortalSessionResponse, status_code=status.HTTP_200_OK)
async def create_billing_portal_session(
    payload: BillingPortalSessionRequest,
    auth_claims: dict | None = Depends(require_dashboard_auth),
    session: AsyncSession = Depends(get_session),
):
    await enforce_site_access_with_db(site_id=payload.site_id, claims=auth_claims, session=session)
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Stripe is not configured")
    record = await session.get(SitePlan, payload.site_id)
    if not record or not record.stripe_customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No Stripe customer is linked to this site")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return_url = _safe_redirect_url(payload.return_url, settings.STRIPE_CUSTOMER_PORTAL_RETURN_URL)
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=record.stripe_customer_id,
            return_url=return_url,
        )
    except stripe.error.StripeError as exc:
        logger.exception("Stripe billing portal session creation failed")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc.user_message or str(exc))) from exc
    return BillingPortalSessionResponse(portal_url=portal_session.url, session_id=portal_session.id)


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
    if not await _record_stripe_event_once(session, event.get("id"), event_type):
        return {"status": "duplicate"}

    if event_type == "checkout.session.completed":
        metadata = data_object.get("metadata") or {}
        record = await _upsert_site_plan(
            session,
            site_id=metadata.get("site_id") or data_object.get("client_reference_id"),
            customer_id=data_object.get("customer"),
            subscription_id=data_object.get("subscription"),
            plan=metadata.get("plan") or "free",
            subscription_status="active",
            commit=False,
        )
        await _sync_extra_site_subscription_item(session, record)
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        price_id = _base_subscription_price_id(data_object)
        metadata = data_object.get("metadata") or {}
        plan_from_metadata = _normalize_plan(metadata.get("plan"))
        resolved_plan = plan_from_metadata or _plan_for_price_id(price_id)
        status_fields = _subscription_status_fields(data_object)
        record = await _upsert_site_plan(
            session,
            site_id=metadata.get("site_id"),
            customer_id=data_object.get("customer"),
            subscription_id=data_object.get("id"),
            plan=resolved_plan,
            subscription_status=status_fields["subscription_status"],
            current_period_end=status_fields["current_period_end"],
            cancel_at_period_end=status_fields["cancel_at_period_end"],
            extra_site_subscription_item_id=status_fields["extra_site_subscription_item_id"],
            extra_site_quantity=status_fields["extra_site_quantity"],
            commit=False,
        )
        await _sync_extra_site_subscription_item(session, record)
    elif event_type == "customer.subscription.deleted":
        metadata = data_object.get("metadata") or {}
        await _upsert_site_plan(
            session,
            site_id=metadata.get("site_id"),
            customer_id=data_object.get("customer"),
            subscription_id=data_object.get("id"),
            plan="free",
            subscription_status="canceled",
            current_period_end=_timestamp_to_datetime(data_object.get("current_period_end")),
            cancel_at_period_end=bool(data_object.get("cancel_at_period_end", False)),
            extra_site_subscription_item_id=None,
            extra_site_quantity=0,
            commit=False,
        )
    elif event_type == "invoice.payment_failed":
        subscription_id = data_object.get("subscription")
        customer_id = data_object.get("customer")
        record = await _find_site_plan_for_billing_event(
            session,
            customer_id=customer_id,
            subscription_id=subscription_id,
        )
        if record:
            now = dt.datetime.now(dt.timezone.utc)
            record.stripe_subscription_status = "past_due"
            record.billing_past_due_at = now
            record.billing_grace_ends_at = now + dt.timedelta(days=settings.STRIPE_PAYMENT_FAILURE_GRACE_DAYS)
            record.updated_at = now
        logger.warning("Invoice payment failed", extra={"invoice_id": data_object.get("id"), "site_id": record.site_id if record else None})
    elif event_type in {"invoice.payment_succeeded", "invoice.paid"}:
        subscription_id = data_object.get("subscription")
        customer_id = data_object.get("customer")
        record = await _find_site_plan_for_billing_event(
            session,
            customer_id=customer_id,
            subscription_id=subscription_id,
        )
        if record:
            record.stripe_subscription_status = "active"
            record.billing_past_due_at = None
            record.billing_grace_ends_at = None
            record.updated_at = dt.datetime.now(dt.timezone.utc)

    await session.commit()
    return {"status": "ok"}
